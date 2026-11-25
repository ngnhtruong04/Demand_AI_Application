from __future__ import annotations

from pathlib import Path
import re
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.agent.tools import generate_pdf_report
from app.main import app
from app.core.config import BACKEND_ROOT

client = TestClient(app)

MOCK_INVENTORY_ITEMS = [
    {
        "id": "101",
        "sku": "SKU-101",
        "name": "Organic Slow Tomato 500g",
        "category": "Produce",
        "warehouse": "Prague_1",
        "onHandStock": 800,
        "forecast14d": 7.0,  # 0.5 units/day -> DOS = 1600 days -> Deadstock
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
        "forecast14d": 700.0,  # 50 units/day -> Best seller
        "safetyStock": 40.0,
        "leadTimeDays": 2,
        "reorderPoint": 140.0,
        "status": "Critical",
    },
    {
        "id": "103",
        "sku": "SKU-103",
        "name": "Wheat Bread Loaf 400g",
        "category": "Bakery",
        "warehouse": "Prague_1",
        "onHandStock": 200,
        "forecast14d": 560.0,  # 40 units/day -> Best seller
        "safetyStock": 30.0,
        "leadTimeDays": 1,
        "reorderPoint": 70.0,
        "status": "In Stock",
    },
    {
        "id": "201",
        "sku": "SKU-201",
        "name": "Unsold Canned Beans 300g",
        "category": "Pantry",
        "warehouse": "Brno_1",
        "onHandStock": 450,
        "forecast14d": 4.2,  # 0.3 units/day -> Deadstock in Brno_1
        "safetyStock": 15.0,
        "leadTimeDays": 4,
        "reorderPoint": 20.0,
        "status": "Deadstock",
    },
]


def test_generate_pdf_report_deadstock():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        res = generate_pdf_report.invoke({"focus_area": "deadstock", "warehouse": "Prague_1"})
        assert "Deadstock" in res
        assert "Prague_1" in res
        assert "/api/v1/forecast/export/download/" in res
        assert ".pdf" in res

        # Extract filename
        match = re.search(r"/api/v1/forecast/export/download/([\w\-\.]+\.pdf)", res)
        assert match is not None, f"PDF link not found in result: {res}"
        filename = match.group(1)

        pdf_path = BACKEND_ROOT / "data" / "exports" / filename
        assert pdf_path.exists()
        pdf_bytes = pdf_path.read_bytes()
        assert len(pdf_bytes) > 2000, "PDF file too small"
        assert pdf_bytes.startswith(b"%PDF-"), "Invalid PDF header signature"


def test_generate_pdf_report_bestseller():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        res = generate_pdf_report.invoke({"focus_area": "best_seller", "warehouse": ""})
        assert "/api/v1/forecast/export/download/" in res
        assert ".pdf" in res

        match = re.search(r"/api/v1/forecast/export/download/([\w\-\.]+\.pdf)", res)
        assert match is not None, f"PDF link not found in result: {res}"
        filename = match.group(1)

        pdf_path = BACKEND_ROOT / "data" / "exports" / filename
        assert pdf_path.exists()
        pdf_bytes = pdf_path.read_bytes()
        assert len(pdf_bytes) > 2000
        assert pdf_bytes.startswith(b"%PDF-")


def test_download_endpoint_serves_pdf():
    export_dir = BACKEND_ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    sample_pdf = export_dir / "sample_test_report.pdf"
    sample_pdf.write_bytes(b"%PDF-1.4\n%test pdf content\n%%EOF\n")

    resp = client.get("/api/v1/forecast/export/download/sample_test_report.pdf")
    assert resp.status_code == 200
    assert "application/pdf" in resp.headers.get("content-type", "")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert resp.content.startswith(b"%PDF-")


def test_generate_pdf_report_empty_deadstock():
    healthy_items = [item for item in MOCK_INVENTORY_ITEMS if item.get("status") != "Deadstock"]
    with patch("app.agent.tools._load_all_inventory_items", return_value=healthy_items):
        res = generate_pdf_report.invoke({"focus_area": "deadstock", "warehouse": "Prague_1"})
        assert "No Report Generated" in res
        assert "Catalog Clean & Stable" in res
        assert "/api/v1/forecast/export/download/" not in res
        assert "Download Executive PDF Report" not in res


