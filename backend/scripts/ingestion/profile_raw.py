import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from scripts.ingestion.common import (
    compute_file_sha256,
    load_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_REGEX = re.compile(r"^-?\d+$")
FLOAT_REGEX = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def infer_value_type(val: str) -> str:
    """Infer the primitive type of a single non-empty string."""
    if INT_REGEX.match(val):
        return "INTEGER"
    if FLOAT_REGEX.match(val):
        return "DOUBLE PRECISION"
    if DATE_REGEX.match(val):
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return "DATE"
        except ValueError:
            pass
    return "TEXT"


def profile_file(
    file_path: Path,
    dataset_info: dict[str, Any],
    candidate_key_cols: list[str],
) -> dict[str, Any]:
    """Profile a single CSV file according to specification."""
    file_size_bytes = file_path.stat().st_size
    logger.info("Computing SHA-256 for %s (%d bytes)...", file_path.name, file_size_bytes)
    file_sha256 = compute_file_sha256(file_path)

    logger.info("Profiling columns and data for %s...", file_path.name)
    start_time = time.time()

    col_names: list[str] = []
    col_stats: dict[str, dict[str, Any]] = {}
    candidate_key_indices: list[int] = []
    seen_candidate_keys: set[Any] = set()
    candidate_duplicates_count = 0
    candidate_duplicate_samples: list[str] = []

    total_rows = 0

    with file_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"File {file_path.name} is empty")

        col_names = [c.strip() for c in header]
        if not col_names or any(not c for c in col_names):
            raise ValueError(f"Invalid header in {file_path.name}: {header}")

        # Map candidate key columns to indices
        if candidate_key_cols:
            for ck in candidate_key_cols:
                if ck in col_names:
                    candidate_key_indices.append(col_names.index(ck))
                else:
                    logger.warning("Candidate key col '%s' not in %s header", ck, file_path.name)

        # Initialize column stats
        for col in col_names:
            col_stats[col] = {
                "null_count": 0,
                "max_length": 0,
                "inferred_types": set(),
                "min_val": None,
                "max_val": None,
                "samples": [],
                "distinct_count_estimate": 0,
            }

        # Sets for distinct tracking (capped for high cardinality)
        distinct_sets: dict[str, set[str]] = {col: set() for col in col_names}
        max_distinct_tracked = 200000

        for row_idx, row in enumerate(reader, start=1):
            total_rows += 1
            if len(row) != len(col_names):
                raise ValueError(
                    f"Row {row_idx} in {file_path.name} has {len(row)} columns, expected {len(col_names)}"
                )

            # Check candidate key uniqueness
            if candidate_key_indices:
                key = tuple(row[idx] for idx in candidate_key_indices)
                if key in seen_candidate_keys:
                    candidate_duplicates_count += 1
                    if len(candidate_duplicate_samples) < 5:
                        candidate_duplicate_samples.append(str(key))
                else:
                    seen_candidate_keys.add(key)

            # Column-level profiling
            for idx, col in enumerate(col_names):
                val = row[idx]
                stats = col_stats[col]
                dset = distinct_sets[col]

                val_len = len(val)
                if val_len > stats["max_length"]:
                    stats["max_length"] = val_len

                if val == "":
                    stats["null_count"] += 1
                else:
                    if len(dset) < max_distinct_tracked:
                        dset.add(val)

                    if len(stats["samples"]) < 5 and val not in stats["samples"]:
                        stats["samples"].append(val)

                    val_type = infer_value_type(val)
                    stats["inferred_types"].add(val_type)

                    # Update min / max
                    if val_type == "INTEGER":
                        int_v = int(val)
                        if stats["min_val"] is None or int_v < stats["min_val"]:
                            stats["min_val"] = int_v
                        if stats["max_val"] is None or int_v > stats["max_val"]:
                            stats["max_val"] = int_v
                    elif val_type == "DOUBLE PRECISION":
                        float_v = float(val)
                        if stats["min_val"] is None or float_v < stats["min_val"]:
                            stats["min_val"] = float_v
                        if stats["max_val"] is None or float_v > stats["max_val"]:
                            stats["max_val"] = float_v
                    elif val_type == "DATE":
                        if stats["min_val"] is None or val < stats["min_val"]:
                            stats["min_val"] = val
                        if stats["max_val"] is None or val > stats["max_val"]:
                            stats["max_val"] = val

            if total_rows % 1000000 == 0:
                logger.info("Processed %d rows for %s...", total_rows, file_path.name)

    # Finalize inferred column types and stats
    final_columns: dict[str, Any] = {}
    for col in col_names:
        stats = col_stats[col]
        types = stats["inferred_types"]

        if not types:
            inferred_pg_type = "TEXT"
        elif "TEXT" in types:
            inferred_pg_type = "TEXT"
        elif "DOUBLE PRECISION" in types:
            inferred_pg_type = "DOUBLE PRECISION"
        elif "INTEGER" in types:
            # Check integer ranges
            min_v = stats["min_val"]
            max_v = stats["max_val"]
            if min_v is not None and max_v is not None and (min_v < -2147483648 or max_v > 2147483647):
                inferred_pg_type = "BIGINT"
            else:
                inferred_pg_type = "INTEGER"
        elif "DATE" in types:
            inferred_pg_type = "DATE"
        else:
            inferred_pg_type = "TEXT"

        # Check special case: if name is unique_id or ends with _id, plan specifies TEXT
        # to preserve leading zeroes or alphanumeric codes.
        if col.lower() in ("unique_id", "product_unique_id") or col.lower().endswith("_id"):
            inferred_pg_type = "TEXT"

        null_ratio = round(stats["null_count"] / total_rows, 6) if total_rows > 0 else 0.0

        dset_len = len(distinct_sets[col])
        distinct_count_info = dset_len if dset_len < max_distinct_tracked else f">{max_distinct_tracked}"

        final_columns[col] = {
            "inferred_pg_type": inferred_pg_type,
            "raw_types_seen": list(types),
            "null_count": stats["null_count"],
            "null_ratio": null_ratio,
            "max_length": stats["max_length"],
            "distinct_count": distinct_count_info,
            "min_val": stats["min_val"],
            "max_val": stats["max_val"],
            "sample_values": stats["samples"][:5],
        }

    elapsed = round(time.time() - start_time, 2)
    logger.info(
        "Finished profiling %s in %s seconds. Rows: %d, Duplicates on candidate key: %d",
        file_path.name,
        elapsed,
        total_rows,
        candidate_duplicates_count,
    )

    return {
        "dataset": dataset_info["name"],
        "file": file_path.name,
        "target_schema": dataset_info["schema"],
        "target_table": dataset_info["table"],
        "file_size_bytes": file_size_bytes,
        "file_sha256": file_sha256,
        "total_rows": total_rows,
        "columns_count": len(col_names),
        "ordered_columns": col_names,
        "columns": final_columns,
        "candidate_key": {
            "columns": candidate_key_cols,
            "is_unique": candidate_duplicates_count == 0,
            "duplicate_count": candidate_duplicates_count,
            "duplicate_samples": candidate_duplicate_samples,
        },
        "profiled_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
    }


