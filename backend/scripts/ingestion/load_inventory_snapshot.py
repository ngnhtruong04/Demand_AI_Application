"""Validate and load the demo inventory snapshot CSV into core.inventory_snapshot."""

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from scripts.ingestion.common import compute_file_sha256, get_master_connection

EXPECTED_COLUMNS = (
    "unique_id", "avg_daily_sales", "lead_time_days", "safety_stock",
    "reorder_point", "current_stock", "status",
)

SCENARIO_GROUPS = {
    "In Stock": "In Stock",
    "Monitor / Pre-alert": "Monitor",
    "Reorder (Need to Order)": "Reorder",
    "Critical / Danger": "Critical",
    "Deadstock / Obsolete": "Deadstock",
}


class InventorySnapshotValidationError(ValueError):
    """Raised when the demo inventory CSV is not safe to load."""


@dataclass(frozen=True)
class InventorySnapshotRow:
    unique_id: str
    avg_daily_sales: float
    lead_time_days: int
    safety_stock: float
    reorder_point: float
    current_stock: int
    scenario_group: str


def _nonnegative_float(value: str, field: str, line: int) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InventorySnapshotValidationError(f"line {line}: {field} must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise InventorySnapshotValidationError(f"line {line}: {field} must be finite and non-negative")
    return parsed


def _nonnegative_int(value: str, field: str, line: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InventorySnapshotValidationError(f"line {line}: {field} must be an integer") from exc
    if parsed < 0:
        raise InventorySnapshotValidationError(f"line {line}: {field} must be non-negative")
    return parsed


def read_inventory_snapshot(file_path: str | Path) -> list[InventorySnapshotRow]:
    path = Path(file_path)
    if not path.is_file():
        raise InventorySnapshotValidationError(f"file not found: {path}")

    rows: list[InventorySnapshotRow] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise InventorySnapshotValidationError(
                f"unexpected CSV columns: expected {EXPECTED_COLUMNS}, got {tuple(reader.fieldnames or ())}"
            )

        for line, raw in enumerate(reader, start=2):
            unique_id = (raw["unique_id"] or "").strip()
            if not unique_id:
                raise InventorySnapshotValidationError(f"line {line}: unique_id is required")
            if unique_id in seen_ids:
                raise InventorySnapshotValidationError(f"line {line}: duplicate unique_id {unique_id!r}")
            seen_ids.add(unique_id)

            source_status = (raw["status"] or "").strip()
            if source_status not in SCENARIO_GROUPS:
                raise InventorySnapshotValidationError(f"line {line}: unsupported status {source_status!r}")

            rows.append(InventorySnapshotRow(
                unique_id=unique_id,
                avg_daily_sales=_nonnegative_float(raw["avg_daily_sales"], "avg_daily_sales", line),
                lead_time_days=_nonnegative_int(raw["lead_time_days"], "lead_time_days", line),
                safety_stock=_nonnegative_float(raw["safety_stock"], "safety_stock", line),
                reorder_point=_nonnegative_float(raw["reorder_point"], "reorder_point", line),
                current_stock=_nonnegative_int(raw["current_stock"], "current_stock", line),
                scenario_group=SCENARIO_GROUPS[source_status],
            ))

    if not rows:
        raise InventorySnapshotValidationError("CSV contains no data rows")
    return rows


def _missing_inventory_ids(cursor: Any, rows: Iterable[InventorySnapshotRow]) -> list[str]:
    unique_ids = [row.unique_id for row in rows]
    cursor.execute("SELECT unique_id FROM core.inventory WHERE unique_id = ANY(%s)", (unique_ids,))
    existing = {record[0] for record in cursor.fetchall()}
    return sorted(set(unique_ids) - existing)


def expected_snapshot_date(last_sales_date: date | None) -> date:
    """Return the opening date of the forecast period."""
    if last_sales_date is None:
        raise InventorySnapshotValidationError(
            "core.sales_daily is empty; cannot align snapshot_date with the forecast cutoff"
        )
    return last_sales_date + timedelta(days=1)


def _validate_snapshot_date(cursor: Any, snapshot_date: date) -> None:
    cursor.execute("SELECT max(date) FROM core.sales_daily")
    last_sales_date = cursor.fetchone()[0]
    expected = expected_snapshot_date(last_sales_date)
    if snapshot_date != expected:
        raise InventorySnapshotValidationError(
            f"snapshot_date must be {expected}, the day after the latest sales date "
            f"{last_sales_date}; got {snapshot_date}"
        )


def load_inventory_snapshot(
    file_path: str | Path,
    snapshot_date: date,
    *,
    dry_run: bool = False,
    replace: bool = False,
) -> tuple[str, int]:
    path = Path(file_path).resolve()
    rows = read_inventory_snapshot(path)
    file_sha256 = compute_file_sha256(path)

    with get_master_connection() as connection:
        try:
            with connection.cursor() as cursor:
                _validate_snapshot_date(cursor, snapshot_date)
                missing_ids = _missing_inventory_ids(cursor, rows)
                if missing_ids:
                    preview = ", ".join(missing_ids[:10])
                    suffix = " ..." if len(missing_ids) > 10 else ""
                    raise InventorySnapshotValidationError(
                        f"{len(missing_ids)} unique_id values do not exist in core.inventory: {preview}{suffix}"
                    )

                cursor.execute(
                    """SELECT count(*), count(DISTINCT source_sha256), min(source_sha256)
                       FROM core.inventory_snapshot WHERE snapshot_date = %s""",
                    (snapshot_date,),
                )
                existing_count, checksum_count, existing_checksum = cursor.fetchone()
                if existing_count:
                    unchanged = existing_count == len(rows) and checksum_count == 1 and existing_checksum == file_sha256
                    if unchanged and not replace:
                        connection.rollback()
                        return "skipped", len(rows)
                    if not replace:
                        raise InventorySnapshotValidationError(
                            f"snapshot {snapshot_date} already contains {existing_count} rows; use --replace"
                        )
                    cursor.execute("DELETE FROM core.inventory_snapshot WHERE snapshot_date = %s", (snapshot_date,))

                cursor.executemany(
                    """INSERT INTO core.inventory_snapshot (
                         unique_id, snapshot_date, current_stock, lead_time_days,
                         safety_stock, baseline_avg_daily_sales, baseline_reorder_point,
                         scenario_group, source_file, source_sha256, is_demo)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)""",
                    [(
                        row.unique_id, snapshot_date, row.current_stock, row.lead_time_days,
                        row.safety_stock, row.avg_daily_sales, row.reorder_point,
                        row.scenario_group, path.name, file_sha256,
                    ) for row in rows],
                )
                cursor.execute("SELECT count(*) FROM core.inventory_snapshot WHERE snapshot_date = %s", (snapshot_date,))
                loaded_count = cursor.fetchone()[0]
                if loaded_count != len(rows):
                    raise RuntimeError(f"loaded {loaded_count} rows, expected {len(rows)}")

            if dry_run:
                connection.rollback()
                return "validated", len(rows)
            connection.commit()
            return "loaded", len(rows)
        except Exception:
            connection.rollback()
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="Path to static_inventory_by_item.csv")
    parser.add_argument("--snapshot-date", required=True, type=date.fromisoformat, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Validate and roll back all database writes")
    parser.add_argument("--replace", action="store_true", help="Replace only the selected snapshot date")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result, row_count = load_inventory_snapshot(
            args.file, args.snapshot_date, dry_run=args.dry_run, replace=args.replace,
        )
    except (InventorySnapshotValidationError, OSError, ValueError) as exc:
        print(f"Inventory snapshot load failed: {exc}")
        return 1
    print(f"Inventory snapshot {result}: {row_count} rows for {args.snapshot_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