def test_generate_pdf_report_empty_bestseller():
    zero_demand_items = [{**item, "forecast14d": 0.0} for item in MOCK_INVENTORY_ITEMS]
    with patch("app.agent.tools._load_all_inventory_items", return_value=zero_demand_items):
        res = generate_pdf_report.invoke({"focus_area": "best_seller", "warehouse": "Prague_1"})
        assert "No Report Generated" in res
        assert "No items with positive forecasted demand" in res
        assert "/api/v1/forecast/export/download/" not in res


def test_generate_pdf_report_critical():
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        res = generate_pdf_report.invoke({"focus_area": "critical", "warehouse": "Prague_1"})
        assert "/api/v1/forecast/export/download/" in res
        assert ".pdf" in res
        assert "report_critical_" in res or "critical" in res.lower()

        match = re.search(r"/api/v1/forecast/export/download/([\w\-\.]+\.pdf)", res)
        assert match is not None, f"PDF link not found in result: {res}"
        filename = match.group(1)

        pdf_path = BACKEND_ROOT / "data" / "exports" / filename
        assert pdf_path.exists()
        pdf_bytes = pdf_path.read_bytes()
        assert len(pdf_bytes) > 2000
        assert pdf_bytes.startswith(b"%PDF-")


def test_generate_pdf_report_empty_critical():
    no_crit_items = [
        {**item, "status": "In Stock", "onHandStock": 1000, "forecast14d": 14.0}
        for item in MOCK_INVENTORY_ITEMS
    ]
    with patch("app.agent.tools._load_all_inventory_items", return_value=no_crit_items):
        res = generate_pdf_report.invoke({"focus_area": "critical", "warehouse": "Prague_1"})
        assert "No Report Generated" in res
        assert "Healthy Inventory Levels" in res
        assert "/api/v1/forecast/export/download/" not in res


def test_hand_calculated_metrics_formula():
    """Verify hand-calculated exact metrics for 14-day cycle equations:
    daily_velocity = 140 / 14 = 10.0
    dos = 100 / 10.0 = 10.0
    dynamic_rop = (10.0 * 3) + 15.0 = 45.0
    replenish = max(0, ceil(140.0 + 15.0 - 100)) = 55
    """
    from app.services.report_data_service import calculate_item_metrics

    raw = {
        "unique_id": "test_calc_01",
        "sku": "SKU-TEST-01",
        "name": "Bánh Mì Ngũ Cốc 500g",
        "warehouse": "Prague_1",
        "current_stock": 100,
        "forecast_14d": 140.0,
        "safety_stock": 15.0,
        "lead_time_days": 3,
        "baseline_reorder_point": 25.0,
        "status": "In Stock",
    }
    item = calculate_item_metrics(raw)
    assert item.daily_forecast == 10.0
    assert item.days_of_supply == 10.0
    assert item.dos_display == "10.0 days"
    assert item.dynamic_rop == 45.0
    assert item.suggested_replenishment_14d == 55


def test_zero_forecast_vs_missing_forecast_differentiation():
    """Strictly verify that forecast=0.0 displays 'Không xác định từ dự báo' (NO 999!)
    and missing forecast displays 'Thiếu dữ liệu'.
    """
    from app.services.report_data_service import calculate_item_metrics

    # Item with forecast = 0
    zero_item = calculate_item_metrics({
        "unique_id": "zero_f",
        "current_stock": 50,
        "forecast_14d": 0.0,
        "safety_stock": 10.0,
        "lead_time_days": 2,
    })
    assert zero_item.days_of_supply is None
    assert zero_item.dos_display == "N/A (Zero Demand)"
    assert "999" not in zero_item.dos_display

    # Item with missing forecast (None)
    missing_item = calculate_item_metrics({
        "unique_id": "missing_f",
        "current_stock": 50,
        "forecast_14d": None,
        "safety_stock": 10.0,
        "lead_time_days": 2,
    })
    assert missing_item.days_of_supply is None
    assert missing_item.dos_display == "Missing Data"
    assert missing_item.suggested_replenishment_14d is None


