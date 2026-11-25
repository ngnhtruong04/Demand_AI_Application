import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg import sql

from app.core.config import settings
from scripts.ingestion.common import (
    compute_file_sha256,
    count_csv_data_rows,
    get_api_connection,
    get_master_connection,
    load_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPORT_FILE = BACKEND_ROOT / "reports" / "raw_validation.json"
REPORT_FILE = DEFAULT_REPORT_FILE


def validate_permissions() -> dict[str, Any]:
    """Validate permissions of tttv_demandforecast_api using PostgreSQL privilege functions."""
    logger.info("Validating permissions for %s...", settings.rds_api_username)
    api_user = settings.rds_api_username
    checks: dict[str, Any] = {}
    all_passed = True

    with get_master_connection() as conn:
        with conn.cursor() as cur:
            # 1. Database CONNECT
            cur.execute(
                "SELECT has_database_privilege(%s, current_database(), 'CONNECT')",
                (api_user,),
            )
            can_connect = cur.fetchone()[0]
            checks["connect_database"] = {"granted": can_connect, "expected": True, "pass": can_connect is True}
            if not can_connect:
                all_passed = False

            # 2. Schema USAGE & CREATE
            cur.execute("SELECT has_schema_privilege(%s, 'raw', 'USAGE')", (api_user,))
            has_usage = cur.fetchone()[0]
            checks["schema_raw_usage"] = {"granted": has_usage, "expected": True, "pass": has_usage is True}
            if not has_usage:
                all_passed = False

            cur.execute("SELECT has_schema_privilege(%s, 'raw', 'CREATE')", (api_user,))
            has_create = cur.fetchone()[0]
            checks["schema_raw_create"] = {"granted": has_create, "expected": False, "pass": has_create is False}
            if has_create:
                all_passed = False

            # 3. Table privileges
            table_checks: dict[str, Any] = {}
            for t in ["calendar", "inventory", "sales_train", "test_weights"]:
                tbl_name = f"raw.{t}"
                cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (api_user, tbl_name))
                can_select = cur.fetchone()[0]

                write_privs: dict[str, bool] = {}
                for priv in ["INSERT", "UPDATE", "DELETE", "TRUNCATE"]:
                    cur.execute("SELECT has_table_privilege(%s, %s, %s)", (api_user, tbl_name, priv))
                    write_privs[priv] = cur.fetchone()[0]

                writes_forbidden = all(not v for v in write_privs.values())
                passed = (can_select is True) and writes_forbidden
                if not passed:
                    all_passed = False

                table_checks[tbl_name] = {
                    "select_granted": can_select,
                    "write_privileges": write_privs,
                    "pass": passed,
                }

            # 4. ingestion_log must NOT be readable by API user
            cur.execute("SELECT has_table_privilege(%s, 'raw.ingestion_log', 'SELECT')", (api_user,))
            can_select_log = cur.fetchone()[0]
            table_checks["raw.ingestion_log"] = {
                "select_granted": can_select_log,
                "expected_select": False,
                "pass": can_select_log is False,
            }
            if can_select_log:
                all_passed = False

            checks["tables"] = table_checks

    # Also test actual connection using API credentials
    try:
        with get_api_connection() as api_conn:
            with api_conn.cursor() as cur:
                cur.execute("SELECT 1")
        checks["api_connection_test"] = {"status": "SUCCESS", "pass": True}
    except Exception as exc:
        checks["api_connection_test"] = {"status": "FAILED", "error": str(exc), "pass": False}
        all_passed = False

    checks["all_passed"] = all_passed
    return checks


