from datetime import date
from pathlib import Path

import pytest

from scripts.ingestion.load_inventory_snapshot import (
    InventorySnapshotValidationError,
    expected_snapshot_date,
    read_inventory_snapshot,
)

HEADER = "unique_id,avg_daily_sales,lead_time_days,safety_stock,reorder_point,current_stock,status\n"


def write_csv(path: Path, rows: str) -> Path:
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def test_normalizes_all_demo_scenario_groups(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "inventory.csv",
        "1,10.5,2,3.5,24.5,50,In Stock\n"
        "2,10.5,2,3.5,24.5,20,Monitor / Pre-alert\n"
        "3,10.5,2,3.5,24.5,10,Reorder (Need to Order)\n"
        "4,10.5,2,3.5,24.5,0,Critical / Danger\n"
        "5,0,2,3.5,3.5,8,Deadstock / Obsolete\n",
    )
    rows = read_inventory_snapshot(path)
    assert [row.scenario_group for row in rows] == [
        "In Stock", "Monitor", "Reorder", "Critical", "Deadstock",
    ]


@pytest.mark.parametrize("row,error", [
    ("1,nan,2,3.5,24.5,50,In Stock\n", "finite and non-negative"),
    ("1,10.5,2,3.5,24.5,-1,In Stock\n", "must be non-negative"),
    ("1,10.5,2,3.5,24.5,50,Unknown\n", "unsupported status"),
])
def test_rejects_invalid_values(tmp_path: Path, row: str, error: str) -> None:
    path = write_csv(tmp_path / "inventory.csv", row)
    with pytest.raises(InventorySnapshotValidationError, match=error):
        read_inventory_snapshot(path)


def test_rejects_duplicate_unique_id(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "inventory.csv",
        "1,10.5,2,3.5,24.5,50,In Stock\n"
        "1,8.5,3,4.5,30,20,Monitor / Pre-alert\n",
    )
    with pytest.raises(InventorySnapshotValidationError, match="duplicate unique_id"):
        read_inventory_snapshot(path)


def test_expected_snapshot_date_is_day_after_sales_cutoff() -> None:
    assert expected_snapshot_date(date(2024, 6, 2)) == date(2024, 6, 3)


def test_expected_snapshot_date_requires_sales_history() -> None:
    with pytest.raises(InventorySnapshotValidationError, match="sales_daily is empty"):
        expected_snapshot_date(None)

