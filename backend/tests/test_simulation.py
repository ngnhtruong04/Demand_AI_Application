"""Tests for Group 5: What-If Demand Simulation (simulate_demand)."""
from unittest.mock import patch
import pytest

from app.services.simulation_service import (
    simulate_sku_discount,
    format_simulation_markdown,
    get_latest_valid_run_id,
)
from app.agent.tools import simulate_demand, SKU_TOOLS
from app.agent.skills import match_skill, SKILLS


def test_skills_registration():
    """Verify what_if_simulation is registered in SKILLS and SKU_TOOLS."""
    assert "what_if_simulation" in SKILLS
    assert SKILLS["what_if_simulation"]["tool"] == "simulate_demand"

    # Verify tool is registered in SKU_TOOLS array
    tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in SKU_TOOLS]
    assert "simulate_demand" in tool_names


def test_match_skill_what_if_queries():
    """Test skill routing for Vietnamese and English what-if scenario questions."""
    q_vi = "Nếu tuần sau tôi giảm giá 20% cho SKU-4471 thì dự báo bán được bao nhiêu? Có cứu được tình trạng deadstock không?"
    skill_vi = match_skill(q_vi)
    assert skill_vi["id"] == "what_if_simulation"
    assert skill_vi["tool"] == "simulate_demand"

    q_en = "What if we discount SKU-001 by 15% next week? Will it clear inventory?"
    skill_en = match_skill(q_en)
    assert skill_en["id"] == "what_if_simulation"
    assert skill_en["tool"] == "simulate_demand"


def test_simulate_sku_discount_unknown_sku():
    """Verify error handling when SKU cannot be resolved."""
    with patch("app.services.simulation_service.resolve_sku_item", return_value=None), \
         patch("app.services.simulation_service.get_latest_valid_run_id", return_value=None):
        res = simulate_sku_discount("SKU-99999999-NONEXISTENT", 20)
        assert res["success"] is False
        assert "not found" in res["error"].lower()

        # Markdown format should cleanly display error
        md = format_simulation_markdown(res)
        assert "Simulation Error" in md


def test_simulate_sku_discount_execution():
    """Verify real simulation execution with ML ensemble re-inference."""
    res = simulate_sku_discount("SKU-4471", 20)
    assert res["success"] is True
    assert res["sku"] == "SKU-4471"
    assert res["discount_percent"] == 20.0
    assert res["baseline_forecast_14d"] > 0
    assert res["simulated_forecast_14d"] > res["baseline_forecast_14d"]
    assert res["pct_change"] > 0
    assert res["inference_method"] == "ensemble_ml"
    assert "deadstock_verdict" in res
    assert "current_stock" in res
    assert "remaining_stock" in res


def test_simulate_sku_discount_clamping():
    """Verify discount percentage input boundary validation."""
    res_neg = simulate_sku_discount("SKU-4471", -15)
    assert res_neg["success"] is True
    assert res_neg["discount_percent"] == 0.0

    res_high = simulate_sku_discount("SKU-4471", 99)
    assert res_high["success"] is True
    assert res_high["discount_percent"] == 90.0


def test_simulate_sku_discount_deadstock_mock():
    """Verify deadstock surplus detection and recommendation with mock scenario matching user story."""
    mock_deadstock_item = {
        "id": "mock-lamp",
        "unique_id": "mock-lamp",
        "sku": "SKU-4471",
        "name": "Desk lamp",
        "warehouse": "Prague_1",
        "category": "Lighting",
        "onHandStock": 820,
        "forecast14d": 85.0,
        "safetyStock": 30.0,
        "reorderPoint": 50.0,
        "leadTimeDays": 3,
        "status": "Deadstock",
        "run_id": None,
    }
    with patch("app.services.simulation_service.resolve_sku_item", return_value=mock_deadstock_item):
        res = simulate_sku_discount("SKU-4471", 20)
        assert res["success"] is True
        assert res["current_stock"] == 820
        assert res["is_deadstock"] is True
        assert res["remaining_stock"] > 600
        assert res["clearance_status"] == "partial_deadstock_remaining"
        assert "CHƯA CỨU HẾT DEADSTOCK" in res["deadstock_verdict"]
        assert "dư" in res["deadstock_verdict"]
        assert res["recommended_discount"] > 20.0


def test_simulate_demand_tool_invocation():
    """Verify tool execution via .func and .invoke."""
    # Test via .func with legacy price_discount_percent
    output = simulate_demand.func(sku_code="SKU-4471", price_discount_percent=20)
    assert "What-If Demand & Price Simulation: SKU-4471" in output
    assert "Nhận định Điều hành & Quyết định Giá (BLUF)" in output
    assert "Bảng So sánh Kịch bản (Scenario Comparison)" in output
    assert "Khuyến nghị Vận hành & Quyết định Giá" in output
    assert "| **Đơn giá sản phẩm** |" in output
    assert "| **Dự báo nhu cầu 14 ngày** |" in output
    assert "| **Doanh thu dự kiến 14 ngày** |" in output
    assert "| **Độ co giãn của cầu (PED)** |" in output

    # Test via LangChain .invoke
    inv_output = simulate_demand.invoke({"sku_code": "SKU-4471", "price_discount_percent": 20})
    assert "What-If Demand & Price Simulation: SKU-4471" in inv_output


