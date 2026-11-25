"""Tests for OpenAPI & Swagger Documentation parity, schemas, and REST endpoints."""
from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest

from app.main import app
from tests.test_pdf_report import MOCK_INVENTORY_ITEMS

client = TestClient(app)


def test_openapi_schema_metadata_and_tags():
    """Verify OpenAPI v2.0.0 metadata, tags, and zero duplicate operation IDs."""
    spec = app.openapi()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["version"] == "2.0.0"
    assert "DemandAI Enterprise" in spec["info"]["title"]
    assert "Two-Way Price Decision" in spec["info"]["description"]

    # Check tags metadata
    tag_names = [t["name"] for t in spec.get("tags", [])]
    expected_tags = {"forecast", "chat", "wiki", "pipeline", "feature-engineering", "health", "system"}
    assert expected_tags.issubset(set(tag_names))

    # Verify Operation IDs are unique and clean (no duplicates)
    op_ids = []
    for path, methods in spec["paths"].items():
        for method, details in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                op_id = details.get("operationId")
                assert op_id is not None, f"Missing operationId for {method.upper()} {path}"
                op_ids.append(op_id)

    assert len(op_ids) == len(set(op_ids)), f"Duplicate operation IDs detected: {[x for x in op_ids if op_ids.count(x) > 1]}"


def test_simulate_rest_endpoint():
    """Verify POST /api/v1/forecast/simulate works via REST API."""
    payload = {
        "sku_code": "SKU-4471",
        "price_change_percent": 15.0,
        "warehouse": "Prague_1",
    }
    res = client.post("/api/v1/forecast/simulate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["action_type"] == "price_increase"
    assert data["price_change_percent"] == 15.0
    assert "markdown_report" in data
    assert "What-If Demand & Price Simulation" in data["markdown_report"]


def test_export_pdf_rest_endpoint():
    """Verify POST /api/v1/forecast/export/pdf generates PDF and returns download link."""
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        payload = {
            "focus_area": "overview",
            "warehouse": "Prague_1",
        }
        res = client.post("/api/v1/forecast/export/pdf", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "download_url" in data
        assert data["download_url"].startswith("/api/v1/forecast/export/download/")


def test_export_replenishment_rest_endpoint():
    """Verify POST /api/v1/forecast/export/replenishment generates CSV and returns download link."""
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        payload = {
            "warehouse": "Prague_1",
        }
        res = client.post("/api/v1/forecast/export/replenishment", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "download_url" in data
        assert data["download_url"].startswith("/api/v1/forecast/export/download/")


def test_wiki_rest_endpoints():
    """Verify GET /api/v1/wiki and sub-endpoints respond with valid schemas."""
    res_all = client.get("/api/v1/wiki")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert "metrics" in data_all
    assert "status" in data_all
    assert "synced" in data_all

    res_metrics = client.get("/api/v1/wiki/metrics")
    assert res_metrics.status_code == 200
    metrics_data = res_metrics.json()
    assert "rop" in str(metrics_data).lower()

    res_status = client.get("/api/v1/wiki/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "deadstock" in str(status_data).lower()


def test_chat_models_rest_endpoint():
    """Verify GET /api/v1/chat/models returns model registry."""
    res = client.get("/api/v1/chat/models")
    assert res.status_code == 200
    data = res.json()
    assert "default" in data
    assert "models" in data
    assert "boot_id" in data
