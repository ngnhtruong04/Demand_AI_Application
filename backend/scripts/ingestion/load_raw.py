import argparse
import csv
import itertools
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg import sql

from app.core.config import settings
from scripts.ingestion.common import (
    ManifestValidationError,
    compute_file_sha256,
    count_csv_data_rows,
    get_dataset_by_name,
    get_master_connection,
    load_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

LOAD_ORDER = ["calendar", "inventory", "test_weights", "sales_train"]


def load_dataset(
    dataset: dict[str, Any],
    dry_run: bool = False,
    limit: Optional[int] = None,
    replace: bool = False,
) -> bool:
    """
    Execute bulk ingestion for a single dataset via psycopg 3 COPY FROM STDIN.
    Returns True on success/skip, False on failure.
    """
    raw_dir = Path(settings.raw_data_dir)
    file_path = raw_dir / dataset["file"]
    schema = dataset["schema"]
    table = dataset["table"]
    ds_name = dataset["name"]

    if not file_path.is_file():
        logger.error("Dataset %s: File not found at %s", ds_name, file_path)
        return False

    file_size = file_path.stat().st_size
    file_sha256 = compute_file_sha256(file_path)
    sha_short = file_sha256[:8]

    # Inspect CSV header
    with file_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)

    if not header:
        logger.error("Dataset %s: Empty or unreadable CSV header", ds_name)
        return False

    columns = [col.strip() for col in header]

    # If limit is specified for dry-run or partial load, expected rows is min(limit, total)
    total_data_rows = count_csv_data_rows(file_path)
    expected_rows = min(limit, total_data_rows) if limit is not None else total_data_rows

    logger.info(
        "Preparing dataset %s (file: %s, size: %d, sha256: %s..., rows: %d, dry_run: %s, replace: %s)",
        ds_name,
        file_path.name,
        file_size,
        sha_short,
        expected_rows,
        dry_run,
        replace,
    )

    if dry_run:
        # Dry run: open transaction, copy sample, check cast & count, rollback
        start_time = time.time()
        success = False
        try:
            with get_master_connection() as conn:
                try:
                    with conn.cursor() as cur:
                        # Stream sample rows via COPY.
                        copy_query = sql.SQL(
                            "COPY {}.{} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, DELIMITER ',', NULL '')"
                        ).format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                            sql.SQL(", ").join([sql.Identifier(c) for c in columns]),
                        )

                        with file_path.open("r", encoding="utf-8", newline="") as f:
                            lines_to_stream = itertools.islice(f, expected_rows + 1)  # +1 for header
                            with cur.copy(copy_query) as copy:
                                for line in lines_to_stream:
                                    copy.write(line)

                        # COPY's command result counts only this operation, unlike
                        # table-count deltas that include concurrent commits.
                        loaded_count = cur.rowcount

                        if loaded_count != expected_rows:
                            logger.error(
                                "DRY RUN FAILED for %s: loaded %d rows, expected %d",
                                ds_name,
                                loaded_count,
                                expected_rows,
                            )
                            success = False
                        else:
                            logger.info(
                                "DRY RUN SUCCESS for %s: verified %d sample rows in %.2fs (cast and schema valid)",
                                ds_name,
                                loaded_count,
                                time.time() - start_time,
                            )
                            success = True
                finally:
                    # Explicitly rollback before connection context manager exits on ALL paths:
                    # success, mismatch, or exception, guaranteeing sample rows are never committed.
                    conn.rollback()
            return success
        except Exception as exc:
            logger.error("DRY RUN ERROR for %s: %s", ds_name, exc, exc_info=True)
            return False

    # 1. Full Ingestion: check existing status in raw.ingestion_log
    with get_master_connection() as conn:
        with conn.cursor() as cur:
            # Check if this exact file sha256 was already successfully loaded
            cur.execute(
                """
                SELECT status, loaded_row_count
                FROM raw.ingestion_log
                WHERE target_schema = %s AND target_table = %s AND file_sha256 = %s
                """,
                (schema, table, file_sha256),
            )
            existing_log = cur.fetchone()

            # Check if table already has rows with different checksum
            count_query = sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table),
            )
            cur.execute(count_query)
            existing_table_count = cur.fetchone()[0]

    if existing_log and existing_log[0] == "success":
        if not replace:
            logger.info(
                "SKIPPED %s: File with SHA-256 %s already successfully ingested (%d rows). Use --replace to overwrite.",
                ds_name,
                sha_short,
                existing_log[1],
            )
            return True

    if existing_table_count > 0 and not replace:
        logger.error(
            "ABORTED %s: Table %s.%s already contains %d rows, but checksum differs or file not recorded as success. Specify --replace to overwrite safely.",
            ds_name,
            schema,
            table,
            existing_table_count,
        )
        return False

    # 2. Record status = 'running' in raw.ingestion_log in a dedicated committed transaction
    ingestion_id = None
    with get_master_connection() as log_conn:
        with log_conn.cursor() as log_cur:
            log_cur.execute(
                """
                INSERT INTO raw.ingestion_log (
                    source_file, target_schema, target_table,
                    file_sha256, file_size_bytes, expected_row_count,
                    status, started_at, completed_at, error_message
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, 'running', NOW(), NULL, NULL
                )
                ON CONFLICT (target_schema, target_table, file_sha256)
                DO UPDATE SET
                    status = 'running',
                    started_at = NOW(),
                    completed_at = NULL,
                    error_message = NULL,
                    loaded_row_count = NULL
                RETURNING ingestion_id;
                """,
                (dataset["file"], schema, table, file_sha256, file_size, expected_rows),
            )
            ingestion_id = log_cur.fetchone()[0]
        log_conn.commit()

    # 3. Perform Load in a separate transaction
    start_time = time.time()
    try:
        with get_master_connection() as load_conn:
            with load_conn.cursor() as cur:
                if replace:
                    truncate_query = sql.SQL("TRUNCATE TABLE {}.{}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                    logger.info("Truncating table %s.%s (--replace enabled)", schema, table)
                    cur.execute(truncate_query)

                copy_query = sql.SQL(
                    "COPY {}.{} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, DELIMITER ',', NULL '')"
                ).format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    sql.SQL(", ").join([sql.Identifier(c) for c in columns]),
                )

                logger.info("Streaming CSV rows into %s.%s via COPY...", schema, table)
                with file_path.open("r", encoding="utf-8", newline="") as f:
                    lines_to_stream = (
                        itertools.islice(f, expected_rows + 1)
                        if limit is not None
                        else f
                    )
                    with cur.copy(copy_query) as copy:
                        for line in lines_to_stream:
                            copy.write(line)

                # Verify loaded row count
                cur.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                )
                loaded_count = cur.fetchone()[0]

                if loaded_count != expected_rows:
                    raise ValueError(
                        f"Row count mismatch: expected {expected_rows}, but loaded {loaded_count}"
                    )

            # Commit load transaction
            load_conn.commit()

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            "SUCCESS: Ingested %d rows into %s.%s in %.2fs",
            loaded_count,
            schema,
            table,
            elapsed,
        )

        # 4. Update log to success
        with get_master_connection() as log_conn:
            with log_conn.cursor() as log_cur:
                log_cur.execute(
                    """
                    UPDATE raw.ingestion_log
                    SET status = 'success',
                        completed_at = NOW(),
                        loaded_row_count = %s,
                        error_message = NULL
                    WHERE ingestion_id = %s
                    """,
                    (loaded_count, ingestion_id),
                )
            log_conn.commit()

        return True

    except Exception as exc:
        elapsed = round(time.time() - start_time, 2)
        logger.error(
            "FAILED: Ingestion for %s failed after %.2fs: %s",
            ds_name,
            elapsed,
            exc,
            exc_info=True,
        )

        # Update log to failed
        try:
            with get_master_connection() as log_conn:
                with log_conn.cursor() as log_cur:
                    log_cur.execute(
                        """
                        UPDATE raw.ingestion_log
                        SET status = 'failed',
                            completed_at = NOW(),
                            error_message = %s
                        WHERE ingestion_id = %s
                        """,
                        (str(exc), ingestion_id),
                    )
                log_conn.commit()
        except Exception as log_exc:
            logger.error("Failed to update ingestion_log to failed status: %s", log_exc)

        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Rohlik Raw Ingestion Loader")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Ingest all 4 raw datasets in order")
    group.add_argument("--dataset", type=str, help="Ingest a specific dataset from allowlist")

    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without committing")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows to load")
    parser.add_argument("--replace", action="store_true", help="Truncate table and replace data")

    args = parser.parse_args()

    try:
        manifest = load_manifest()
    except ManifestValidationError as e:
        logger.error("Manifest error: %s", e)
        sys.exit(1)

    datasets_to_run = []
    if args.all:
        manifest_by_name = {d["name"]: d for d in manifest}
        # Enforce exact order from spec: calendar -> inventory -> test_weights -> sales_train
        for name in LOAD_ORDER:
            if name in manifest_by_name:
                datasets_to_run.append(manifest_by_name[name])
    else:
        try:
            dataset = get_dataset_by_name(args.dataset)
            datasets_to_run.append(dataset)
        except ManifestValidationError as e:
            logger.error("%s", e)
            sys.exit(1)

    all_success = True
    for ds in datasets_to_run:
        limit_val = args.limit
        if args.dry_run and limit_val is None:
            limit_val = 1000

        success = load_dataset(
            dataset=ds,
            dry_run=args.dry_run,
            limit=limit_val,
            replace=args.replace,
        )
        if not success:
            all_success = False
            logger.error("Ingestion failed on dataset '%s'. Stopping pipeline.", ds["name"])
            break

    if not all_success:
        sys.exit(1)

    print("\nAll requested ingestions completed successfully.")


if __name__ == "__main__":
    main()
