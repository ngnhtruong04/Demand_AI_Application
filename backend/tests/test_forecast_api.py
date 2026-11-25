import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_forecast_status_endpoint():
    response = client.get("/api/v1/forecast/forecast_status")
    assert response.status_code == 410
    assert "POST" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Requires live RDS connection")
def test_get_forecast_14d_endpoint():
    response = client.get("/api/v1/forecast/get_forecast_14d?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
    assert data["count"] > 0

    first_item = data["items"][0]
    assert "id" in first_item
    assert "forecast14d" in first_item
    assert "status" in first_item
    assert "onHandStock" in first_item
    assert "reorderPoint" in first_item
    assert "safetyStock" in first_item
    assert "daily_points" in first_item
    assert len(first_item["daily_points"]) == 14
    assert "grouped_drivers" in first_item
    assert len(first_item["grouped_drivers"]) > 0


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Requires live RDS connection")
def test_get_forecast_14d_top_k_with_others():
    """Verify Top-5 features plus aggregated Other Features row."""
    response = client.get("/api/v1/forecast/get_forecast_14d?unique_id=10&top_k=5")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["count"] == 1

    item = data["items"][0]
    features = item.get("all_features_shap", [])
    assert len(features) == 6, f"Expected Top-5 + 1 Other row (6 total), got {len(features)}"

    # 6th row must be aggregated Other Features
    other_row = features[-1]
    assert other_row["feature"] == "other_features"
    assert other_row["is_aggregated"] is True
    assert "Other Features" in other_row["label"]
    assert other_row["features_count"] > 0


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Requires live RDS connection")
def test_get_forecast_14d_full_features():
    """Verify top_k=0 returns 100% full unaggregated features."""
    response = client.get("/api/v1/forecast/get_forecast_14d?unique_id=10&top_k=0")
    assert response.status_code == 200
    data = response.json()
    item = data["items"][0]
    features = item.get("all_features_shap", [])
    assert len(features) > 10, f"Expected all features, got {len(features)}"
    assert not any(f.get("is_aggregated") for f in features), "Should have no aggregated row when top_k=0"


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Requires live RDS connection")
def test_forecast_runs_endpoint():
    """Verify GET /api/v1/forecast/runs lists recorded runs."""
    response = client.get("/api/v1/forecast/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "runs" in data
    assert len(data["runs"]) > 0
    latest = data["runs"][0]
    assert "run_id" in latest
    assert "model_version" in latest
    assert "total_items" in latest
    assert latest["is_latest"] is True


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Requires live RDS connection")
def test_prune_runs_endpoint():
    """Verify POST /api/v1/forecast/prune_runs with max_runs_to_keep=10."""
    response = client.post("/api/v1/forecast/prune_runs?max_runs_to_keep=10")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "pruned_count" in data
    assert data["max_runs_retained"] == 10


def test_cached_pages_skip_database(monkeypatch):
    from app.api.routes import forecast

    payload = {"items": [{"id": "501"}], "total_items": 501}
    monkeypatch.setattr(forecast, "_get_cached_forecast_payload", lambda **kwargs: payload)

    def unexpected_query(*args):
        pytest.fail("A cached page must not query the database")

    monkeypatch.setattr(forecast, "_query_db_worker", unexpected_query)
    response = client.get("/api/v1/forecast/get_forecast_14d?source=cache&offset=500")
    assert response.status_code == 200
    assert response.json() == payload


def test_database_pages_forward_run_id(monkeypatch):
    from app.api.routes import forecast
    from uuid import UUID

    run_id = "00000000-0000-0000-0000-000000000001"

    def query(uid, limit, offset, top_k, requested_run):
        assert requested_run == UUID(run_id)
        assert offset == 500
        return {"run_id": run_id, "items": [{"id": "501"}]}

    monkeypatch.setattr(forecast, "_query_db_worker", query)
    response = client.get(f"/api/v1/forecast/get_forecast_14d?source=database&offset=500&run_id={run_id}")
    assert response.status_code == 200
    assert response.json()["run_id"] == run_id


@pytest.mark.parametrize("failure, status", [(TimeoutError(), 504), (RuntimeError("unavailable"), 503), (None, 404)])
def test_pinned_database_failure_does_not_fallback(monkeypatch, failure, status):
    from app.api.routes import forecast

    def query(*args):
        if failure:
            raise failure
        return None

    def unexpected_cache(**kwargs):
        pytest.fail("A pinned database page must not switch to cache")

    monkeypatch.setattr(forecast, "_query_db_worker", query)
    monkeypatch.setattr(forecast, "_get_cached_forecast_payload", unexpected_cache)
    response = client.get("/api/v1/forecast/get_forecast_14d?source=database")
    assert response.status_code == status
    assert response.json()["detail"]


def test_expire_session_prunes_db(monkeypatch):
    from app.api.routes import forecast
    called_with = []

    def mock_delete(db, session_key):
        called_with.append(session_key)
        return 1

    monkeypatch.setattr("app.api.routes.forecast.delete_forecast_session", mock_delete)
    monkeypatch.setattr("app.services.forecast_artifacts.prune_old_sessions", lambda keep_n=4: ["run-1"])

    res = client.post("/api/v1/forecast/sessions/expire", json={"session_id": "test-sess-123"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["expired_session_id"] == "test-sess-123"
    assert data["db_pruned_runs"] == 1
    assert "removed_exports" in data
    assert called_with == ["test-sess-123"]


def test_prune_old_exports_fifo(tmp_path, monkeypatch):
    import time
    from app.services import forecast_artifacts

    monkeypatch.setattr(forecast_artifacts, "EXPORTS_DIR", tmp_path)

    # Create 6 files with staggered mtimes
    created_files = []
    for i in range(6):
        f = tmp_path / f"export_{i}.pdf"
        f.write_text(f"content {i}")
        # Set distinct mtimes
        mtime = time.time() - (100 - i * 10)  # export_0 is oldest, export_5 is newest
        import os
        os.utime(f, (mtime, mtime))
        created_files.append(f)

    # Prune keeping 4 latest (FIFO: export_0 and export_1 must be removed)
    removed = forecast_artifacts.prune_old_exports(keep_n=4)
    assert len(removed) == 2
    assert "export_0.pdf" in removed
    assert "export_1.pdf" in removed

    remaining = sorted([f.name for f in tmp_path.iterdir()])
    assert remaining == ["export_2.pdf", "export_3.pdf", "export_4.pdf", "export_5.pdf"]


def test_chat_cleanup_endpoint(monkeypatch):
    from app.services import forecast_artifacts
    monkeypatch.setattr(forecast_artifacts, "prune_old_exports", lambda keep_n=5: ["old_file.pdf"])

    res = client.post("/api/v1/chat/cleanup")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["removed_exports"] == ["old_file.pdf"]
    assert data["kept_limit"] == 5



def test_extract_model_parquet_data_ceiling(tmp_path):
    """Verify that extract_model_parquet_data ceils all predictions to whole integers."""
    import datetime
    import polars as pl
    from app.services.forecast_persistence import extract_model_parquet_data

    dummy_df = pl.DataFrame({
        "unique_id": ["SKU_TEST", "SKU_TEST"],
        "horizon": [1, 2],
        "date": [datetime.date(2024, 5, 20), datetime.date(2024, 5, 21)],
        "predicted_sales": [59.01, 10.4],
    })
    dummy_parquet = tmp_path / "preds.parquet"
    dummy_df.write_parquet(dummy_parquet)

    data = extract_model_parquet_data(
        preds_path=dummy_parquet,
        shap_path=tmp_path / "shap.parquet",
        include_shap=False,
    )
    pred_totals = data["pred_totals"]
    daily_pts = data["daily_predictions"]
    # 59.01 -> ceil -> 60.0, 10.4 -> ceil -> 11.0, Total = 71.0
    assert pred_totals["SKU_TEST"] == 71.0
    pts = daily_pts["SKU_TEST"]
    assert pts[0]["predicted"] == 60.0
    assert pts[1]["predicted"] == 11.0


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Requires live RDS connection")
def test_forecast_values_are_integers():
    """Verify that all 14-day forecasts and daily predictions in RDS are whole integers (rounded UP/ceil)."""
    res = client.get("/api/v1/forecast/get_forecast_14d?limit=30")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["items"]) > 0

    for item in data["items"]:
        f14 = item["forecast14d"]
        assert isinstance(f14, (int, float))
        assert float(f14).is_integer(), f"Item {item['id']} forecast14d is not integer: {f14}"

        for pt in item.get("daily_points", []):
            pred = pt["predicted"]
            assert isinstance(pred, (int, float))
            assert float(pred).is_integer(), f"Item {item['id']} day {pt.get('day')} predicted is not integer: {pred}"
