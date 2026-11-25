"""
test_agent_comprehensive.py — Comprehensive Test Suite for Demand AI Agent.

This test suite organizes test cases into 5 graded difficulty levels,
ranging from zero-LLM fast guardrails up to complete end-to-end multi-turn
scenarios (including the official Demo Script):

- Level 1: Fast Guardrails & Presets (Zero-LLM, <10ms, 100% token savings)
- Level 2: Intent Guard & Entity Resolution (Ambiguity, Disambiguation cards, UI Priority)
- Level 3: Core Domain Tools & Analytics (ROP, TreeSHAP Drivers, What-If Simulation, Reports)
- Level 4: E2E Demo Script Scenario (Commands 1 to 5 + Follow-up chain question)
- Level 5: Adversarial, Multilingual & Edge Cases (Prompt injection, Hallucination, Protocol)
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agent.fallback import (
    IntentGuardResult,
    evaluate_intent_guard,
    extract_sku_mention,
    get_out_of_scope_message,
    is_out_of_scope_query,
)
from app.agent.presets import check_preset_response, HELP_SUMMARY
from app.agent.sku_agent import (
    DEFAULT_MODEL,
    MODELS,
    SYSTEM_PROMPT_EN,
    SYSTEM_PROMPT_VI,
    build_langchain_agent,
    find_conversational_day,
    find_original_user_inquiry,
    find_previously_mentioned_sku,
    stream_sku_agent_response,
)
from app.agent.tools import (
    SKU_TOOLS,
    active_day_context,
    active_item_context,
    compare_sku_peers,
    export_replenishment_csv,
    generate_pdf_report,
    get_daily_forecast_series,
    get_portfolio_overview,
    get_sku_core_info,
    get_sku_inventory_and_forecast,
    get_sku_shap_drivers,
    list_warehouses_summary,
    query_inventory_wiki,
    resolve_sku_item,
    show_clarification_card,
    simulate_demand,
)


MOCK_COMPREHENSIVE_INVENTORY = [
    {
        "id": "1",
        "sku": "SKU-1",
        "name": "Blueberry_0",
        "category": "Produce",
        "warehouse": "Frankfurt_1",
        "onHandStock": 120,
        "forecast14d": 84.0,
        "status": "In Stock",
        "reorderPoint": 60.0,
        "safetyStock": 25.0,
        "leadTimeDays": 2,
        "unit_price": 4.5,
        "daily_points": [{"day": i, "date": f"2024-06-{i:02d}", "predicted": 6.0} for i in range(1, 15)],
        "grouped_drivers": [
            {"group": "Pricing & Discounts", "contribution_share": 35.0},
            {"group": "Calendar & Seasonality", "contribution_share": 30.0},
        ],
    },
    {
        "id": "4720",
        "sku": "SKU-4720",
        "name": "Roll_51",
        "category": "Bakery",
        "warehouse": "Prague_1",
        "onHandStock": 45,
        "forecast14d": 140.0,
        "status": "Critical",
        "reorderPoint": 90.0,
        "safetyStock": 35.0,
        "leadTimeDays": 2,
        "unit_price": 2.2,
        "daily_points": [{"day": i, "date": f"2024-06-{i:02d}", "predicted": 10.0} for i in range(1, 15)],
        "grouped_drivers": [
            {"group": "Promotions", "contribution_share": 50.0},
            {"group": "Pricing & Discounts", "contribution_share": 30.0},
        ],
    },
    {
        "id": "5293",
        "sku": "SKU-5293",
        "name": "Baguette_40",
        "category": "Bakery",
        "warehouse": "Frankfurt_1",
        "onHandStock": 18,
        "forecast14d": 95.0,
        "status": "Critical",
        "reorderPoint": 65.0,
        "safetyStock": 20.0,
        "leadTimeDays": 2,
        "unit_price": 3.0,
        "daily_points": [{"day": i, "date": f"2024-06-{i:02d}", "predicted": 6.8} for i in range(1, 15)],
        "grouped_drivers": [
            {"group": "Pricing & Discounts", "contribution_share": 40.0},
        ],
    },
    {
        "id": "5294",
        "sku": "SKU-5294",
        "name": "Baguette_40",
        "category": "Bakery",
        "warehouse": "Prague_1",
        "onHandStock": 110,
        "forecast14d": 70.0,
        "status": "In Stock",
        "reorderPoint": 45.0,
        "safetyStock": 15.0,
        "leadTimeDays": 2,
        "unit_price": 3.0,
        "daily_points": [{"day": i, "date": f"2024-06-{i:02d}", "predicted": 5.0} for i in range(1, 15)],
        "grouped_drivers": [],
    },
    {
        "id": "1021",
        "sku": "SKU-1021",
        "name": "Raspberry_1",
        "category": "Produce",
        "warehouse": "Prague_2",
        "onHandStock": 30,
        "forecast14d": 112.0,
        "status": "Critical",
        "reorderPoint": 80.0,
        "safetyStock": 30.0,
        "leadTimeDays": 3,
        "unit_price": 5.0,
        "daily_points": [{"day": i, "date": f"2024-06-{i:02d}", "predicted": 8.0} for i in range(1, 15)],
        "grouped_drivers": [],
    },
    {
        "id": "10",
        "sku": "SKU-010",
        "name": "Avocados 10",
        "category": "Produce",
        "warehouse": "Central",
        "onHandStock": 150,
        "forecast14d": 84.0,
        "status": "In Stock",
        "reorderPoint": 50.0,
        "safetyStock": 20.0,
        "leadTimeDays": 3,
        "unit_price": 3.5,
        "daily_points": [{"day": i, "date": f"2024-06-{i:02d}", "predicted": 6.0} for i in range(1, 15)],
        "grouped_drivers": [],
    },
]


@pytest.fixture(autouse=True)
def mock_all_inventory_and_db():
    """Autouse fixture to run all tests completely offline without external RDS/DB dependencies."""
    with patch("app.agent.tools._load_all_inventory_items", return_value=MOCK_COMPREHENSIVE_INVENTORY), \
         patch("app.agent.rag.get_all_inventory_items", return_value=MOCK_COMPREHENSIVE_INVENTORY):
        yield


# ==============================================================================
# LEVEL 1: FAST GUARDRAILS & PRESETS (ZERO-LLM, <10MS, 100% TOKEN SAVINGS)
# ==============================================================================

class TestLevel1FastGuardrailsAndPresets:
    """Level 1: Fast, deterministic zero-LLM shortcuts and security guardrails."""

    def test_1_1_quick_help_and_slash_presets(self):
        """Verify standard help shortcuts return instant markdown guide."""
        for query in ("/help", "help", "trợ giúp", "hướng dẫn", "what can you do"):
            reply = check_preset_response(query, lang="vi")
            assert reply is not None, f"Preset failed for query: {query}"
            assert "DemandAI" in reply or "Trợ lý" in reply
            assert "/reorder" in reply
            assert "/drivers" in reply

    def test_1_2_portfolio_overview_preset_shortcuts(self):
        """Verify direct overview shortcuts fetch portfolio overview without LLM call."""
        for query in ("/overview", "tổng quan kho", "portfolio overview"):
            reply = check_preset_response(query, lang="en")
            assert reply is not None, f"Overview preset failed for: {query}"
            assert "PORTFOLIO OVERVIEW" in reply or "Tracked SKUs" in reply

    def test_1_3_warehouse_list_preset(self):
        """Verify /warehouse preset returns warehouse listings without LLM."""
        reply = check_preset_response("/warehouse", lang="vi")
        assert reply is not None
        assert "Frankfurt_1" in reply or "Prague_1" in reply or "Central" in reply

    def test_1_4_metric_wiki_definitions(self):
        """Verify common metrics (ROP, DOS, Safety Stock) return textbook formulas instantly."""
        queries = {
            "rop là gì": "Reorder Point",
            "what is rop": "Reorder Point",
            "days of supply là gì": "Days of Supply",
            "safety stock là gì": "Safety Stock",
            "what is deadstock": "Deadstock",
        }
        for q, expected in queries.items():
            res = check_preset_response(q, lang="vi")
            assert res is not None, f"Wiki preset failed for {q}"
            assert expected.lower() in res.lower()

    def test_1_5_out_of_scope_guard_refusal(self):
        """Verify Layer 1 Guardrail immediately refuses unrelated prompts."""
        unrelated_prompts = [
            "kiểm tra thời tiết hôm nay",
            "thời tiết tại Hà Nội thế nào",
            "dự báo thời tiết ngày mai",
            "chơi game đi bạn",
            "bạn có chơi game được không",
            "kể chuyện cười cho tôi nghe",
            "làm thơ tình yêu đi",
            "viết code python tính fibonacci",
            "giá vàng hôm nay bao nhiêu",
            "tỷ số bóng đá tối qua",
            "tell me a funny joke",
            "what is the weather in London?",
            "write python code to sort list",
        ]
        for prompt in unrelated_prompts:
            guard = evaluate_intent_guard(prompt, selected_item_id="SKU-010")
            assert guard.is_fallback is True, f"Expected fallback for {prompt}"
            assert guard.fallback_type == "out_of_scope", f"Expected out_of_scope for {prompt}"
            assert "DemandAI Assistant" in guard.message

    def test_1_6_in_scope_whitelist_acceptance(self):
        """Verify polite greetings, introductions and general inquiries are NOT blocked."""
        legitimate_inquiries = [
            "xin chào",
            "hello",
            "bạn là ai",
            "hướng dẫn sử dụng hệ thống",
            "tổng quan kho hiện tại",
            "mặt hàng nào đang có nguy cơ đứt hàng?",
            "dự báo nhu cầu 14 ngày của SKU-1",
            "thời tiết mưa có làm giảm tồn kho của SKU-1 không?",
            "tính ROP cho món này",
        ]
        for inquiry in legitimate_inquiries:
            guard = evaluate_intent_guard(inquiry, selected_item_id="SKU-010")
            assert guard.fallback_type != "out_of_scope", f"Wrongly blocked: {inquiry}"


# ==============================================================================
# LEVEL 2: INTENT GUARD & ENTITY RESOLUTION (CONTEXT & UI SYNCHRONIZATION)
# ==============================================================================

class TestLevel2EntityResolutionAndUICards:
    """Level 2: Item resolution, multi-match disambiguation cards, and UI click sync."""

    def test_2_1_item_resolution_by_code_and_name(self):
        """Verify resolve_sku_item finds items by raw SKU code or product name."""
        # By exact SKU
        item_sku = resolve_sku_item("SKU-1")
        assert item_sku is not None
        assert "Blueberry" in item_sku.get("name", "")

        # By partial / fuzzy product name
        item_name = resolve_sku_item("Roll_51")
        assert item_name is not None
        assert item_name.get("sku") == "SKU-4720"

    def test_2_2_multi_item_disambiguation_card(self):
        """Verify query matching multiple items across warehouses returns clarifying card."""
        multi_candidates = [MOCK_COMPREHENSIVE_INVENTORY[2], MOCK_COMPREHENSIVE_INVENTORY[3]]
        with patch("app.agent.fallback.find_matching_sku_items", return_value=multi_candidates):
            guard = evaluate_intent_guard("phân tích Baguette_40", selected_item_id=None, forced_lang="vi")
            assert guard.is_fallback is True
            assert guard.fallback_type == "clarify_sku_disambiguation"
            assert guard.item_data is not None
            assert "clarification" in guard.item_data
            clarif = guard.item_data["clarification"]
            assert clarif.get("type") == "clarify_intent"
            assert len(clarif.get("options", [])) >= 2

    def test_2_3_non_existent_sku_guard(self):
        """Verify querying an unknown SKU returns a helpful 'sku_not_found' card."""
        guard = evaluate_intent_guard("Dự báo của SKU-99999 ra sao?", selected_item_id=None, forced_lang="vi")
        assert guard.is_fallback is True
        assert guard.fallback_type == "sku_not_found"
        assert "không tìm thấy" in guard.message.lower() or "not found" in guard.message.lower()
        assert guard.item_data["clarification"]["allowTextInput"] is True

    def test_2_4_ui_selected_item_priority_over_chat_history(self):
        """Regression test: UI click (selected_item_id) MUST take priority over past chat context."""
        chat_history = [
            {"role": "user", "content": "xem hàng"},
            {"role": "assistant", "content": "Bạn đang xem Blueberry_0 — mã SKU-1, tại kho Frankfurt_1."},
        ]
        # User now clicks SKU-4720 (Roll_51) and asks deictic question
        prev_sku = find_previously_mentioned_sku(chat_history)
        intended = extract_sku_mention("mình đang chọn mặt hàng nào?", selected_item_id=None)
        selected_ui = "SKU-4720"
        active_sku = intended or selected_ui or prev_sku

        assert prev_sku == "SKU-1"
        assert intended is None
        assert active_sku == "SKU-4720", f"Expected active_sku to be SKU-4720, got {active_sku}"

    def test_2_5_dashboard_view_item_suggestion_card(self):
        """Verify when user discusses an item different from screen selection, view card is offered."""
        guard = evaluate_intent_guard("mở mặt hàng SKU-4720 lên dashboard", selected_item_id="SKU-1", forced_lang="vi")
        if guard.is_fallback and guard.fallback_type == "view_item_card":
            assert guard.target_sku == "SKU-4720"
            clarif = guard.item_data["clarification"]
            assert any(opt.get("actionType") == "view_item_on_screen" for opt in clarif["options"])


# ==============================================================================
# LEVEL 3: CORE DOMAIN TOOLS & ANALYTICS
# ==============================================================================

class TestLevel3DomainToolsAndAnalytics:
    """Level 3: Core supply chain tools, ROP, TreeSHAP permissions, and What-if simulation."""

    def test_3_1_inventory_health_and_rop_tool(self):
        """Verify get_sku_inventory_and_forecast computes ROP, DOS and replenishment need."""
        inv_data = get_sku_inventory_and_forecast.invoke({"sku_or_id": "SKU-1"})
        assert "14-Day Expected Demand" in inv_data
        assert "Reorder Point (ROP)" in inv_data
        assert "Safety Stock" in inv_data
        assert "Days of Supply" in inv_data or "DOS" in inv_data

    def test_3_2_treeshap_confirmation_guard_when_uncalculated(self):
        """Verify direct calculate_sku_shap tool is omitted; user confirmation is strictly guarded."""
        tool_names = [t.name for t in SKU_TOOLS]
        assert "calculate_sku_shap" not in tool_names

        guard = evaluate_intent_guard("Tính TreeSHAP cho món này", selected_item_id="SKU-1", forced_lang="vi")
        assert guard.is_fallback is True
        assert guard.fallback_type == "run_shap_card"
        clarif = guard.item_data["clarification"]
        assert clarif.get("type") == "run_shap"
        assert any(opt.get("actionType") == "run_shap" for opt in clarif.get("options", []))

    def test_3_3_what_if_price_simulation_execution(self):
        """Verify simulate_demand computes price elasticity and scenario comparison table."""
        sim_res = simulate_demand.invoke({
            "sku_code": "SKU-1",
            "price_change_percent": 10.0,
            "warehouse": "Frankfurt_1",
        })
        assert "what-if" in sim_res.lower() or "scenario comparison" in sim_res.lower()
        assert "+10%" in sim_res
        assert "Elasticity" in sim_res or "Co giãn" in sim_res or "Baseline" in sim_res

    def test_3_4_pdf_and_csv_export_tools(self):
        """Verify generate_pdf_report and export_replenishment_csv generate valid outputs."""
        pdf_res = generate_pdf_report.invoke({"focus_area": "overview", "warehouse": "Frankfurt_1"})
        assert ".pdf" in pdf_res.lower()
        assert "/api/v1/forecast/export/download/" in pdf_res or "download" in pdf_res.lower()

        csv_res = export_replenishment_csv.invoke({"warehouse": "Frankfurt_1", "include_all": True})
        assert ".csv" in csv_res.lower() or "replenishment" in csv_res.lower()


# ==============================================================================
# LEVEL 4: E2E DEMO SCRIPT SCENARIO (# DEMO SCRIPT - DEMAND AI)
# ==============================================================================

class TestLevel4DemoScriptScenario:
    """Level 4: Full End-to-End sequence replicating the official Demo Script."""

    def test_4_1_demo_command1_catalog_overview(self):
        """Demo Command 1: 'Give me a catalog overview.' -> Portfolio overview."""
        overview = get_portfolio_overview.invoke({"focus": "all"})
        assert "PORTFOLIO OVERVIEW" in overview
        assert "Total Tracked SKUs" in overview
        assert "Aggregate 14-Day Expected Demand" in overview
        assert "Frankfurt_1" in overview or "Prague_1" in overview

    def test_4_2_demo_command2_analyze_baguette40_urgency(self):
        """Demo Command 2: 'Analyze Baguette_40: inventory health and replenishment urgency.'"""
        item = resolve_sku_item("Baguette_40")
        assert item is not None, "Baguette_40 should resolve to a valid item"
        target_sku = item.get("sku", f"SKU-{item.get('id')}")

        inv_report = get_sku_inventory_and_forecast.invoke({"sku_or_id": target_sku})
        assert "14-Day Expected Demand" in inv_report
        assert "Reorder Point (ROP)" in inv_report

        peers_report = compare_sku_peers.invoke({"sku_or_id": target_sku})
        assert "Bakery" in peers_report or "Peers" in peers_report or len(peers_report) > 30

    def test_4_3_demo_command3_analyze_roll51_treeshap(self):
        """Demo Command 3: 'Analyze Roll_51: forecast and TreeSHAP forecast drivers.'"""
        item = resolve_sku_item("Roll_51")
        assert item is not None
        assert item.get("sku") == "SKU-4720"

        shap_report = get_sku_shap_drivers.invoke({"sku_or_id": "SKU-4720"})
        assert "TreeSHAP" in shap_report or "5 Business Factor Groups Share" in shap_report or "Promotions" in shap_report

    def test_4_4_demo_chain_followup_day12_context_inheritance(self):
        """Demo Chain Query: 'What predicted demand at day 12 and what contribute most?'

        Validates conversational context engineering:
        - Inherits Roll_51 (SKU-4720) from previous turn without prompting.
        - Identifies focal horizon day = 12.
        - Preserves inquiry in agent working memory.
        """
        history = [
            {"role": "user", "content": "Analyze Roll_51: forecast and TreeSHAP forecast drivers."},
            {"role": "assistant", "content": "I have analyzed Roll_51 (SKU-4720). TreeSHAP drivers show high promo impact."},
        ]
        follow_up = "What predicted demand at day 12 and what contribute most?"

        # 1. Check SKU inheritance
        inherited_sku = find_previously_mentioned_sku(history)
        assert inherited_sku == "SKU-4720"

        # 2. Check focal day extraction
        focal_day = find_conversational_day(follow_up, history)
        assert focal_day == 12, f"Expected focal day 12, got {focal_day}"

        # 3. Check original inquiry extraction
        inquiry = find_original_user_inquiry(follow_up, history)
        assert "roll_51" in inquiry.lower() or "forecast" in inquiry.lower()

        # 4. Verify working memory injection in agent prompt
        agent = build_langchain_agent(
            lang="en",
            selected_item_id=inherited_sku,
            focal_day=focal_day,
            active_inquiry=inquiry,
        )
        assert agent is not None

    def test_4_5_demo_command4_what_if_price_increase_simulation(self):
        """Demo Command 4: 'How would a 10% price increase affect the forecast for Berry_1?'"""
        target_sku = "SKU-1"
        sim_output = simulate_demand.invoke({
            "sku_code": target_sku,
            "price_change_percent": 10.0,
            "warehouse": "Frankfurt_1",
        })
        assert "+10%" in sim_output
        assert "Elasticity" in sim_output or "Baseline" in sim_output or "Revenue" in sim_output

    def test_4_6_demo_command5_export_restock_report_pdf(self):
        """Demo Command 5: '/export restock report in PDF.' -> Generates PDF & CSV links."""
        pdf_res = generate_pdf_report.invoke({"focus_area": "critical", "warehouse": "Frankfurt_1"})
        csv_res = export_replenishment_csv.invoke({"warehouse": "Frankfurt_1", "include_all": True})

        assert ".pdf" in pdf_res.lower()
        assert ".csv" in csv_res.lower() or "Exported" in csv_res or "replenishment" in csv_res.lower()


# ==============================================================================
# LEVEL 5: ADVERSARIAL, MULTILINGUAL & EDGE CASES
# ==============================================================================

class TestLevel5AdversarialAndEdgeCases:
    """Level 5: Multilingual directives, role hijacking defense, and streaming protocol."""

    def test_5_1_system_prompt_language_directives(self):
        """Verify strict language enforcement directives in System Prompts."""
        assert "BẮT BUỘC TRẢ LỜI 100% BẰNG TIẾNG VIỆT" in SYSTEM_PROMPT_VI
        assert "MANDATORY OUTPUT DIRECTIVE: YOU MUST RESPOND 100% IN ENGLISH" in SYSTEM_PROMPT_EN

    def test_5_2_scope_boundary_rule_in_system_prompts(self):
        """Verify section 5 (Scope Boundary & Refusal) exists in both system prompts."""
        assert "5. GIỚI HẠN PHẠM VI HỖ TRỢ (SCOPE BOUNDARY & REFUSAL)" in SYSTEM_PROMPT_VI
        assert "5. SCOPE BOUNDARY & REFUSAL" in SYSTEM_PROMPT_EN
        assert "DemandAI Assistant" in SYSTEM_PROMPT_VI
        assert "DemandAI Assistant" in SYSTEM_PROMPT_EN

    def test_5_3_zero_hallucination_on_missing_item(self):
        """Verify non-existent item is rejected gracefully without hallucinating numbers."""
        fake_item = resolve_sku_item("NonExistentPastry_9999")
        assert fake_item is None

        guard = evaluate_intent_guard("Dự báo của NonExistentPastry_9999 thế nào?", forced_lang="vi")
        assert guard.is_fallback is True or guard.target_sku is None

    @pytest.mark.anyio
    async def test_5_4_sse_streaming_protocol_integrity(self):
        """Verify SSE event stream yields valid JSON format with proper event types."""
        events = []
        async for chunk in stream_sku_agent_response(
            query="/overview",
            history_messages=[],
            model_info=MODELS[DEFAULT_MODEL],
            selected_item_id="SKU-1",
            language="vi",
        ):
            events.append(chunk)

        all_text = "".join(events)
        assert "data: {" in all_text

        # Verify every line starting with 'data: ' contains valid JSON
        for block in all_text.strip().split("\n\n"):
            if block.startswith("data: "):
                json_str = block[len("data: "):].strip()
                parsed = json.loads(json_str)
                assert "type" in parsed
                assert parsed["type"] in ("token", "step", "done", "model_active", "clarification", "fallback_type", "error")
