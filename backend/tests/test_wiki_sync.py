import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.wiki.sync import format_wiki_prompt_context, get_wiki_data, sync_wiki_to_frontend

client = TestClient(app)


def test_wiki_data_loading():
    data = get_wiki_data()
    assert "metrics" in data
    assert "status" in data
    assert "forecast" in data["metrics"]["metrics"]
    assert "Deadstock" in data["status"]["statuses"]
    assert "Critical" in data["status"]["statuses"]


def test_wiki_sync_to_frontend():
    # Sync runs without errors and confirms frontend files exist and match
    synced = sync_wiki_to_frontend()
    # It returns True if files were updated or False if already in sync
    assert isinstance(synced, bool)


def test_wiki_prompt_context():
    context_vi = format_wiki_prompt_context("vi")
    assert "DEMANDAI WIKI" in context_vi
    assert "14-Day Forecast" in context_vi
    assert "Reorder Point (ROP)" in context_vi
    assert "Deadstock" in context_vi

    context_en = format_wiki_prompt_context("en")
    assert "DEMANDAI WIKI" in context_en
    assert "Formula" in context_en


def test_api_wiki_endpoints():
    # 1. Get all wiki
    res_all = client.get("/api/v1/wiki")
    assert res_all.status_code == 200
    body_all = res_all.json()
    assert "metrics" in body_all
    assert "status" in body_all

    # 2. Get metrics
    res_metrics = client.get("/api/v1/wiki/metrics")
    assert res_metrics.status_code == 200
    assert "metrics" in res_metrics.json()

    # 3. Get status
    res_status = client.get("/api/v1/wiki/status")
    assert res_status.status_code == 200
    assert "statuses" in res_status.json()

    # 4. Manual sync trigger
    res_sync = client.post("/api/v1/wiki/sync")
    assert res_sync.status_code == 200
    assert res_sync.json()["status"] == "success"


def test_query_inventory_wiki_tool():
    from app.agent.tools import query_inventory_wiki

    # ROP lookup
    res_rop = query_inventory_wiki.invoke({"term": "rop"})
    assert "Reorder Point (ROP)" in res_rop
    assert "Calculation" in res_rop

    # Days of supply lookup
    res_dos = query_inventory_wiki.invoke({"term": "days of supply"})
    assert "Days of Supply" in res_dos

    # Critical status lookup
    res_crit = query_inventory_wiki.invoke({"term": "critical"})
    assert "STATUS 'Critical'" in res_crit
    assert "Condition" in res_crit

    # TreeSHAP lookup
    res_shap = query_inventory_wiki.invoke({"term": "treeshap"})
    assert "Tree SHAP" in res_shap or "Daily Attribution" in res_shap

    # Vietnamese alias lookup
    res_vn = query_inventory_wiki.invoke({"term": "số ngày tồn kho"})
    assert "Days of Supply" in res_vn
