"""test_pipeline_single_item.py — Test feature engineering pipeline on actual RDS data.

Pulls actual joined records (sales_train + inventory + calendar) from AWS RDS PostgreSQL:
- Supports 1 single unique_id or all unique_ids
- Window of exactly N days (default 30d, no more, no less)
- 'availability' is strictly excluded from data
- Runs feature engineering pipeline and saves outputs to backend/data/test
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path
from typing import Any

import polars as pl
from psycopg import sql

# Ensure backend root is on sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.feature_engineering import _build_inference_splits
from app.pipeline.feature_engineering import (
    DEFAULT_CONFIG,
    DataValidationError,
    DatasetSplits,
    FeatureEngineeringArtifacts,
    RohlikFeatureEngineeringPipeline,
    run_feature_engineering,
)
from scripts.ingestion.common import get_api_connection

TEST_DATA_DIR = BACKEND_ROOT / "data" / "test"

# NOTE: 'availability' is strictly removed from the SELECT columns
_BASE_MERGE_SQL = """
SELECT
    s.unique_id,
    s.date,
    s.warehouse,
    s.total_orders,
    s.sales,
    s.sell_price_main,
    s.type_0_discount,
    s.type_1_discount,
    s.type_2_discount,
    s.type_3_discount,
    s.type_4_discount,
    s.type_5_discount,
    s.type_6_discount,
    i.name,
    i.product_unique_id,
    i."L1_category_name_en",
    i."L2_category_name_en",
    i."L3_category_name_en",
    i."L4_category_name_en",
    c.holiday_name,
    c.holiday,
    c.shops_closed,
    c.winter_school_holidays,
    c.school_holidays
