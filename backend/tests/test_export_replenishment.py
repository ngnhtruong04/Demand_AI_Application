from __future__ import annotations

import csv
import io
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.agent.tools import export_replenishment_csv
from app.main import app

client = TestClient(app)

MOCK_ITEMS = [
    {
        "id": "101",
        "sku": "SKU-101",
        "name": "Fresh Milk 1L",
        "category": "Dairy",
        "warehouse": "Warehouse-14",
        "onHandStock": 10,
        "forecast14d": 50.0,
        "safetyStock": 20.0,
        "leadTimeDays": 2,
        "reorderPoint": 25.0,
        "status": "Critical",
    },
    {
        "id": "102",
        "sku": "SKU-102",
        "name": "Cheddar Cheese 200g",
        "category": "Dairy",
        "warehouse": "Warehouse-14",
        "onHandStock": 100,
        "forecast14d": 40.0,
        "safetyStock": 15.0,
        "leadTimeDays": 3,
        "reorderPoint": 20.0,
        "status": "Normal",
    },
    {
        "id": "201",
        "sku": "SKU-201",
        "name": "Organic Apples 1kg",
        "category": "Produce",
        "warehouse": "Warehouse-02",
        "onHandStock": 5,
        "forecast14d": 30.0,
        "safetyStock": 10.0,
        "leadTimeDays": 2,
        "reorderPoint": 15.0,
        "status": "Critical",
    },
]


def test_export_replenishment_csv_calculation():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_ITEMS):
        res = export_replenishment_csv.invoke({"warehouse": "Warehouse-14"})
        assert "Warehouse-14" in res
        assert "1" in res  # Only 1 SKU needs replenishment (SKU-101: 50+20-10=60, while SKU-102: 40+15-100=-45 <= 0)
        assert "/api/v1/forecast/export/download/" in res

        # Extract filename from the response
        import re
        match = re.search(r"/api/v1/forecast/export/download/([\w\-\.]+)", res)
        assert match is not None, f"Download link not found in response: {res}"
        filename = match.group(1)

        # Check file on disk
        from app.core.config import BACKEND_ROOT
        export_path = BACKEND_ROOT / "data" / "exports" / filename
        assert export_path.exists()

        content = export_path.read_text(encoding="utf-8-sig")
        reader = list(csv.DictReader(io.StringIO(content)))
        assert len(reader) == 1
        row = reader[0]
        assert row["SKU_ID"] == "SKU-101"
        assert row["Product_Name"] == "Fresh Milk 1L"
        assert row["Warehouse"] == "Warehouse-14"
        assert int(row["Current_Stock"]) == 10
        assert float(row["Forecast_14D"]) == 50.0
        assert float(row["Safety_Stock"]) == 20.0
        assert int(row["Suggested_Replenishment_Qty"]) == 60  # (50 + 20) - 10 = 60


def test_export_replenishment_csv_all_warehouses():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_ITEMS):
        res = export_replenishment_csv.invoke({"warehouse": ""})
        assert "toàn bộ" in res.lower() or "all" in res.lower()
        assert "2" in res  # SKU-101 and SKU-201 need replenishment


def test_download_endpoint_success():
    from app.core.config import BACKEND_ROOT
    export_dir = BACKEND_ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    test_file = export_dir / "test_download.csv"
    test_file.write_text("SKU_ID,Product_Name\nSKU-001,Test Product\n", encoding="utf-8-sig")

    resp = client.get("/api/v1/forecast/export/download/test_download.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "SKU-001" in resp.text


def test_download_endpoint_security_path_traversal():
    resp = client.get("/api/v1/forecast/export/download/..%2F..%2Fmain.py")
    assert resp.status_code in (400, 404)


def test_download_endpoint_not_found():
    resp = client.get("/api/v1/forecast/export/download/nonexistent_file_99999.csv")
    assert resp.status_code == 404
