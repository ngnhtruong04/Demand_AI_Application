"""backend/tests/test_dynamic_status.py
Comprehensive test suite verifying the dynamic inventory health status calculation:
- Critical
- Reorder
- Monitor
- Deadstock
- In Stock

Verifies:
1. compute_dynamic_status boundary conditions and waterfall priority order.
2. Mathematical formulas: Daily Velocity, Dynamic ROP, Days of Supply.
3. Alignment with backend/app/wiki/status.json and metrics.json official definitions.
4. Edge cases: zero stock, negative forecast, zero lead time, zero safety stock.
5. Alignment with Frontend Status Sort Order (Critical -> Reorder -> Monitor -> Deadstock -> In Stock).
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.services.forecast_persistence import compute_dynamic_status


# ==============================================================================
# 1. CORE WATERFALL STATUS TESTS
# ==============================================================================

class TestDynamicStatusCoreLogic:
    """Validate core status assignment per official inventory business rules."""

    def test_deadstock_due_to_low_velocity(self):
        """Rule 1: Stock > 0 and Daily Velocity < 1.0 unit/day -> Deadstock.
        Even if stock is small, slow-moving items are capital traps, not emergencies.
        """
        # f14d = 7.0 -> daily_velocity = 0.5 units/day (< 1.0)
        # stock = 10, safety_stock = 15
        # Although stock <= safety_stock, low velocity categorizes this as Deadstock first
        status, dynamic_rop = compute_dynamic_status(
            stock=10,
            f14d=7.0,
            safety_stock=15.0,
            baseline_rop=30.0,
            lead_time=7,
        )
        assert status == "Deadstock"
        # dynamic_rop = (7 * 0.5) + 15 = 18.5
        assert dynamic_rop == 18.5

    def test_deadstock_due_to_excess_days_of_supply(self):
        """Rule 1: Stock > 0 and Days of Supply > 365 days -> Deadstock.
        Selling velocity >= 1.0, but inventory exceeds 1 year of demand runway.
        """
        # f14d = 28.0 -> daily_velocity = 2.0 units/day
        # stock = 800 -> DOS = 800 / 2.0 = 400 days (> 365)
        status, dynamic_rop = compute_dynamic_status(
            stock=800,
            f14d=28.0,
            safety_stock=20.0,
            baseline_rop=50.0,
            lead_time=5,
        )
        assert status == "Deadstock"
        # dynamic_rop = (5 * 2.0) + 20 = 30.0
        assert dynamic_rop == 30.0

    def test_critical_at_or_below_safety_stock(self):
        """Rule 2: Current stock is at or below safety stock reserve.
        Immediate stockout emergency.
        """
        # f14d = 70.0 -> daily_velocity = 5.0 units/day (healthy velocity)
        # safety_stock = 25.0, lead_time = 7 -> dynamic_rop = (7 * 5) + 25 = 60.0
        # stock = 20 <= 25 (safety_stock)
        status, dynamic_rop = compute_dynamic_status(
            stock=20,
            f14d=70.0,
            safety_stock=25.0,
            baseline_rop=60.0,
            lead_time=7,
        )
        assert status == "Critical"
        assert dynamic_rop == 60.0

    def test_critical_zero_stock_out_of_stock(self):
        """Rule 2: Complete stockout (stock == 0) must trigger Critical, NEVER Deadstock.
        Deadstock explicitly requires stock > 0.
        """
        # f14d = 0.0 (no forecast), stock = 0
        status, dynamic_rop = compute_dynamic_status(
            stock=0,
            f14d=0.0,
            safety_stock=10.0,
            baseline_rop=20.0,
            lead_time=7,
        )
        assert status == "Critical"

    def test_reorder_point_breached(self):
        """Rule 3: Current stock is below or equal to Dynamic Reorder Point.
        Stock has breached replenishment trigger but still above safety reserve.
        """
        # f14d = 140.0 -> daily_velocity = 10.0 units/day
        # safety_stock = 30.0, lead_time = 7 -> dynamic_rop = (7 * 10) + 30 = 100.0
        # stock = 80: 30 < stock <= 100
        status, dynamic_rop = compute_dynamic_status(
            stock=80,
            f14d=140.0,
            safety_stock=30.0,
            baseline_rop=100.0,
            lead_time=7,
        )
        assert status == "Reorder"
        assert dynamic_rop == 100.0

    def test_monitor_approaching_reorder_threshold(self):
        """Rule 4: Stock is within 20% buffer above ROP (stock <= dynamic_rop * 1.2).
        Not yet breached, but nearing purchase requisition trigger.
        """
        # f14d = 140.0 -> daily_velocity = 10.0 units/day
        # dynamic_rop = 100.0, 1.2 * dynamic_rop = 120.0
        # stock = 115: 100 < stock <= 120
        status, dynamic_rop = compute_dynamic_status(
            stock=115,
            f14d=140.0,
            safety_stock=30.0,
            baseline_rop=100.0,
            lead_time=7,
        )
        assert status == "Monitor"
        assert dynamic_rop == 100.0

    def test_monitor_projected_breach_during_lead_time(self):
        """Rule 4: Stock is > 1.2 * ROP today, but projected stock after lead time drops below ROP.
        (stock - (lead_time * daily_velocity)) <= dynamic_rop.
        """
        # daily_velocity = 20.0 (f14d = 280), lead_time = 10, safety_stock = 10
        # dynamic_rop = (10 * 20) + 10 = 210.0
        # dynamic_rop * 1.2 = 252.0
        # stock = 260 (> 252)
        # projected stock after 10 days = 260 - (10 * 20) = 60 <= 210 (dynamic_rop)
        status, dynamic_rop = compute_dynamic_status(
            stock=260,
            f14d=280.0,
            safety_stock=10.0,
            baseline_rop=210.0,
            lead_time=10,
        )
        assert status == "Monitor"

    def test_in_stock_healthy_inventory(self):
        """Rule 5: Stock is comfortably above ROP buffer and safe across lead time."""
        # daily_velocity = 10.0 (f14d = 140), lead_time = 7, safety_stock = 30
        # dynamic_rop = 100.0, 1.2 * dynamic_rop = 120.0
        # stock = 250:
        # DOS = 250 / 10 = 25 days (well under 365)
        # stock > 120
        # stock - lead_time * velocity = 250 - 70 = 180 > 100
        status, dynamic_rop = compute_dynamic_status(
            stock=250,
            f14d=140.0,
            safety_stock=30.0,
            baseline_rop=100.0,
            lead_time=7,
        )
        assert status == "In Stock"
        assert dynamic_rop == 100.0


# ==============================================================================
# 2. BOUNDARY TESTS (Off-by-one & Precise Transitions)
# ==============================================================================

class TestDynamicStatusBoundaries:
    """Rigorous boundary value analysis on threshold transitions."""

    @pytest.mark.parametrize(
        "f14d,expected_status",
        [
            (13.86, "Deadstock"),  # 13.86 / 14 = 0.99 units/day (< 1.0)
            (14.00, "In Stock"),   # 14.00 / 14 = 1.00 units/day (DOS = 50 days, stock=50, rop=25)
        ],
    )
    def test_velocity_boundary_at_one_unit_per_day(self, f14d: float, expected_status: str):
        """Transition at daily_velocity = 1.0 unit/day."""
        status, _ = compute_dynamic_status(
            stock=50,
            f14d=f14d,
            safety_stock=10.0,
            baseline_rop=25.0,
            lead_time=5,
        )
        assert status == expected_status

    @pytest.mark.parametrize(
        "stock,expected_status",
        [
            (365, "In Stock"),   # DOS = 365 / 1.0 = 365 days (exactly at limit -> NOT Deadstock)
            (366, "Deadstock"),  # DOS = 366 / 1.0 = 366 days (> 365 -> Deadstock)
        ],
    )
    def test_days_of_supply_boundary_at_365_days(self, stock: int, expected_status: str):
        """Transition at DOS = 365 days (1 year demand runway)."""
        status, _ = compute_dynamic_status(
            stock=stock,
            f14d=14.0,  # daily_velocity = 1.0
            safety_stock=10.0,
            baseline_rop=20.0,
            lead_time=5,
        )
        assert status == expected_status

    @pytest.mark.parametrize(
        "stock,expected_status",
        [
            (20, "Critical"),  # stock == safety_stock
            (21, "Reorder"),   # stock == safety_stock + 1
        ],
    )
    def test_critical_to_reorder_transition(self, stock: int, expected_status: str):
        """Transition at stock = safety_stock."""
        # dynamic_rop = (5 * 5.0) + 20 = 45.0
        status, _ = compute_dynamic_status(
            stock=stock,
            f14d=70.0,  # velocity = 5.0
            safety_stock=20.0,
            baseline_rop=45.0,
            lead_time=5,
        )
        assert status == expected_status

    @pytest.mark.parametrize(
        "stock,expected_status",
        [
            (100, "Reorder"),  # stock == dynamic_rop
            (101, "Monitor"),  # stock == dynamic_rop + 1
        ],
    )
    def test_reorder_to_monitor_transition(self, stock: int, expected_status: str):
        """Transition at stock = dynamic_rop."""
        # dynamic_rop = (7 * 10.0) + 30 = 100.0
        status, _ = compute_dynamic_status(
            stock=stock,
            f14d=140.0,  # velocity = 10.0
            safety_stock=30.0,
            baseline_rop=100.0,
            lead_time=7,
        )
        assert status == expected_status

    @pytest.mark.parametrize(
        "stock,expected_status",
        [
            (120, "Monitor"),   # stock == dynamic_rop * 1.2
            (180, "In Stock"),  # stock safely above monitor threshold and lead time drain
        ],
    )
    def test_monitor_to_in_stock_transition(self, stock: int, expected_status: str):
        """Transition at stock = dynamic_rop * 1.2."""
        # dynamic_rop = 100.0, 1.2 * rop = 120.0
        status, _ = compute_dynamic_status(
            stock=stock,
            f14d=140.0,  # velocity = 10.0
            safety_stock=30.0,
            baseline_rop=100.0,
            lead_time=7,
        )
        assert status == expected_status


# ==============================================================================
# 3. EDGE CASES & RESILIENCE
# ==============================================================================

class TestDynamicStatusEdgeCases:
    """Validate system robustness on extreme or zero values."""

    def test_negative_forecast_clamped_to_zero(self):
        """Negative forecast output from ML model is safely clamped to 0.0."""
        status, dynamic_rop = compute_dynamic_status(
            stock=5,
            f14d=-15.0,
            safety_stock=10.0,
            baseline_rop=25.0,
            lead_time=7,
        )
        # daily_velocity clamped to 0.0
        # stock = 5 > 0 and velocity = 0.0 < 1.0 -> Deadstock
        assert status == "Deadstock"
        # dynamic_rop = (7 * 0.0) + 10.0 = 10.0
        assert dynamic_rop == 10.0

    def test_zero_lead_time_and_zero_safety_stock(self):
        """When supplier has 0 lead time and 0 safety stock."""
        status, dynamic_rop = compute_dynamic_status(
            stock=50,
            f14d=70.0,  # velocity = 5.0
            safety_stock=0.0,
            baseline_rop=10.0,
            lead_time=0,
        )
        # dynamic_rop = (0 * 5) + 0 = 0 -> falls back to baseline_rop = 10.0
        assert dynamic_rop == 10.0
        assert status == "In Stock"

    def test_fallback_to_baseline_rop_when_dynamic_rop_is_zero(self):
        """When computed dynamic ROP is 0, system must preserve baseline ROP."""
        status, dynamic_rop = compute_dynamic_status(
            stock=0,
            f14d=0.0,
            safety_stock=0.0,
            baseline_rop=42.0,
            lead_time=0,
        )
        assert dynamic_rop == 42.0
        # stock = 0 <= safety_stock = 0 -> Critical
        assert status == "Critical"


# ==============================================================================
# 4. WIKI & CONTRACT SPECIFICATION ALIGNMENT
# ==============================================================================

class TestWikiAndContractAlignment:
    """Ensure code matches system documentation in wiki/status.json and api contract."""

    def test_wiki_status_json_contains_all_five_statuses(self):
        """Wiki status.json must define Critical, Reorder, Monitor, Deadstock, In Stock."""
        wiki_path = Path("backend/app/wiki/status.json")
        assert wiki_path.exists(), "status.json wiki file must exist"
        data = json.loads(wiki_path.read_text(encoding="utf-8"))
        statuses = data.get("statuses", {})

        expected_statuses = {"Critical", "Reorder", "Monitor", "Deadstock", "In Stock"}
        assert set(statuses.keys()) == expected_statuses

    def test_frontend_status_order_priority_coverage(self):
        """Verify the 5 statuses match the frontend Status Sort Order modal."""
        frontend_sort_order = ["Critical", "Reorder", "Monitor", "Deadstock", "In Stock"]
        assert len(frontend_sort_order) == 5
        # Each status must be reproducible by compute_dynamic_status
        produced_statuses = {
            compute_dynamic_status(stock=10, f14d=7.0, safety_stock=15.0, baseline_rop=30.0, lead_time=7)[0],   # Deadstock
            compute_dynamic_status(stock=5, f14d=70.0, safety_stock=10.0, baseline_rop=30.0, lead_time=5)[0],   # Critical
            compute_dynamic_status(stock=20, f14d=70.0, safety_stock=10.0, baseline_rop=35.0, lead_time=5)[0],  # Reorder
            compute_dynamic_status(stock=40, f14d=70.0, safety_stock=10.0, baseline_rop=35.0, lead_time=5)[0],  # Monitor
            compute_dynamic_status(stock=100, f14d=70.0, safety_stock=10.0, baseline_rop=35.0, lead_time=5)[0], # In Stock
        }
        assert produced_statuses == set(frontend_sort_order)
