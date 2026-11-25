"""test_recursive_ensemble.py — Unit test for RecursiveEnsemblePredictor using real data."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import polars as pl

from app.pipeline.recursive_ensemble import RecursiveEnsemblePredictor

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REAL_PAST_CSV = BACKEND_ROOT / "data" / "output" / "feature_engineered_item_10_30d_past.csv"


def test_recursive_ensemble_prediction_real_data():
    assert REAL_PAST_CSV.exists(), f"Real validation file missing: {REAL_PAST_CSV}"

    full_df = pl.read_csv(REAL_PAST_CSV).with_columns(
        pl.col("date").str.to_date(),
        pl.col("sales").cast(pl.Float32),
    )
    full_df = full_df.with_columns(
        [pl.col(c).cast(pl.Float32) for c in full_df.columns if full_df[c].dtype == pl.Float64]
    )

    cutoff_date = full_df["date"].sort().unique().to_list()[15]
    df_past = full_df.filter(pl.col("date") <= cutoff_date)
    actual_future = full_df.filter(pl.col("date") > cutoff_date).sort("date")
    df_future = actual_future.with_columns(pl.lit(None, dtype=pl.Float32).alias("sales"))

    predictor = RecursiveEnsemblePredictor()
    preds = predictor.predict(df_past, df_future)

    # Verifications
    assert preds.height == 14
    assert preds["predicted_sales"].null_count() == 0
    assert (preds["predicted_sales"] >= 0).all()
    assert preds["predicted_sales"].dtype == pl.Float32 or preds["predicted_sales"].dtype == pl.Float64

    # Check frontend contract generation
    payload = predictor.to_frontend_contract(preds)
    assert payload["status"] == "success"
    assert payload["forecast_horizon_days"] == 14
    assert len(payload["items"]) == 1
    assert len(payload["items"][0]["daily_points"]) == 14
    assert payload["items"][0]["forecast14d"] > 0


def test_calculate_metrics_with_test_weights():
    """Verify calculate_metrics automatically uses weights from dataframe or loads from DB for WMAE."""
    final_val = pl.read_parquet(BACKEND_ROOT / "models" / "final_predictions.parquet")
    metrics = RecursiveEnsemblePredictor.calculate_metrics(final_val)

    assert "wmae" in metrics
    assert "wape" in metrics
    assert "mae" in metrics
    assert metrics["wmae"] < 17.5
    assert metrics["wape"] < 0.20


def test_load_test_weights_directly_from_db():
    """Verify weights load permanently and directly from RDS raw.test_weights table."""
    import os
    if os.environ.get("RUN_RDS_INTEGRATION_TESTS") != "1":
        import pytest
        pytest.skip("Requires live RDS via RUN_RDS_INTEGRATION_TESTS=1")

    weights_df = RecursiveEnsemblePredictor.load_test_weights()
    assert weights_df is not None
    assert len(weights_df) == 5390
    assert "unique_id" in weights_df.columns
    assert "weight" in weights_df.columns
    assert weights_df[weights_df["unique_id"] == "10"]["weight"].iloc[0] > 2.0


def test_recursive_ensemble_with_treeshap_explainability():
    """Verify recursive prediction + TreeSHAP explainability produces top 5 pos/neg drivers adhering to schema."""
    full_df = pl.read_csv(REAL_PAST_CSV).with_columns(
        pl.col("date").str.to_date(),
        pl.col("sales").cast(pl.Float32),
    )
    cutoff_date = full_df["date"].sort().unique().to_list()[15]
    df_past = full_df.filter(pl.col("date") <= cutoff_date)
    actual_future = full_df.filter(pl.col("date") > cutoff_date).sort("date")
    df_future = actual_future.with_columns(pl.lit(None, dtype=pl.Float32).alias("sales"))

    predictor = RecursiveEnsemblePredictor()
    preds_df, explanations = predictor.predict_and_explain(df_past, df_future, mode="auto")

    assert preds_df.height == 14
    assert len(explanations) == 14

    for exp in explanations:
        assert "unique_id" in exp
        assert "warehouse" in exp
        assert "date" in exp
        assert "horizon" in exp
        assert "forecast" in exp
        assert "top_positive_features" in exp
        assert "top_negative_features" in exp
        assert exp["mode"] in ("offline", "online")

        # Verify top 5 positive and negative feature drivers
        assert len(exp["top_positive_features"]) == 5
        assert len(exp["top_negative_features"]) == 5

        for feat in exp["top_positive_features"]:
            assert feat["direction"] == "increase"
            assert "feature" in feat
            assert "feature_label" in feat
            assert "shap_value" in feat
            assert feat["shap_value"] > 0

        for feat in exp["top_negative_features"]:
            assert feat["direction"] == "decrease"
            assert "feature" in feat
            assert "feature_label" in feat
            assert "shap_value" in feat
            assert feat["shap_value"] < 0

