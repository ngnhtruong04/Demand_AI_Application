"""backend/tests/test_agent_think.py
Comprehensive test suite verifying the Agent's Think block behavior:
1. Non-spoiling context-aware think text (no premature SKU disclosure on deictic queries).
2. Language auto-detection without English bleed.
3. Clean dynamic status without raw truncated quote artifacts.
4. Clean reasoning separation with double newline.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.agent.language import detect_language
from app.agent.sku_agent import build_initial_think, stream_sku_agent_response, MODELS, DEFAULT_MODEL


# ==============================================================================
# 1. UNIT TESTS: build_initial_think
# ==============================================================================

class TestBuildInitialThink:
    """Validate build_initial_think returns appropriate, non-confusing think messages."""

    @pytest.mark.parametrize(
        "query",
        [
            "tôi đang chọn mặt hàng nào?",
            "tôi đang xem sku nào?",
            "mặt hàng hiện tại là gì?",
            "đây là sản phẩm gì?",
            "chọn mặt hàng nào vậy?",
        ],
    )
    def test_deictic_active_item_inquiry_vietnamese(self, query: str):
        """On Vietnamese deictic questions, think text MUST NOT spoil the active SKU."""
        think = build_initial_think(
            query=query,
            intended_sku=None,
            active_sku="SKU-5295",
            lang="vi",
        )
        assert think == "Đang kiểm tra thông tin mặt hàng hiện tại trên không gian làm việc..."
        assert "SKU-5295" not in think
        assert "checking relevant tools" not in think.lower()

    @pytest.mark.parametrize(
        "query",
        [
            "which item am I selecting?",
            "what item is currently selected?",
            "what sku am I looking at?",
            "which item is active?",
        ],
    )
    def test_deictic_active_item_inquiry_english(self, query: str):
        """On English deictic questions, think text MUST NOT spoil the active SKU."""
        think = build_initial_think(
            query=query,
            intended_sku=None,
            active_sku="SKU-5295",
            lang="en",
        )
        assert think == "Checking current active item details on the workspace..."
        assert "SKU-5295" not in think

    def test_explicit_sku_query(self):
        """When user explicitly specifies SKU, think text appropriately acknowledges it."""
        think_vi = build_initial_think(
            query="Dự báo 14 ngày tới cho SKU-10",
            intended_sku="SKU-10",
            active_sku="SKU-10",
            lang="vi",
        )
        assert "SKU-10" in think_vi
        assert "Đang đối chiếu dữ liệu và công cụ phân tích cho SKU-10..." in think_vi

        think_en = build_initial_think(
            query="14-day forecast for SKU-10",
            intended_sku="SKU-10",
            active_sku="SKU-10",
            lang="en",
        )
        assert "SKU-10" in think_en
        assert "Analyzing data and analytical tools for SKU-10..." in think_en

    def test_contextual_active_sku_analytical_query(self):
        """When query is domain-specific (forecast, stockout) referencing active item."""
        think_vi = build_initial_think(
            query="Mặt hàng này có nguy cơ đứt hàng không?",
            intended_sku=None,
            active_sku="SKU-5295",
            lang="vi",
        )
        assert "SKU-5295" in think_vi
        assert "Đang tổng hợp thông tin phân tích cho SKU-5295..." in think_vi

        think_en = build_initial_think(
            query="Is there any stockout risk for this item?",
            intended_sku=None,
            active_sku="SKU-5295",
            lang="en",
        )
        assert "SKU-5295" in think_en
        assert "Gathering analytical insights for SKU-5295..." in think_en

    @pytest.mark.parametrize(
        "query,lang,expected",
        [
            ("tồn kho an toàn là gì?", "vi", "Đang phân tích câu hỏi và chuẩn bị câu trả lời..."),
            ("bạn có thể làm gì?", "vi", "Đang phân tích câu hỏi và chuẩn bị câu trả lời..."),
            ("hướng dẫn tôi sử dụng hệ thống", "vi", "Đang phân tích câu hỏi và chuẩn bị câu trả lời..."),
            ("what is safety stock?", "en", "Analyzing inquiry and preparing response..."),
            ("how do I use DemandAI?", "en", "Analyzing inquiry and preparing response..."),
        ],
    )
    def test_general_conceptual_inquiries(self, query: str, lang: str, expected: str):
        """General questions must never mention active SKU or claim checking tools."""
        think = build_initial_think(
            query=query,
            intended_sku=None,
            active_sku="SKU-5295",
            lang=lang,
        )
        assert think == expected
        assert "SKU-5295" not in think
        assert "tools" not in think.lower()


# ==============================================================================
# 2. LANGUAGE RESOLUTION TESTS
# ==============================================================================

class TestLanguageResolution:
    """Verify that language selection avoids English bleed on Vietnamese queries."""

    def test_vietnamese_query_with_default_english_ui(self):
        """Even if frontend defaults to language='en', Vietnamese query must detect 'vi'."""
        assert detect_language("tôi đang chọn mặt hàng nào?", default="en") == "vi"
        assert detect_language("dự báo tồn kho 14 ngày tới", default="en") == "vi"

    def test_english_query_with_default_vietnamese_ui(self):
        """English query detects 'en' even if UI default is 'vi'."""
        assert detect_language("which item am I selecting?", default="vi") == "en"
        assert detect_language("what is the stockout risk for SKU-1?", default="vi") == "en"

    def test_neutral_codes_respect_default_language(self):
        """Neutral codes (pure SKU, bare slash commands) respect UI default."""
        assert detect_language("SKU-5295", default="vi") == "vi"
        assert detect_language("SKU-5295", default="en") == "en"
        assert detect_language("/drivers", default="vi") == "vi"
        assert detect_language("/drivers", default="en") == "en"


# ==============================================================================
# 3. END-TO-END STREAMING THINK STEP TESTS
# ==============================================================================

@pytest.mark.anyio
class TestStreamSkuAgentThinkEvent:
    """Verify stream_sku_agent_response SSE output for think events."""

    async def test_stream_think_event_for_deictic_query(self):
        """SSE stream for 'tôi đang chọn mặt hàng nào?' must emit clean Vietnamese think step."""
        mock_agent = MagicMock()

        async def fake_astream_events(*args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": MagicMock(content="Bạn đang chọn mặt hàng SKU-5295.", additional_kwargs={})},
            }

        mock_agent.astream_events = fake_astream_events

        with patch("app.agent.sku_agent.build_langchain_agent", return_value=mock_agent), \
             patch("app.agent.sku_agent.get_llm_api_key", return_value="dummy-key"):

            events: list[dict] = []
            async for sse in stream_sku_agent_response(
                query="tôi đang chọn mặt hàng nào?",
                history_messages=[],
                model_info=MODELS[DEFAULT_MODEL],
                selected_item_id="SKU-5295",
                language="en",  # Client initially sends "en" as default
            ):
                if sse.startswith("data: "):
                    events.append(json.loads(sse[6:].strip()))

            think_events = [e for e in events if e.get("type") == "step" and e.get("step_type") == "think"]
            assert len(think_events) >= 1

            initial_think_content = think_events[0]["content"]
            # Must be Vietnamese
            assert "Đang kiểm tra thông tin mặt hàng hiện tại" in initial_think_content
            # Must NOT spoil SKU-5295
            assert "SKU-5295" not in initial_think_content
            # Must NOT have raw quotes with query slice
            assert "Analyzing '" not in initial_think_content
            assert "'tôi đang chọn" not in initial_think_content

    async def test_stream_reasoning_token_separation(self):
        """When LLM streams reasoning tokens, they should be cleanly separated with double newline."""
        mock_agent = MagicMock()

        async def fake_astream_events(*args, **kwargs):
            # Model emits reasoning_content
            yield {
                "event": "on_chat_model_stream",
                "data": {
                    "chunk": MagicMock(
                        content="",
                        additional_kwargs={"reasoning_content": "User wants to know current SKU."},
                    )
                },
            }
            # Next chunk of reasoning
            yield {
                "event": "on_chat_model_stream",
                "data": {
                    "chunk": MagicMock(
                        content="",
                        additional_kwargs={"reasoning_content": " Selected item in context is SKU-5295."},
                    )
                },
            }
            # Model emits final content
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": MagicMock(content="Mặt hàng hiện tại là SKU-5295.", additional_kwargs={})},
            }

        mock_agent.astream_events = fake_astream_events

        with patch("app.agent.sku_agent.build_langchain_agent", return_value=mock_agent), \
             patch("app.agent.sku_agent.get_llm_api_key", return_value="dummy-key"):

            events: list[dict] = []
            async for sse in stream_sku_agent_response(
                query="tôi đang chọn mặt hàng nào?",
                history_messages=[],
                model_info=MODELS[DEFAULT_MODEL],
                selected_item_id="SKU-5295",
                language="vi",
            ):
                if sse.startswith("data: "):
                    events.append(json.loads(sse[6:].strip()))

            think_events = [e for e in events if e.get("type") == "step" and e.get("step_type") == "think"]
            assert len(think_events) == 3

            # 1st think: initial_think
            assert "Đang kiểm tra" in think_events[0]["content"]

            # 2nd think: first reasoning chunk must start with \n\n to cleanly separate
            assert think_events[1]["content"].startswith("\n\nUser wants")

            # 3rd think: subsequent reasoning chunk continues normally without extra \n\n
            assert think_events[2]["content"].startswith(" Selected item")