def main() -> None:
    raw_dir = Path(settings.raw_data_dir)
    report_file = Path(settings.raw_profile_report)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        manifest = load_manifest()
    except Exception as e:
        logger.error("Failed to load manifest: %s", e)
        sys.exit(1)

    candidate_keys_map = {
        "sales_train": ["unique_id", "warehouse", "date"],
        "inventory": ["unique_id", "warehouse"],
        "calendar": ["warehouse", "date"],
        "test_weights": ["unique_id"],
    }

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": {},
    }

    # Verify all files exist
    missing_files = []
    for ds in manifest:
        fpath = raw_dir / ds["file"]
        if not fpath.is_file():
            missing_files.append(str(fpath))

    if missing_files:
        logger.error("Missing required raw CSV files: %s", missing_files)
        sys.exit(1)

    for ds in manifest:
        fpath = raw_dir / ds["file"]
        ck_cols = candidate_keys_map.get(ds["name"], [])
        try:
            profile_data = profile_file(fpath, ds, ck_cols)
            report["datasets"][ds["name"]] = profile_data
        except Exception as exc:
            logger.error("Error profiling %s: %s", ds["name"], exc, exc_info=True)
            sys.exit(1)

    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info("Raw data profiling report saved to %s", report_file)
    print(f"\nRaw profiling completed successfully. Report saved to {report_file}")


if __name__ == "__main__":
    main()