FROM raw.sales_train s
LEFT JOIN raw.inventory  i ON s.unique_id = i.unique_id  AND s.warehouse = i.warehouse
LEFT JOIN raw.calendar   c ON s.date      = c.date        AND s.warehouse = c.warehouse
WHERE s.date >= (
    SELECT MAX(date) - (%(days)s - 1) * INTERVAL '1 day'
    FROM   raw.sales_train
)
{extra_filter}
ORDER BY s.unique_id, s.warehouse, s.date
"""


def fetch_actual_data(
    unique_id: str | None = "10",
    days: int = 30,
) -> pl.DataFrame:
    """Pull actual data from RDS for exactly `days` days.

    Guarantees a continuous unbroken calendar grid of exactly `days` days ending at
    the global dataset latest date (2024-06-02). Missing days are filled with sales=0.0.

    Args:
        unique_id: Target unique_id (e.g. '10'), or None/'all' to pull all unique IDs.
        days: Exact number of days to pull (default: 30, no more, no less).
    """
    params: dict[str, Any] = {"days": days}
    is_single = unique_id is not None and str(unique_id).lower() != "all"
    if is_single:
        params["unique_id"] = str(unique_id)
        target_desc = f"unique_id='{unique_id}'"
    else:
        target_desc = "ALL unique_ids"

    print(f"Connecting to RDS (read-only)...")
    print(f"Querying exactly {days} days for {target_desc} ('availability' excluded)...")
    with get_api_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM raw.sales_train;")
            cutoff_date = cur.fetchone()[0]
            start_date = cutoff_date - datetime.timedelta(days=days - 1)

            query = _BASE_MERGE_SQL.format(
                extra_filter="AND s.unique_id = %(unique_id)s" if is_single else ""
            )
            cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            # Query calendar table for exact window to fill gaps
            cal_sql = """
            SELECT date, warehouse, holiday_name, holiday, shops_closed, winter_school_holidays, school_holidays
            FROM raw.calendar
            WHERE date >= %s AND date <= %s;
            """
            cur.execute(cal_sql, (start_date, cutoff_date))
            c_cols = [desc[0] for desc in cur.description]
            c_rows = cur.fetchall()
            cal_df = (
                pl.DataFrame({c: [r[i] for r in c_rows] for i, c in enumerate(c_cols)})
                .with_columns(pl.col("date").cast(pl.Date))
                if c_rows
                else pl.DataFrame({c: [] for c in c_cols})
            )

    print(f"Retrieved {len(rows)} raw rows from RDS.")
    if not rows:
        return pl.DataFrame({col: [] for col in cols})

    col_data: dict[str, list[Any]] = {col: [] for col in cols}
    for row in rows:
        for col, val in zip(cols, row):
            col_data[col].append(val)

    df = pl.DataFrame(col_data).with_columns(pl.col("date").cast(pl.Date))
    assert "availability" not in df.columns, "'availability' must NOT be in the retrieved columns"

    # Build continuous unbroken calendar grid
    all_dates = pl.date_range(start_date, cutoff_date, "1d", eager=True).alias("date")
    series_keys = df.select(["unique_id", "warehouse"]).unique()
    grid = series_keys.join(pl.DataFrame({"date": all_dates}), how="cross")

    merged = grid.join(df, on=["unique_id", "warehouse", "date"], how="left")
    if cal_df.height > 0:
        # Update calendar features for zero-filled gap days
        for cal_c in ["holiday_name", "holiday", "shops_closed", "winter_school_holidays", "school_holidays"]:
            if cal_c in merged.columns and cal_c in cal_df.columns:
                merged = merged.drop(cal_c)
        merged = merged.join(cal_df, on=["warehouse", "date"], how="left")

    merged = merged.with_columns([
        pl.col("sales").fill_null(0.0),
        pl.col("type_0_discount").fill_null(0.0),
        pl.col("type_1_discount").fill_null(0.0),
        pl.col("type_2_discount").fill_null(0.0),
        pl.col("type_3_discount").fill_null(0.0),
        pl.col("type_4_discount").fill_null(0.0),
        pl.col("type_5_discount").fill_null(0.0),
        pl.col("type_6_discount").fill_null(0.0),
        pl.col("sell_price_main").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("total_orders").forward_fill().backward_fill().fill_null(10000.0).over("warehouse"),
        pl.col("name").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("product_unique_id").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("L1_category_name_en").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("L2_category_name_en").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("L3_category_name_en").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("L4_category_name_en").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("holiday").fill_null(0),
        pl.col("shops_closed").fill_null(0),
        pl.col("winter_school_holidays").fill_null(0),
        pl.col("school_holidays").fill_null(0),
        pl.col("holiday_name").fill_null(""),
    ]).sort(["unique_id", "warehouse", "date"])

    return merged


def fetch_single_item_data(unique_id: str = "10", window_days: int = 30) -> pl.DataFrame:
    """Convenience alias for single item data fetching for tests."""
    return fetch_actual_data(unique_id=unique_id, days=window_days)


import os
import pytest

run_integration = os.environ.get("RUN_RDS_INTEGRATION_TESTS") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not run_integration,
    reason="RDS integration tests require live DB via RUN_RDS_INTEGRATION_TESTS=1",
)
def test_pipeline_for_unique_id(
    unique_id: str = "10",
    inference_days: int = 30,
    save_dir: Path | str | None = TEST_DATA_DIR,
) -> FeatureEngineeringArtifacts:
    """Run actual data test for unique_id (or 'all') for exactly inference_days (default 30d)."""
    is_all = unique_id is None or str(unique_id).lower() == "all"
    target_label = "ALL unique_ids" if is_all else f"unique_id={unique_id}"

    print("=" * 70)
    print(f"Rohlik Feature Engineering Pipeline — Actual Data Test ({target_label})")
    print(f"Window duration:    {inference_days} days (exact, no more - no less)")
    print(f"'availability':     EXCLUDED")
    print("=" * 70)

    # 1. Fetch data from DB
    t0 = time.perf_counter()
    df = fetch_actual_data(unique_id=unique_id, days=inference_days)
    if df.height == 0:
        raise ValueError(f"No records found for {target_label}.")

    min_date = df["date"].min()
    max_date = df["date"].max()
    actual_days = (max_date - min_date).days + 1
    warehouses = df["warehouse"].unique().to_list()
    num_uids = df["unique_id"].n_unique()

    print(f"Data summary:")
    print(f"  • Total rows:       {df.height}")
    print(f"  • Date span:        {min_date} to {max_date} ({actual_days} days)")
    print(f"  • Distinct items:   {num_uids}")
    print(f"  • Warehouses:       {warehouses}")
    print(f"  • 'availability':   {'PRESENT (ERROR)' if 'availability' in df.columns else 'REMOVED (OK)'}")
    print(f"  • Elapsed fetch:    {round(time.perf_counter() - t0, 3)}s")
    print("-" * 70)

    # Validate that we pulled exactly inference_days (no more, no less)
    assert actual_days == inference_days, f"Expected exactly {inference_days} days span, got {actual_days}"

    # 2. Build inference splits (train / val / test)
    # Since only 30d is pulled, train, val, and test represent the 30d window
    splits = _build_inference_splits(df, inference_days)
    print(f"Inference splits:")
    print(f"  • Train rows:       {splits.train.height} (covers {splits.train['date'].min()} → {splits.train['date'].max()})")
    print(f"  • Test rows:        {splits.test.height} (covers {splits.test['date'].min()} → {splits.test['date'].max()})")
    print("-" * 70)

    # 3. Track events via emit
    events: list[tuple[str, str, Any]] = []

    def emit(step: str, status: str, detail: Any) -> None:
        events.append((step, status, detail))
        if status == "running":
            print(f"  [RUNNING] Step: {step:<25s} | {detail}")
        elif status == "done":
            print(f"  [  OK   ] Step: {step:<25s} | {detail}")
        else:
            print(f"  [FAILED ] Step: {step:<25s} | {detail}")

    # 4. Execute pipeline
    print("Executing pipeline steps:")
    t_pipe = time.perf_counter()
    artifacts = run_feature_engineering(
        splits=splits,
        config=DEFAULT_CONFIG,
        emit=emit,
        save=False,
    )
    pipe_duration = round(time.perf_counter() - t_pipe, 3)
    print("-" * 70)
    print(f"Pipeline finished in {pipe_duration}s!")
    print(f"Engineered features summary:")
    print(f"  • Total feature count:       {len(artifacts.feature_columns)}")
    print(f"  • Categorical count:         {len(artifacts.categorical_columns)}")
    print(f"  • Feature groups:            {len(artifacts.feature_groups)}")
    for grp, cols in artifacts.feature_groups.items():
        print(f"      - {grp}: {len(cols)} columns")
    print(f"  • Warnings:                  {artifacts.warnings}")
    print(f"  • Test split shape:          {artifacts.splits.test.shape}")
    print(f"  • Test split date range:     {artifacts.splits.test['date'].min()} → {artifacts.splits.test['date'].max()}")

    # 5. Verification checks on output
    test_df = artifacts.splits.test
    assert test_df.height == df.height, f"Expected {df.height} test rows, got {test_df.height}"
    for col in artifacts.feature_columns:
        assert col in test_df.columns, f"Feature column {col} missing in test split"

    assert "availability" not in test_df.columns, "'availability' must NOT be in output test features"

    # Verify key feature columns exist
    sample_features = [
        "year", "month", "weekday", "day", "sin_dayofyear", "cos_dayofyear",
        "name_0", "max_discount", "discounted_price",
        "sales_1", "sales_7", "sales_14", "sales_28",
        "sales_order_1", "sales_price_1",
        "type_0_discount_1", "type_0_discount_7",
    ]
    for sf in sample_features:
        assert sf in test_df.columns, f"Expected sample feature {sf} missing in output"

    print("\nVerification checks: ALL PASSED!")
    preview_cols = ["unique_id", "date", "warehouse", "sales", "sales_1", "sales_7", "max_discount", "discounted_price"]
    print("Sample output:")
    print(test_df.select([c for c in preview_cols if c in test_df.columns]).head(5))

    # 6. Save test data to disk if requested
    if save_dir:
        out_dir = Path(save_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        prefix = "all_items" if is_all else f"item_{unique_id}"
        raw_test_path = out_dir / f"raw_{prefix}_{inference_days}d.csv"
        csv_path = out_dir / f"feature_engineered_{prefix}_{inference_days}d.csv"
        parquet_path = out_dir / f"feature_engineered_{prefix}_{inference_days}d.parquet"

        # Also save standard names for default 30d single item tests
        default_csv_path = out_dir / "feature_engineered_30d.csv"
        default_parquet_path = out_dir / "feature_engineered_30d.parquet"
        default_raw_path = out_dir / "raw_test_30d.csv"

        splits.test.write_csv(raw_test_path)
        test_df.write_csv(csv_path)
        test_df.write_parquet(parquet_path)

        if not is_all and inference_days == 30:
            splits.test.write_csv(default_raw_path)
            test_df.write_csv(default_csv_path)
            test_df.write_parquet(default_parquet_path)

        print("-" * 70)
        print(f"Saved test data to directory: {out_dir}")
        print(f"  • Raw test CSV:                {raw_test_path.name} ({splits.test.height} rows, {splits.test.width} cols)")
        print(f"  • Feature engineered CSV:      {csv_path.name} ({test_df.height} rows, {test_df.width} cols, {round(csv_path.stat().st_size / 1024, 2)} KB)")
        print(f"  • Feature engineered Parquet:  {parquet_path.name} ({round(parquet_path.stat().st_size / 1024, 2)} KB)")
    print("=" * 70)
    return artifacts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test pipeline on actual RDS data for single unique_id or all")
    parser.add_argument(
        "--unique-id",
        type=str,
        default="10",
        help="Target unique_id (default: '10'). Use 'all' to pull all unique IDs.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to pull (default: 30, no more, no less).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(TEST_DATA_DIR),
        help="Directory to save test datasets (default: backend/data/test).",
    )
    args = parser.parse_args()

    test_pipeline_for_unique_id(
        unique_id=args.unique_id,
        inference_days=args.days,
        save_dir=args.output_dir,
    )