def test_more_than_60_items_not_truncated():
    """Ensure report does not silently drop items after 60 rows."""
    from app.services.report_data_service import fetch_report_dataset

    items_80 = [
        {
            "id": f"item_{i}",
            "sku": f"SKU-{i:03d}",
            "name": f"Product {i}",
            "warehouse": "Prague_1",
            "onHandStock": 10 + i,
            "forecast14d": 50.0 + i,
            "safetyStock": 20.0,
            "leadTimeDays": 2,
            "status": "In Stock",
        }
        for i in range(80)
    ]

    ds = fetch_report_dataset(focus_area="overview", warehouse_filter="Prague_1", raw_items_override=items_80)
    assert ds.metadata.total_records_in_scope == 80
    assert ds.metadata.matching_records_count == 80
    assert len(ds.items) == 80, f"Expected 80 items, but got {len(ds.items)}"


def test_top_n_does_not_alter_portfolio_kpis():
    """Verify Top N ranking does not change overall scope KPIs."""
    from app.services.report_data_service import fetch_report_dataset

    items_70 = [
        {
            "id": f"sku_{i}",
            "sku": f"SKU-{i}",
            "warehouse": "Prague_1",
            "onHandStock": 100,
            "forecast14d": 200.0,
            "safetyStock": 10.0,
            "leadTimeDays": 1,
            "status": "In Stock",
        }
        for i in range(70)
    ]
    ds = fetch_report_dataset(focus_area="overview", warehouse_filter="Prague_1", raw_items_override=items_70)
    # Total stock should be 70 * 100 = 7000, total forecast 70 * 200 = 14000
    assert ds.metadata.total_on_hand_stock == 7000
    assert ds.metadata.total_forecast_14d == 14000.0
    assert len(ds.top_action_items) <= 15
    # Total scope records still 70
    assert ds.metadata.total_records_in_scope == 70


def test_warehouse_exact_filter_and_no_crosstalk():
    """Verify warehouse exact matching prevents cross-warehouse contamination."""
    from app.services.report_data_service import resolve_warehouse_filter

    whs = ["Prague_1", "Prague_2", "Prague_3", "Brno_1"]

    # Exact match works
    matched, label, err = resolve_warehouse_filter("Prague_1", whs)
    assert err is None
    assert matched == ["Prague_1"]

    # Ambiguous substring matching multiple warehouses is rejected with clear error
    matched_amb, _, err_amb = resolve_warehouse_filter("Prague", whs)
    assert len(matched_amb) == 0
    assert err_amb is not None
    assert "ambiguous" in err_amb


def test_depletion_risk_day_calculation():
    """Verify daily points cumulative consumption detects exact depletion day."""
    from app.services.report_data_service import calculate_item_metrics

    daily_pts = [
        {"day": 1, "date": "2024-06-03", "predicted_sales": 10.0},
        {"day": 2, "date": "2024-06-04", "predicted_sales": 10.0},
        {"day": 3, "date": "2024-06-05", "predicted_sales": 10.0},
        {"day": 4, "date": "2024-06-06", "predicted_sales": 10.0},
    ]
    # Stock is 25: Day 1 (10), Day 2 (20), Day 3 (30 >= 25) -> Crashes on 2024-06-05!
    raw = {
        "unique_id": "deplete_test",
        "current_stock": 25,
        "forecast_14d": 40.0,
        "safety_stock": 5.0,
        "lead_time_days": 2,
    }
    item = calculate_item_metrics(raw, daily_points=daily_pts)
    assert "2024-06-05" in item.depletion_risk_day


