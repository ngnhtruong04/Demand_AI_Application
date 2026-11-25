"""test_load_pipeline.py — Test load_pipeline wrapper."""
from __future__ import annotations

import datetime
from pathlib import Path

import polars as pl
import pytest

from app.pipeline.feature_engineering import DEFAULT_CONFIG
from app.pipeline.load_pipeline import (
    fetch_raw_data,
    filter_inactive_series,
    load_and_engineer_splits,
    recompute_future_features,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_load_and_engineer_splits_item_10():
    """Verify load_and_engineer_splits loads 60d, engineers features, and cuts to 30d past + 14d future."""
    past_df, future_df = load_and_engineer_splits(
        unique_id="10",
        history_days=60,
        past_cut_days=30,
        horizon_days=14,
        config=DEFAULT_CONFIG,
        save=True,
        output_dir=BACKEND_ROOT / "data" / "output",
    )

    # 1. Row counts
    assert past_df.height == 30, f"Expected 30 past rows, got {past_df.height}"
    assert future_df.height == 14, f"Expected 14 future rows, got {future_df.height}"

    # 2. Date continuity
    max_past_date = past_df["date"].max()
    min_future_date = future_df["date"].min()
    max_future_date = future_df["date"].max()

    assert min_future_date == max_past_date + datetime.timedelta(days=1), "Future date must continue from past"
    assert max_future_date == max_past_date + datetime.timedelta(days=14)

    # 3. Features contract
    assert len(past_df.columns) == 142
    assert len(future_df.columns) == 142
    assert future_df["sales"].null_count() == 14, "Future sales must be NULL"

    # 4. Lags fully populated in past 30d thanks to 60d lookback
    assert past_df["sales_1"].null_count() == 0, "sales_1 should have 0 nulls in past 30d"
    assert past_df["sales_28"].null_count() == 0, "sales_28 should have 0 nulls in past 30d"

    # 5. Future lags behavior
    day1_row = future_df.filter(pl.col("date") == min_future_date)
    assert day1_row["sales_1"][0] is not None, "Day 1 future sales_1 should be filled from cutoff date"
    assert day1_row["sales_14"][0] is not None, "Day 1 future sales_14 should be filled from cutoff - 13"

    # 6. Verify total_orders is median of closest 4 days of the same weekday
    for row in future_df.select(["date", "total_orders"]).iter_rows(named=True):
        f_date, f_val = row["date"], row["total_orders"]
        expected = round(
            past_df.filter(pl.col("date").dt.weekday() == f_date.isoweekday())
            .sort("date")
            .tail(4)["total_orders"]
            .median()
        )
        assert f_val == expected, f"Expected {expected} for {f_date} (isoweekday {f_date.isoweekday()}), got {f_val}"

    print("test_load_and_engineer_splits_item_10: ALL ASSERTIONS PASSED!")


def test_recompute_future_features():
    """Verify recursive forecast feature recomputation when predictions are provided."""
    past_df, future_df = load_and_engineer_splits(
        unique_id="10",
        history_days=60,
        past_cut_days=30,
        horizon_days=14,
        save=False,
    )

    day1_date = future_df["date"].min()
    day2_date = day1_date + datetime.timedelta(days=1)

    # 1. Single-step update: DataFrame with unique_id x warehouse x date
    day1_pred = future_df.filter(pl.col("date") == day1_date).select(["unique_id", "warehouse", "date"]).with_columns(
        pl.lit(42.0).alias("sales")
    )
    updated_1 = recompute_future_features(future_df, past_df, predicted_sales=day1_pred)
    day2_row = updated_1.filter(pl.col("date") == day2_date)

    assert day2_row["sales_1"][0] == 42.0, "Day 2 sales_1 should equal Day 1 prediction"
    assert day2_row["sales_order_1"][0] is not None
    assert day2_row["sales_price_1"][0] is not None

    # 2. Batch update: DataFrame with unique_id x warehouse x date across all 14 days
    mock_14d = future_df.select(["unique_id", "warehouse", "date"]).with_columns(
        pl.Series("sales", [25.0 + i for i in range(future_df.height)])
    )
    updated_all = recompute_future_features(future_df, past_df, predicted_sales=mock_14d)

    assert updated_all["sales"].null_count() == 0, "All future sales should be filled"
    assert updated_all["sales_1"].null_count() == 0, "All sales_1 should be filled"
    assert updated_all["sales_order_1"].null_count() == 0, "All sales_order_1 should be filled"
    assert updated_all["sales_price_1"].null_count() == 0, "All sales_price_1 should be filled"

    print("test_recompute_future_features: ALL ASSERTIONS PASSED!")


def test_filter_inactive_series():
    """Verify that items with 10+ days without sales up to cutoff are filtered out."""
    cutoff = datetime.date(2024, 6, 2)
    start = cutoff - datetime.timedelta(days=29)
    dates = [start + datetime.timedelta(days=i) for i in range(30)]

    records = []
    # 1. Active item (has sales right up to 2024-06-01)
    for d in dates:
        records.append({
            "unique_id": 1,
            "warehouse": "Prague_1",
            "date": d,
            "sales": 10.0 if d == datetime.date(2024, 6, 1) else 0.0,
            "total_orders": 20.0,
            "sell_price_main": 50.0,
            "holiday": 0,
            "shops_closed": 0,
            "winter_school_holidays": 0,
            "school_holidays": 0,
            "type_0_discount": 0.0,
            "type_1_discount": 0.0,
            "type_2_discount": 0.0,
            "type_3_discount": 0.0,
            "type_4_discount": 0.0,
            "type_5_discount": 0.0,
            "type_6_discount": 0.0,
            "holiday_name": "",
            "name": f"item_{1}",
            "product_unique_id": 10,
            "L1_category_name_en": "Food",
            "L2_category_name_en": "Dairy",
            "L3_category_name_en": "Milk",
            "L4_category_name_en": "Fresh",
        })

    # 2. Inactive item (last sale on 2024-05-20, exactly 13 days before cutoff)
    for d in dates:
        records.append({
            "unique_id": 2,
            "warehouse": "Prague_1",
            "date": d,
            "sales": 15.0 if d == datetime.date(2024, 5, 20) else 0.0,
            "total_orders": 20.0,
            "sell_price_main": 50.0,
            "holiday": 0,
            "shops_closed": 0,
            "winter_school_holidays": 0,
            "school_holidays": 0,
            "type_0_discount": 0.0,
            "type_1_discount": 0.0,
            "type_2_discount": 0.0,
            "type_3_discount": 0.0,
            "type_4_discount": 0.0,
            "type_5_discount": 0.0,
            "type_6_discount": 0.0,
            "holiday_name": "",
            "name": f"item_{2}",
            "product_unique_id": 20,
            "L1_category_name_en": "Food",
            "L2_category_name_en": "Dairy",
            "L3_category_name_en": "Milk",
            "L4_category_name_en": "Fresh",
        })

    # 3. Inactive item (never sold, sales=0.0 on all days)
    for d in dates:
        records.append({
            "unique_id": 3,
            "warehouse": "Prague_1",
            "date": d,
            "sales": 0.0,
            "total_orders": 20.0,
            "sell_price_main": 50.0,
            "holiday": 0,
            "shops_closed": 0,
            "winter_school_holidays": 0,
            "school_holidays": 0,
            "type_0_discount": 0.0,
            "type_1_discount": 0.0,
            "type_2_discount": 0.0,
            "type_3_discount": 0.0,
            "type_4_discount": 0.0,
            "type_5_discount": 0.0,
            "type_6_discount": 0.0,
            "holiday_name": "",
            "name": f"item_{3}",
            "product_unique_id": 30,
            "L1_category_name_en": "Food",
            "L2_category_name_en": "Dairy",
            "L3_category_name_en": "Milk",
            "L4_category_name_en": "Fresh",
        })

    test_df = pl.DataFrame(records).with_columns(pl.col("date").cast(pl.Date))

    # Test standalone filter helper
    filtered_df, inactive_ids = filter_inactive_series(
        test_df,
        cutoff_date=cutoff,
        min_days_no_sale=10,
        sales_col="sales",
        date_col="date",
        id_col="unique_id",
    )
    assert set(filtered_df["unique_id"].unique().to_list()) == {1}, "Only item 1 should be retained"
    assert set(inactive_ids) == {2, 3}, "Items 2 and 3 should be flagged as inactive"

    # Test load_and_engineer_splits with use_inactive_items=False (default)
    past_f, fut_f = load_and_engineer_splits(
        source_data=test_df,
        use_inactive_items=False,
        history_days=30,
        past_cut_days=15,
        horizon_days=7,
        save=False,
    )
    assert past_f["unique_id"].n_unique() == 1
    assert past_f["unique_id"].unique().to_list() == [1]
    assert fut_f["unique_id"].unique().to_list() == [1]

    # Test load_and_engineer_splits with use_inactive_items=True (keep all)
    past_all, fut_all = load_and_engineer_splits(
        source_data=test_df,
        use_inactive_items=True,
        history_days=30,
        past_cut_days=15,
        horizon_days=7,
        save=False,
    )
    assert past_all["unique_id"].n_unique() == 3
    assert fut_all["unique_id"].n_unique() == 3
    print("test_filter_inactive_series: ALL ASSERTIONS PASSED!")


if __name__ == "__main__":
    test_filter_inactive_series()