def test_get_latest_valid_run_id():
    """Verify helper finds a valid run with all 14 horizon pickles."""
    run_id = get_latest_valid_run_id()
    assert run_id is not None
    assert len(run_id) == 36


def test_multi_warehouse_auto_detection():
    """Verify multi-warehouse auto-detection when querying a product present in multiple distribution hubs."""
    res = simulate_sku_discount("Baguette_40", 20)
    assert res["success"] is True
    assert res["mode"] == "multi_warehouse"
    assert len(res["warehouses"]) == 4
    assert res["has_asymmetry"] is True
    assert res["transferable_units"] > 0
    assert res["total_stock"] > 40000

    # Test Markdown formatting contains multi-warehouse breakdown table and stock transfer advice
    md = format_simulation_markdown(res)
    assert "Multi-Warehouse What-If Simulation: Baguette_40" in md
    assert "Bảng So sánh & Đánh giá Tác động Theo Từng Kho" in md
    assert "TOÀN MẠNG LƯỚI" in md
    assert "CẢNH BÁO BẤT CÂN ĐỐI TỒN KHO" in md
    assert "Inter-Warehouse Stock Transfer" in md


def test_single_warehouse_targeted_filter():
    """Verify targeted single warehouse simulation when warehouse parameter is provided."""
    res = simulate_sku_discount("Baguette_40", 20, warehouse="Prague_2")
    assert res["success"] is True
    assert res["mode"] == "single_warehouse"
    assert res["warehouse"] == "Prague_2"
    assert res["sku"] == "SKU-5295"
    assert res["current_stock"] == 18

    # Tool invocation with warehouse parameter
    tool_out = simulate_demand.invoke({
        "sku_code": "Baguette_40",
        "price_discount_percent": 20,
        "warehouse": "Prague_2",
    })
    assert "Kho `Prague_2`" in tool_out
    assert "SKU-5295" in tool_out


def test_simulate_price_increase_execution():
    """Verify real simulation execution with ML ensemble for price increase scenario (+15%)."""
    from app.services.simulation_service import simulate_sku_price_change
    res = simulate_sku_price_change("SKU-4471", 15.0)
    assert res["success"] is True
    assert res["sku"] == "SKU-4471"
    assert res["action_type"] == "price_increase"
    assert res["price_change_percent"] == 15.0
    assert res["increase_percent"] == 15.0
    assert res["new_price"] > res["sell_price"]
    assert res["baseline_revenue_14d"] > 0
    assert res["simulated_revenue_14d"] > 0
    assert "revenue_delta" in res
    assert "price_elasticity_demand" in res
    assert "elasticity_label" in res


def test_simulate_price_increase_ped_and_markdown():
    """Verify price elasticity (PED) calculations and Markdown generation for price increases."""
    from app.services.simulation_service import simulate_sku_price_change, format_simulation_markdown
    res = simulate_sku_price_change("SKU-4471", 15.0)
    assert res["success"] is True
    assert isinstance(res["price_elasticity_demand"], (int, float))
    assert res["elasticity_label"] in (
        "Co giãn cao (Price Elastic - Nhạy cảm giá)",
        "Co giãn đơn vị (Unit Elastic)",
        "Bất co giãn (Inelastic - Ít nhạy cảm giá)",
    )

    md = format_simulation_markdown(res)
    assert "What-If Demand & Price Simulation: SKU-4471" in md
    assert "Kịch bản Tăng Giá" in md
    assert "Doanh thu dự kiến 14 ngày" in md
    assert "Độ co giãn của cầu (PED)" in md
    assert "Triển khai tăng giá niêm yết" in md or "Hạn chế tăng giá mạnh" in md


def test_multi_warehouse_price_increase():
    """Verify multi-warehouse simulation under a system-wide price increase (+20%)."""
    from app.services.simulation_service import simulate_sku_price_change, format_simulation_markdown
    res = simulate_sku_price_change("Baguette_40", 20.0)
    assert res["success"] is True
    assert res["mode"] == "multi_warehouse"
    assert res["action_type"] == "price_increase"
    assert res["price_change_percent"] == 20.0
    assert len(res["warehouses"]) == 4
    assert res["total_revenue_delta"] > 0

    md = format_simulation_markdown(res)
    assert "Multi-Warehouse What-If Simulation: Baguette_40" in md
    assert "Áp dụng mức tăng giá **+20%**" in md
    from app.core.config import settings
    assert f"Doanh thu 14d ({settings.default_currency_unit})" in md
    assert "TĂNG GIÁ KHẢ THI TRÊN TOÀN MẠNG LƯỚI" in md
    assert "Độ co giãn PED" in md


def test_simulate_demand_signed_price_change():
    """Verify simulate_demand tool handles signed price_change_percent for both hikes and discounts."""
    # 1. Price increase (+15%)
    res_pos = simulate_demand.invoke({"sku_code": "SKU-4471", "price_change_percent": 15.0})
    assert "Kịch bản Tăng Giá" in res_pos
    assert "+15%" in res_pos

    # 2. Discount (-25%)
    res_neg = simulate_demand.invoke({"sku_code": "SKU-4471", "price_change_percent": -25.0})
    assert "Kịch bản Giảm Giá" in res_neg
    assert "-25%" in res_neg
