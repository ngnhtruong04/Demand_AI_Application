from __future__ import annotations

from unittest.mock import patch
import pytest

from app.agent.presets import check_preset_response
from app.agent.tools import list_warehouses_summary

MOCK_INVENTORY_ITEMS = [
    {
        "id": "101",
        "sku": "SKU-101",
        "name": "Organic Slow Tomato 500g",
        "category": "Produce",
        "warehouse": "Prague_1",
        "onHandStock": 800,
        "forecast14d": 7.0,
        "safetyStock": 20.0,
        "leadTimeDays": 3,
        "reorderPoint": 25.0,
        "status": "Deadstock",
    },
    {
        "id": "102",
        "sku": "SKU-102",
        "name": "Super Fast Fresh Milk 1L",
        "category": "Dairy",
        "warehouse": "Prague_1",
        "onHandStock": 50,
        "forecast14d": 700.0,
        "safetyStock": 40.0,
        "leadTimeDays": 2,
        "reorderPoint": 140.0,
        "status": "Critical",
    },
    {
        "id": "201",
        "sku": "SKU-201",
        "name": "Unsold Canned Beans 300g",
        "category": "Pantry",
        "warehouse": "Brno_1",
        "onHandStock": 450,
        "forecast14d": 4.2,
        "safetyStock": 15.0,
        "leadTimeDays": 4,
        "reorderPoint": 20.0,
        "status": "Deadstock",
    },
]


def test_list_warehouses_summary_all():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        res = list_warehouses_summary.invoke({"warehouse": ""})
        assert "DemandAI Warehouses" in res
        assert "Prague_1" in res
        assert "Brno_1" in res
        assert "Deadstock" in res
        assert "export PDF" in res
        assert "export replenishment CSV" in res


def test_list_warehouses_summary_specific():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        res = list_warehouses_summary.invoke({"warehouse": "Brno_1"})
        assert "Brno_1" in res
        assert "Prague_1" not in res
        assert "Deadstock" in res


def test_preset_slash_warehouse():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        # Pure command -> deterministic preset response
        res_pure = check_preset_response("/warehouse", "vi")
        assert res_pure is not None
        assert "DemandAI Warehouses" in res_pure

        # Pure warehouse inspection
        res_wh = check_preset_response("/warehouse Brno_1", "vi")
        assert res_wh is not None
        assert "Brno_1" in res_wh

        # Action query with export intent -> should return None so it proceeds to LLM
        res_action = check_preset_response("/warehouse Brno_1 xuất báo cáo pdf deadstock", "vi")
        assert res_action is None

        res_csv_action = check_preset_response("/warehouse Prague_1 xuất file csv", "vi")
        assert res_csv_action is None


def test_help_contains_warehouse():
    help_vi = check_preset_response("/help", "vi")
    assert help_vi is not None
    assert "/warehouse <kho>" in help_vi

    help_en = check_preset_response("/help", "en")
    assert help_en is not None
    assert "/warehouse <name>" in help_en