def test_vietnamese_pdf_multi_page_generation(tmp_path):
    """Verify multi-page PDF generation with Vietnamese characters and landscape layout."""
    from app.services.report_data_service import fetch_report_dataset
    from app.services.pdf_report_generator import generate_multi_page_report

    vn_items = [
        {
            "id": f"vn_{i}",
            "sku": f"VN-{i:03d}",
            "name": f"Sữa tươi tiệt trùng nguyên chất loại {i} thơm ngon bổ dưỡng hảo hạng",
            "category": "Bơ sữa & Trứng",
            "warehouse": "Hà Nội Kho Trung Tâm",
            "onHandStock": 10 * i,
            "forecast14d": 50.0 + i * 5,
            "safetyStock": 15.0,
            "leadTimeDays": 2,
            "status": "Critical" if i < 10 else "In Stock",
        }
        for i in range(25)
    ]
    ds = fetch_report_dataset(focus_area="critical", warehouse_filter="", raw_items_override=vn_items)
    pdf_out = tmp_path / "test_vn_critical.pdf"
    res = generate_multi_page_report(ds, focus_area="critical", warehouse_label="Hà Nội Kho Trung Tâm", output_path=pdf_out)

    assert res["status"] == "success"
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 10000
    assert pdf_out.read_bytes().startswith(b"%PDF-")


def test_inactive_skus_filtered_by_default():
    """Verify that inactive items (10+ days without sales) are filtered out by default unless use_inactive_items=True."""
    from unittest.mock import patch
    from app.services.report_data_service import fetch_report_dataset

    mock_inactive_set = {"sku_inactive_99"}
    mock_items = [
        {
            "id": "sku_active_1",
            "unique_id": "sku_active_1",
            "sku": "SKU-ACT-1",
            "name": "Active SKU",
            "warehouse": "Prague_1",
            "onHandStock": 100,
            "forecast14d": 50.0,
            "status": "In Stock",
        },
        {
            "id": "sku_inactive_99",
            "unique_id": "sku_inactive_99",
            "sku": "SKU-INACT-99",
            "name": "Inactive SKU (10+ days no sales)",
            "warehouse": "Prague_1",
            "onHandStock": 300,
            "forecast14d": 0.0,
            "status": "Deadstock",
        },
    ]

    with patch("app.services.report_data_service.get_inactive_uids", return_value=mock_inactive_set):
        # By default use_inactive_items=False -> Inactive SKU must be excluded
        ds_default = fetch_report_dataset(focus_area="overview", warehouse_filter="Prague_1", raw_items_override=mock_items, use_inactive_items=False)
        assert len(ds_default.items) == 1
        assert ds_default.items[0].unique_id == "sku_active_1"

        # When use_inactive_items=True -> Inactive SKU is included
        ds_included = fetch_report_dataset(focus_area="overview", warehouse_filter="Prague_1", raw_items_override=mock_items, use_inactive_items=True)
        assert len(ds_included.items) == 2


def test_format_report_filename():
    """Verify that format_report_filename produces standardized English filenames:
    report_{TOPIC}_{WAREHOUSE}_{YYYYMMDD}_{HHMMSS}.pdf
    """
    from datetime import datetime
    from app.services.pdf_report_generator import format_report_filename

    fixed_dt = datetime(2026, 9, 22, 11, 30, 45)

    # 1. Single warehouse
    fn1 = format_report_filename("critical", "Prague_1", ["Prague_1"], export_datetime=fixed_dt)
    assert fn1 == "report_critical_prague_1_20260922_113045.pdf"

    # 2. All warehouses via Vietnamese label
    fn2 = format_report_filename("overview", "Entire Warehouse Network (7 Warehouses)", ["Prague_1", "Brno_1"], export_datetime=fixed_dt)
    assert fn2 == "report_overview_all_warehouses_20260922_113045.pdf"

    # 3. All warehouses via empty string
    fn3 = format_report_filename("deadstock", "", None, export_datetime=fixed_dt)
    assert fn3 == "report_deadstock_all_warehouses_20260922_113045.pdf"

    # 4. Multiple warehouses in list
    fn4 = format_report_filename("best_seller", "all", ["Prague_1", "Prague_2"], export_datetime=fixed_dt)
    assert fn4 == "report_best_seller_all_warehouses_20260922_113045.pdf"


def test_executive_insights_no_bullets_in_chat_and_pdf():
    """Verify that executive insights format does not contain redundant bullets like '• 1.'."""
    from unittest.mock import patch
    from app.agent.tools import generate_pdf_report

    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_INVENTORY_ITEMS):
        res = generate_pdf_report.invoke({"focus_area": "critical", "warehouse": "Prague_1"})
        # Chat response must use **1.**, **2.** and not • **1.**
        assert "**1.** " in res
        assert "• **1.**" not in res
