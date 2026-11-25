"""test_pipeline_actual_data.py — Integration test for feature engineering pipeline with actual RDS data.

Verifies:
1. End-to-end extraction from AWS RDS PostgreSQL for 1 unique_id over exactly 30 days
   (no more, no less), with 'availability' strictly removed.
2. Capability to configure N days (e.g. n=30d) and pull across all unique_ids or 1 single unique_id.
3. Feature engineering execution and saving outputs to backend/data/test.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.api.routes.feature_engineering import _build_inference_splits
from app.pipeline.feature_engineering import (
    DEFAULT_CONFIG,
    DatasetSplits,
    run_feature_engineering,
)
from scripts.ingestion.common import get_api_connection
from tests.test_pipeline_single_item import fetch_actual_data

run_integration = os.environ.get("RUN_RDS_INTEGRATION_TESTS") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not run_integration,
    reason="RDS integration tests are opt-in via RUN_RDS_INTEGRATION_TESTS=1",
)
def test_pipeline_runs_on_actual_rds_data_30d_single_item() -> None:
    unique_id = "10"
    n_days = 30  # ONLY PULL 30d: no more, no less

    # 1. Fetch exactly 30 days from RDS for 1 single unique_id
    df = fetch_actual_data(unique_id=unique_id, days=n_days)

    # 2. Strict validation: 'availability' must be removed, exactly 30 days
    assert "availability" not in df.columns, "'availability' must be strictly removed from data"
    assert df.height == n_days, f"Expected exactly {n_days} rows for single warehouse, got {df.height}"

    min_date = df["date"].min()
    max_date = df["date"].max()
    actual_span = (max_date - min_date).days + 1
    assert actual_span == n_days, f"Expected exactly {n_days} days date span, got {actual_span} ({min_date} to {max_date})"

    # 3. Build inference splits
    splits = _build_inference_splits(df, n_days)
    assert splits.test.height == n_days
    assert "availability" not in splits.train.columns

    # 4. Run feature engineering pipeline
    events = []
    def emit(step: str, status: str, detail: Any) -> None:
        events.append((step, status, detail))

    artifacts = run_feature_engineering(
        splits=splits,
        config=DEFAULT_CONFIG,
        emit=emit,
        save=False,
    )

    # 5. Assert outputs
    assert len(artifacts.feature_columns) == 139
    assert len(artifacts.categorical_columns) == 8
    assert artifacts.splits.test.height == n_days
    assert "sales_1" in artifacts.splits.test.columns
    assert "sales_28" in artifacts.splits.test.columns
    assert "max_discount" in artifacts.splits.test.columns
    assert "sin_dayofyear" in artifacts.splits.test.columns
    assert "availability" not in artifacts.splits.test.columns

    # 6. Save test data to backend/data/test
    backend_root = Path(__file__).resolve().parents[1]
    test_dir = backend_root / "data" / "test"
    test_dir.mkdir(parents=True, exist_ok=True)

    raw_test_file = test_dir / "raw_test_30d.csv"
    engineered_test_file = test_dir / "feature_engineered_30d.csv"
    engineered_parquet_file = test_dir / "feature_engineered_30d.parquet"

    splits.test.write_csv(raw_test_file)
    artifacts.splits.test.write_csv(engineered_test_file)
    artifacts.splits.test.write_parquet(engineered_parquet_file)

    assert raw_test_file.is_file() and raw_test_file.stat().st_size > 0
    assert engineered_test_file.is_file() and engineered_test_file.stat().st_size > 0
    assert engineered_parquet_file.is_file() and engineered_parquet_file.stat().st_size > 0


@pytest.mark.integration
@pytest.mark.skipif(
    not run_integration,
    reason="RDS integration tests are opt-in via RUN_RDS_INTEGRATION_TESTS=1",
)
def test_fetch_data_options_all_items_and_custom_n_days() -> None:
    # Test custom n (e.g. n=5 days) for 1 unique_id
    n_days_custom = 5
    df_single = fetch_actual_data(unique_id="10", days=n_days_custom)
    assert "availability" not in df_single.columns
    assert df_single.height == n_days_custom
    span_custom = (df_single["date"].max() - df_single["date"].min()).days + 1
    assert span_custom == n_days_custom

    # Test pulling all unique_ids for n=2 days (small sample to keep test fast)
    df_all_small = fetch_actual_data(unique_id="all", days=2)
    assert "availability" not in df_all_small.columns
    assert df_all_small.height > 100
    assert df_all_small["unique_id"].n_unique() > 1
    span_all = (df_all_small["date"].max() - df_all_small["date"].min()).days + 1
    assert span_all == 2