def validate_datasets(manifest: list[dict[str, Any]], profile_data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Validate dataset row counts, checksums, and columns against PostgreSQL."""
    raw_dir = Path(settings.raw_data_dir)
    results: dict[str, Any] = {}
    all_passed = True

    with get_master_connection() as conn:
        with conn.cursor() as cur:
            for ds in manifest:
                ds_name = ds["name"]
                schema = ds["schema"]
                table = ds["table"]
                file_path = raw_dir / ds["file"]

                logger.info("Validating dataset %s...", ds_name)

                # Check file existence
                file_exists = file_path.is_file()
                if not file_exists:
                    results[ds_name] = {"error": f"File {file_path} does not exist", "pass": False}
                    all_passed = False
                    continue

                # SHA-256 and CSV row count
                current_sha256 = compute_file_sha256(file_path)
                csv_rows = count_csv_data_rows(file_path)

                # Query ingestion log
                cur.execute(
                    """
                    SELECT status, file_sha256, loaded_row_count, started_at, completed_at
                    FROM raw.ingestion_log
                    WHERE target_schema = %s AND target_table = %s
                    ORDER BY ingestion_id DESC LIMIT 1
                    """,
                    (schema, table),
                )
                log_row = cur.fetchone()
                if not log_row:
                    results[ds_name] = {"error": "No ingestion_log record found", "pass": False}
                    all_passed = False
                    continue

                log_status, log_sha, log_loaded, started_at, completed_at = log_row

                # Query database row count
                cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
                db_rows = cur.fetchone()[0]

                # Check column schema in DB
                cur.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (schema, table),
                )
                db_cols = {r[0]: r[1] for r in cur.fetchall()}

                # Match against profile columns if available
                ds_profile = profile_data.get("datasets", {}).get(ds_name, {})
                profile_cols = ds_profile.get("columns", {})

                cols_match = True
                col_details: dict[str, Any] = {}
                for col_name, pinfo in profile_cols.items():
                    exists_in_db = col_name in db_cols
                    if not exists_in_db:
                        cols_match = False
                    col_details[col_name] = {
                        "in_db": exists_in_db,
                        "db_data_type": db_cols.get(col_name),
                        "profile_inferred": pinfo.get("inferred_pg_type"),
                    }

                status_pass = log_status == "success"
                sha_match = current_sha256 == log_sha
                count_match = csv_rows == db_rows == (log_loaded or 0)

                ds_pass = status_pass and sha_match and count_match and cols_match
                if not ds_pass:
                    all_passed = False

                results[ds_name] = {
                    "file": ds["file"],
                    "csv_row_count": csv_rows,
                    "db_row_count": db_rows,
                    "ingestion_log": {
                        "status": log_status,
                        "loaded_rows": log_loaded,
                        "sha256": log_sha,
                        "started_at": started_at.isoformat() if started_at else None,
                        "completed_at": completed_at.isoformat() if completed_at else None,
                    },
                    "sha256_match": sha_match,
                    "count_match": count_match,
                    "columns_match": cols_match,
                    "columns": col_details,
                    "pass": ds_pass,
                }

    return results, all_passed


def validate_cross_table_reconciliation() -> dict[str, Any]:
    """Perform referential reconciliation across raw tables."""
    logger.info("Performing cross-table referential checks...")
    results: dict[str, Any] = {}

    with get_master_connection() as conn:
        with conn.cursor() as cur:
            # 1. sales_train items vs inventory items
            cur.execute(
                """
                SELECT count(*)
                FROM (
                    SELECT DISTINCT unique_id, warehouse FROM raw.sales_train
                    EXCEPT
                    SELECT unique_id, warehouse FROM raw.inventory
                ) sub
                """
            )
            unmatched_sales_inventory = cur.fetchone()[0]

            # Sample unmatched
            cur.execute(
                """
                SELECT unique_id, warehouse
                FROM (
                    SELECT DISTINCT unique_id, warehouse FROM raw.sales_train
                    EXCEPT
                    SELECT unique_id, warehouse FROM raw.inventory
                ) sub
                LIMIT 5
                """
            )
            samples_inv = cur.fetchall()

            # 2. sales_train dates/warehouses vs calendar
            cur.execute(
                """
                SELECT count(*)
                FROM (
                    SELECT DISTINCT warehouse, date FROM raw.sales_train
                    EXCEPT
                    SELECT warehouse, date FROM raw.calendar
                ) sub
                """
            )
            unmatched_sales_calendar = cur.fetchone()[0]

            results["sales_train_vs_inventory"] = {
                "unmatched_count": unmatched_sales_inventory,
                "sample_unmatched": [f"{r[0]}@{r[1]}" for r in samples_inv],
                "consistent": unmatched_sales_inventory == 0,
            }

            results["sales_train_vs_calendar"] = {
                "unmatched_count": unmatched_sales_calendar,
                "consistent": unmatched_sales_calendar == 0,
            }

    return results


def main() -> None:
    start_time = time.time()
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        manifest = load_manifest()
    except Exception as exc:
        logger.error("Failed to load manifest: %s", exc)
        sys.exit(1)

    profile_report_path = Path(settings.raw_profile_report)
    profile_data: dict[str, Any] = {}
    if profile_report_path.is_file():
        with profile_report_path.open("r", encoding="utf-8") as f:
            profile_data = json.load(f)

    # 1. Validate permissions
    perm_results = validate_permissions()

    # 2. Validate datasets
    ds_results, ds_passed = validate_datasets(manifest, profile_data)

    # 3. Cross-table reconciliation
    recon_results = validate_cross_table_reconciliation()

    overall_pass = perm_results.get("all_passed", False) and ds_passed

    report = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": "PASS" if overall_pass else "FAIL",
        "permission_checks": perm_results,
        "dataset_checks": ds_results,
        "cross_table_reconciliation": recon_results,
        "elapsed_seconds": round(time.time() - start_time, 2),
    }

    with REPORT_FILE.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info("Validation report written to %s", REPORT_FILE)
    print(f"\nRaw Validation Result: {'PASS' if overall_pass else 'FAIL'}")
    print(f"Report saved to {REPORT_FILE}")

    if not overall_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
