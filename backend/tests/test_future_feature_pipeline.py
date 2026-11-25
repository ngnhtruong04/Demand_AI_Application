"""test_future_feature_pipeline.py — Test create_future_feature_frame with run_feature_engineering.

Generates 2 expected DataFrames:
1. 30d on SINGLE unique_id with full features engineered.
2. FUTURE 14d of that same item with full features engineered
   (lag sales values filled from history until no longer available).
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.pipeline.feature_engineering import (
    DEFAULT_CONFIG,
    DatasetSplits,
    create_future_feature_frame,
    run_feature_engineering,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
RAW_30D_PATH = BACKEND_ROOT / "data" / "test" / "raw_test_30d.csv"


def dummy_emit(step: str, status: str, detail: Any) -> None:
    pass


def run_test():
    # 1. Load 30d single item raw data
    assert RAW_30D_PATH.is_file(), f"File not found: {RAW_30D_PATH}"
    raw_30d = pl.read_csv(RAW_30D_PATH)
    raw_30d = raw_30d.with_columns(pl.col("date").cast(pl.Date))

    unique_id = raw_30d["unique_id"][0]
    assert raw_30d["unique_id"].n_unique() == 1, "Expected single unique_id"
    assert raw_30d.height == 30, f"Expected 30 rows, got {raw_30d.height}"

    max_hist_date = raw_30d["date"].max()
    min_hist_date = raw_30d["date"].min()
    print(f"Loaded raw 30d for item {unique_id}: {min_hist_date} to {max_hist_date} ({raw_30d.height} rows)")

    # 2. Run feature engineering on 30d historical frame -> DF 1
    artifacts_30d = run_feature_engineering(
        splits=raw_30d,
        config=DEFAULT_CONFIG,
        emit=dummy_emit,
        save=False,
    )
    df_30d_engineered = artifacts_30d.splits.test
    print(f"DF 1 (30d historical engineered) shape: {df_30d_engineered.shape}")
    assert df_30d_engineered.height == 30

    # 3. Create future feature frame (14 days)
    horizon_days = 14
    future_raw = create_future_feature_frame(
        test_frame=raw_30d,
        horizon_days=horizon_days,
        config=DEFAULT_CONFIG,
    )
    print(f"Future raw shape: {future_raw.shape}")
    assert future_raw.height == horizon_days
    assert future_raw["sales"].null_count() == horizon_days, "Future sales must all be NULL"

    future_min_date = future_raw["date"].min()
    future_max_date = future_raw["date"].max()
    assert future_min_date == max_hist_date + datetime.timedelta(days=1)
    assert future_max_date == max_hist_date + datetime.timedelta(days=14)

    # 4. Combine history + future to allow lag lookups from history into future
    combined_raw = pl.concat([raw_30d, future_raw], how="vertical")
    assert combined_raw.height == 30 + horizon_days

    artifacts_combined = run_feature_engineering(
        splits=combined_raw,
        config=DEFAULT_CONFIG,
        emit=dummy_emit,
        save=False,
    )
    df_combined_engineered = artifacts_combined.splits.test

    # Sliced DF 2: Future 14d with full features engineered
    df_future_engineered = df_combined_engineered.filter(
        pl.col("date") > max_hist_date
    )
    print(f"DF 2 (14d future engineered) shape: {df_future_engineered.shape}")
    assert df_future_engineered.height == 14

    # 5. Verify sales lags behavior in future frame
    # Day 1 (cutoff + 1 day): lag 1 looks back 1 day -> cutoff date (in history, known!)
    day1_row = df_future_engineered.filter(pl.col("date") == future_min_date)
    assert day1_row["sales_1"][0] is not None, "Day 1 sales_1 should be filled from cutoff date"
    assert day1_row["sales_7"][0] is not None, "Day 1 sales_7 should be filled from history"
    assert day1_row["sales_14"][0] is not None, "Day 1 sales_14 should be filled from history"

    # Day 2: lag 1 looks back to Day 1 (future sales=NULL) -> None!
    # But lag 2 looks back to cutoff date (history) -> filled!
    day2_date = future_min_date + datetime.timedelta(days=1)
    day2_row = df_future_engineered.filter(pl.col("date") == day2_date)
    assert day2_row["sales_1"][0] is None, "Day 2 sales_1 should be None (waiting for prediction)"
    assert day2_row["sales_2"][0] is not None, "Day 2 sales_2 should be filled from cutoff date"

    # Day 14: lags 1..7 need future sales -> None
    # lag 14 looks back 14 days -> cutoff date -> filled!
    day14_row = df_future_engineered.filter(pl.col("date") == future_max_date)
    assert day14_row["sales_1"][0] is None, "Day 14 sales_1 should be None"
    assert day14_row["sales_7"][0] is None, "Day 14 sales_7 should be None"
    assert day14_row["sales_14"][0] is not None, "Day 14 sales_14 should be filled from cutoff date"
    assert day14_row["sales_21"][0] is not None, "Day 14 sales_21 should be filled from history"
    assert day14_row["sales_28"][0] is not None, "Day 14 sales_28 should be filled from history"

    print("\nAll lag assertions passed successfully!")
    print("\n--- DF 1 (30d Historical Features) ---")
    print(df_30d_engineered.select(["unique_id", "date", "sales", "sales_1", "sales_7", "sales_14", "max_discount", "discounted_price"]).head(3))
    print(df_30d_engineered.select(["unique_id", "date", "sales", "sales_1", "sales_7", "sales_14", "max_discount", "discounted_price"]).tail(3))

    # 6. Save test outputs to backend/data/test for review
    test_dir = BACKEND_ROOT / "data" / "test"
    test_dir.mkdir(parents=True, exist_ok=True)

    # Historical 30d engineered
    df_30d_engineered.write_csv(test_dir / "feature_engineered_30d.csv")
    df_30d_engineered.write_parquet(test_dir / "feature_engineered_30d.parquet")
    df_30d_engineered.write_csv(test_dir / f"feature_engineered_item_{unique_id}_30d.csv")
    df_30d_engineered.write_parquet(test_dir / f"feature_engineered_item_{unique_id}_30d.parquet")

    # Future 14d raw
    future_raw.write_csv(test_dir / "raw_future_14d.csv")
    future_raw.write_csv(test_dir / f"raw_item_{unique_id}_future_14d.csv")

    # Future 14d engineered
    df_future_engineered.write_csv(test_dir / "feature_engineered_future_14d.csv")
    df_future_engineered.write_parquet(test_dir / "feature_engineered_future_14d.parquet")
    df_future_engineered.write_csv(test_dir / f"feature_engineered_item_{unique_id}_future_14d.csv")
    df_future_engineered.write_parquet(test_dir / f"feature_engineered_item_{unique_id}_future_14d.parquet")

    print(f"\nSaved test files to {test_dir}:")
    print(f"  • {test_dir / 'raw_future_14d.csv'}")
    print(f"  • {test_dir / 'feature_engineered_future_14d.csv'}")
    print(f"  • {test_dir / 'feature_engineered_future_14d.parquet'}")
    print(f"  • {test_dir / 'feature_engineered_30d.csv'}")
    print(f"  • {test_dir / 'feature_engineered_30d.parquet'}")

    return df_30d_engineered, df_future_engineered


if __name__ == "__main__":
    run_test()
