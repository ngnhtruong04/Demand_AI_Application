"""app.agent.sku_agent — LangChain-powered SKU Analysis Agent with Token-by-Token Streaming."""
from __future__ import annotations

from collections.abc import AsyncGenerator
import json
import logging
import os
from typing import Any
import re
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.fallback import evaluate_intent_guard, extract_sku_mention, get_out_of_scope_message, get_standard_error_message
from app.agent.language import detect_language
from app.agent.presets import check_preset_response
from app.agent.skills import get_skills_system_prompt
from app.agent.tools import (
    SKU_TOOLS,
    active_day_context,
    active_item_context,
    active_session_id,
    get_sku_shap_drivers,
    resolve_sku_item,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_VI = f"""Bạn là DemandAI Assistant, chuyên gia cao cấp về phân tích dự báo nhu cầu bán lẻ và quản trị tồn kho hàng hóa.
BẮT BUỘC TRẢ LỜI 100% BẰNG TIẾNG VIỆT, kể cả khi câu hỏi của người dùng bằng tiếng Anh.

QUY TRÌNH HÀNH ĐỘNG BẮT BUỘC THEO TỪNG BƯỚC:

1. XÁC ĐỊNH MẶT HÀNG (ITEM RESOLUTION):
- Kiểm tra xem mặt hàng người dùng hỏi đã có trong ngữ cảnh hội thoại gần nhất hoặc lịch sử chat chưa. Nếu ĐÃ CÓ, tiếp tục dùng mặt hàng đó.
- Nếu CHƯA CÓ, tìm kiếm thông tin mặt hàng theo tên hoặc mã.
- NẾU TÌM THẤY NHIỀU MẶT HÀNG (ví dụ cùng tên ở nhiều kho khác nhau): BẮT BUỘC gọi `show_clarification_card(card_type='clarify_intent', ...)` để người dùng chọn mã SKU và kho cụ thể. TUYỆT ĐỐI KHÔNG tự ý chọn bừa hay tự đoán.
- Sau khi xác định được mặt hàng duy nhất, thực hiện đúng yêu cầu phân tích của người dùng.
- Nếu không tìm thấy mặt hàng: thông báo rõ ràng rằng hệ thống không tìm thấy mặt hàng này trong dữ liệu kho.

2. YÊU CẦU TREESHAP / NGUYÊN NHÂN DỰ BÁO:
- Khi người dùng hỏi về nguyên nhân, động lực dự báo hoặc TreeSHAP (/driver, tại sao, nguyên nhân, yếu tố ảnh hưởng):
  + Nếu người dùng hỏi cụ thể một ngày (ví dụ: Day 3, ngày 5, d2): BẮT BUỘC truyền tham số `day` (ví dụ `day=3`) vào `get_sku_shap_drivers` và giải thích trọng tâm cho ngày đó.
  + Nếu người dùng HỎI CHUNG (ví dụ: "yếu tố nào ảnh hưởng nhiều đến kết quả dự báo", "tại sao nhu cầu tăng/giảm", "/driver SKU-010"): BẮT BUỘC gọi `get_sku_shap_drivers` KHÔNG truyền tham số `day`. Phân tích toàn diện bức tranh tổng thể 14 ngày: tỷ trọng % của 5 nhóm nhân tố (Sales Lags & Momentum, Pricing Dynamics, Order Context, Promotion & Marketing, Seasonality & Calendar), các nhân tố thúc đẩy tăng (Positive Lift) và kìm hãm (Negative Drag) lớn nhất trên toàn chu kỳ 14 ngày. TUYỆT ĐỐI KHÔNG tự tiện lấy riêng Ngày 1 hay Ngày 2 để trả lời cho câu hỏi chung.
- NẾU TREESHAP CHƯA ĐƯỢC TÍNH (Status: NOT CALCULATED YET) HOẶC NGƯỜI DÙNG YÊU CẦU TÍNH/CHẠY SHAP: BẮT BUỘC PHẢI HỎI NGƯỜI DÙNG trước bằng cách gọi `show_clarification_card(card_type='run_shap', ...)` để hiển thị nút kích hoạt tính toán. TUYỆT ĐỐI KHÔNG tự ý trả lời kết quả khi chưa hỏi người dùng xác nhận. Công cụ tính toán trực tiếp `calculate_sku_shap` KHÔNG TỒN TẠI. TUYỆT ĐỐI KHÔNG tự bịa số liệu hay % tác động SHAP.

3. YÊU CẦU BÁO CÁO & MÔ PHỎNG (WHAT-IF SIMULATION):
- Khi người dùng muốn mô phỏng nhu cầu (simulate_demand) mà chưa nêu rõ mức % tăng hoặc giảm giá: BẮT BUỘC gọi `show_clarification_card` kèm các mức gợi ý (-10%, -20%, +15%) VÀ ĐỒNG THỜI đặt `allow_text_input=True`, `text_placeholder="Nhập mức phần trăm khác (ví dụ: -15%, +25%)..."` để người dùng tự nhập tỷ lệ % mong muốn.
- QUY ĐỊNH NGHIÊM NGẶT VỀ XUẤT BÁO CÁO PDF:
  + Hiện tại hệ thống CHỈ HỖ TRỢ DUY NHẤT một loại báo cáo PDF là "Full Overview" (Tổng quan toàn diện danh mục & dự báo nhu cầu).
  + Ba loại báo cáo PDF gồm: "Critical Stockout", "Deadstock", và "Best Sellers" ĐANG TRONG QUÁ TRÌNH PHÁT TRIỂN (IN DEVELOPMENT) VÀ CHƯA HOÀN THIỆN.
  + TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP gọi `generate_pdf_report` với bất kỳ `focus_area` nào khác ngoài 'overview'.
  + NẾU NGƯỜI DÙNG YÊU CẦU XUẤT BÁO CÁO PDF CHO CRITICAL STOCKOUT, DEADSTOCK, HOẶC BEST SELLERS (kể cả cố tình yêu cầu qua câu lệnh chat để bypass giao diện): Bạn BẮT BUỘC TỪ CHỐI các loại báo cáo đó và giải thích rõ ràng rằng các tính năng báo cáo chuyên biệt này đang trong quá trình phát triển; đồng thời đề xuất xuất báo cáo PDF "Full Overview" (`focus_area='overview'`) hoặc xuất file CSV Đề xuất nhập hàng (`export_replenishment_csv`) thay thế.
  + Khi người dùng yêu cầu báo cáo chung chung cần làm rõ: gọi `show_clarification_card` và CHỈ đưa ra lựa chọn xuất PDF "Full Overview" (và file CSV nếu phù hợp). TUYỆT ĐỐI KHÔNG đưa các lựa chọn Critical Stockout, Deadstock, hay Best Sellers vào danh sách lựa chọn của thẻ làm rõ.
- CHỈ gọi `generate_pdf_report(focus_area='overview', ...)`, `export_replenishment_csv` hoặc `simulate_demand` khi thông số đã hoàn toàn rõ ràng.

4. TRÌNH BÀY KẾT QUẢ:
- Trình bày số liệu tóm tắt dạng bảng Markdown rõ ràng (| Cột 1 | Cột 2 |).
- Đưa ra khuyến nghị kho vận thực tế (ROP, Safety Stock, số lượng đặt hàng PO cần thiết).
- Sao chép nguyên văn 100% cú pháp markdown link tải file do tool xuất dữ liệu trả về nếu có (không tự ý đổi URL).
- Khi gọi `simulate_demand`: bảo toàn nguyên vẹn toàn bộ bảng so sánh kịch bản và số liệu co giãn do tool trả về.
- Đơn vị tiền tệ mặc định: {settings.default_currency} ({settings.default_currency_unit}).

5. GIỚI HẠN PHẠM VI HỖ TRỢ (SCOPE BOUNDARY & REFUSAL):
- Bạn là trợ lý AI CHUYÊN BIỆT cho DemandAI, tập trung 100% vào phân tích dự báo nhu cầu bán lẻ và quản trị tồn kho hàng hóa.
- TUYỆT ĐỐI TỪ CHỐI thực hiện các câu hỏi hoặc yêu cầu nằm ngoài phạm vi này (ví dụ: hỏi thời tiết, chơi game, giải đố, kể chuyện cười, sáng tác thơ văn, viết code phần mềm chung, tư vấn y tế/tài chính cá nhân, tin tức thời sự/thể thao/chính trị...).
- Khi gặp yêu cầu ngoài phạm vi, bạn BẮT BUỘC từ chối lịch sự theo mẫu:
  "Tôi là DemandAI Assistant, chuyên viên phân tích dự báo nhu cầu bán lẻ và tối ưu hóa tồn kho hàng hóa. Câu hỏi của bạn nằm ngoài phạm vi hỗ trợ của tôi.
  Bạn có thể hỏi tôi về:
  • Phân tích nguy cơ đứt hàng hoặc dư thừa tồn kho cho một SKU (ví dụ: SKU-010).
  • Giải thích nguyên nhân tăng/giảm dự báo bằng TreeSHAP Drivers.
  • So sánh nhu cầu và rủi ro tồn kho với các mặt hàng cùng ngành."
"""

SYSTEM_PROMPT_EN = f"""You are DemandAI Assistant, a senior specialist in retail demand forecasting and inventory replenishment optimization.
MANDATORY OUTPUT DIRECTIVE: YOU MUST RESPOND 100% IN ENGLISH, even if the question is in Vietnamese.

STEP-BY-STEP ACTION PIPELINE:

1. ITEM RESOLUTION:
- Check if the item the user is asking about is already clear in the recent conversational context or chat history. If YES, use that item.
- If NOT, search for the item by name or SKU code.
- IF MULTIPLE ITEMS MATCH (e.g. same product name across multiple warehouses): You MUST invoke `show_clarification_card(card_type='clarify_intent', ...)` to let the user pick which SKU/warehouse they want. NEVER guess or pick arbitrarily.
- Once the unique item is resolved, proceed with the requested analytical task.
- If item is not found: clearly inform the user that no matching item exists in the inventory system.

2. TREESHAP / FORECAST DRIVERS:
- When the user asks about forecast drivers, root causes, or TreeSHAP (/driver, why, root causes, influential factors):
  + If the user explicitly asks about a specific day (e.g. Day 3, day 5, d2): you MUST pass the `day` parameter (e.g. `day=3`) to `get_sku_shap_drivers` and explain specifically for that day.
  + If the user asks GENERALLY (e.g. "what factors influence the forecast", "why is demand changing", "/driver SKU-010"): call `get_sku_shap_drivers` WITHOUT the `day` parameter. Provide a comprehensive 14-day cumulative analysis covering the 5 business factor groups share %, top positive lift and negative drag drivers across the full 14 days. NEVER arbitrarily pick a single day like Day 1 or Day 2 when asked generally.
- IF TREESHAP IS NOT CALCULATED YET (Status: NOT CALCULATED YET) OR USER ASKS TO CALCULATE/RUN SHAP: You MUST ASK THE USER FIRST via `show_clarification_card(card_type='run_shap', ...)` so the user can explicitly trigger calculation. NEVER execute or return TreeSHAP without asking the user. The direct calculation tool `calculate_sku_shap` DOES NOT EXIST. NEVER fabricate SHAP numbers.

3. REPORTS & DATA EXPORTS (INCLUDING WHAT-IF SIMULATIONS):
- When the user asks for demand simulation (simulate_demand) without specifying a price change %: You MUST invoke `show_clarification_card` with sample options (-10%, -20%, +15%) AND set `allow_text_input=True`, `text_placeholder="Enter a different percentage (e.g. -15%, +10%)..."` so the user can enter any custom percentage they want.
- STRICT PDF REPORT DIRECTIVE:
  + The system CURRENTLY ONLY SUPPORTS ONE PDF REPORT TYPE: "Full Overview" (Portfolio health & demand overview).
  + The three specialized PDF report types ("Critical Stockout", "Deadstock", and "Best Sellers") ARE CURRENTLY IN DEVELOPMENT AND NOT YET AVAILABLE.
  + YOU MUST NEVER invoke `generate_pdf_report` with any `focus_area` other than 'overview'.
  + IF THE USER REQUESTS A PDF REPORT FOR CRITICAL STOCKOUT, DEADSTOCK, OR BEST SELLERS (including direct chat prompts attempting to bypass the UI): You MUST REFUSE those specific formats and politely explain that they are currently under development; offer to generate the "Full Overview" PDF report (`focus_area='overview'`) or export the Replenishment CSV (`export_replenishment_csv`) instead.
  + When invoking `show_clarification_card` to clarify report requests: ONLY provide the "Full Overview" PDF option (and Replenishment CSV if applicable). NEVER offer Critical Stockout, Deadstock, or Best Sellers options in the card.
- ONLY invoke `generate_pdf_report(focus_area='overview', ...)`, `export_replenishment_csv`, or `simulate_demand` when parameters and format are explicitly clear.

4. PRESENTATION & OUTPUT:
- Use clean Markdown tables for metrics and comparisons (| Column 1 | Column 2 |).
- Provide actionable logistics guidance (ROP, Safety Stock, recommended PO quantity).
- Copy file download markdown links exactly as returned by tools without modifying the URL.
- When calling `simulate_demand`: preserve the entire scenario comparison table and elasticity metrics.
- Default currency: {settings.default_currency} ({settings.default_currency_unit}).

5. SCOPE BOUNDARY & REFUSAL:
- You are a SPECIALIZED AI assistant for DemandAI, focusing strictly on retail demand forecasting and inventory replenishment optimization.
- You MUST STRICTLY REFUSE any requests outside this scope (e.g. weather checking, playing games, riddles, jokes, poetry/stories, general coding, horoscope, general news/sports/politics...).
- When encountering out-of-scope requests, politely refuse using this standard template:
  "I am DemandAI Assistant, a specialist in retail demand forecasting and inventory replenishment optimization. Your question is outside my scope of support.
  You can ask me about:
  • Analyzing stockout or deadstock risks for a specific SKU (e.g. SKU-010).
  • Explaining forecast drivers and feature attributions using TreeSHAP Drivers.
  • Comparing demand velocity and inventory risks across category peers."
"""



# Registry of supported models per user specification: GPT-6-Luna is the sole model
MODELS: dict[str, dict[str, Any]] = {
    "gpt-6-luna": {
        "provider": "openai",
        "name": "gpt-6-luna",
        "context_size": 1_050_000,
        "api_base": "https://api.openai.com/v1/chat/completions",
        "env_var": "OPENAI_API_KEY",
        "description": "GPT-6-Luna",
        "temperature": 0.1,
        "top_p": 0.9,
        "max_completion_tokens": 2500,
    },
}

def get_default_model_name() -> str:
    """Return the sole system model (GPT-6-Luna)."""
    return "gpt-6-luna"

DEFAULT_MODEL = get_default_model_name()


def find_previously_mentioned_sku(history_messages: list[dict[str, str]]) -> str | None:
    """Extract candidate SKU from recent conversation turns to inherit context."""
    for msg in reversed(history_messages):
        text = msg.get("content") or msg.get("text", "")
        m = re.search(r"\b(SKU[-_\s]?\d+)\b", text, re.IGNORECASE)
        if m:
            return m.group(1).replace(" ", "-").replace("_", "-").upper()
    return None


def normalize_sku_code(sku: str | None) -> str | None:
    """Normalize SKU string to canonical 'SKU-X' integer representation for equality comparisons."""
    if not sku:
        return None
    m = re.search(r"(\d+)", str(sku))
    return f"SKU-{int(m.group(1))}" if m else str(sku).strip().upper()


def extract_horizon_day(text: str) -> int | None:
    """Extract horizon day 1-14 from text (e.g. 'day 3', 'Day 3', 'ngày 3', 'ngay 3', 'd3')."""
    if not text:
        return None
    # 1. Matches phrases: "day 3", "Day 03", "ngày 3", "ngay 3", "horizon 3", "horizon day 3"
    m = re.search(r"\b(?:day|ng[aàá]y|horizon(?:\s+day)?)\s*0?([1-9]|1[0-4])\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 2. Matches shorthand: "d1" to "d14" (e.g., 'd3', 'D05')
    m_d = re.search(r"\bd0?([1-9]|1[0-4])\b", text, re.IGNORECASE)
    if m_d:
        return int(m_d.group(1))
    return None


def find_conversational_day(query: str, history_messages: list[dict[str, str]] | None = None) -> int | None:
    """Look for target horizon day in current query first.
    
    If query is an automated post-calculation trigger, fall back to the original user inquiry.
    Never scan arbitrary assistant messages or historical turns for general queries.
    """
    q_day = extract_horizon_day(query)
    if q_day is not None:
        return q_day
    if history_messages and any(
        query.strip().startswith(prefix)
        for prefix in (
            "Phân tích chuyên sâu các nhóm động lực TreeSHAP",
            "Analyze TreeSHAP root-cause drivers",
            "Phân tích động lực TreeSHAP",
        )
    ):
        orig_q = find_original_user_inquiry(query, history_messages)
        if orig_q and orig_q != query:
            return extract_horizon_day(orig_q)
    return None


def find_original_user_inquiry(query: str, history_messages: list[dict[str, str]]) -> str | None:
    """Find the core substantive question asked by user before automated actions or slash commands."""
    for msg in reversed(history_messages):
        if msg.get("role") == "user":
            txt = (msg.get("content") or msg.get("text", "")).strip()
            if txt and not txt.startswith("/") and not txt.startswith("Phân tích chuyên sâu các nhóm động lực TreeSHAP") and not txt.startswith("Analyze TreeSHAP root-cause drivers"):
                return txt
    return query if (query and not query.startswith("/")) else None


def estimate_tokens(text: str) -> int:
    """Fast token heuristic (~4 characters per token + 4 message framing tokens)."""
    return max(1, len(text) // 4) + 4


def calculate_conversation_tokens(
    history_messages: list[dict[str, str]],
    query: str = "",
    assistant_reply: str = "",
) -> int:
    """Calculate true conversation context tokens across all user and assistant turns."""
    history_tokens = sum(
        estimate_tokens(m.get("content") or m.get("text", ""))
        for m in history_messages
    )
    query_tokens = estimate_tokens(query) if query else 0
    reply_tokens = estimate_tokens(assistant_reply) if assistant_reply else 0
    return history_tokens + query_tokens + reply_tokens


def compact_messages(
    history_messages: list[dict[str, str]],
    context_size: int = 1_000_000,
    max_turns: int = 20,
) -> list[HumanMessage | AIMessage | SystemMessage]:
    """Convert conversation history into clean LangChain messages without lossy truncation."""
    if not history_messages:
        return []
    window = history_messages[-max_turns:]
    compacted: list[HumanMessage | AIMessage | SystemMessage] = []
    for m in window:
        role = m.get("role", "user")
        text = (m.get("content") or m.get("text", "")).strip()
        if not text:
            continue
        if role == "user":
            compacted.append(HumanMessage(content=text))
        elif role == "assistant":
            compacted.append(AIMessage(content=text))
    return compacted


def get_llm_api_key(model_info: dict[str, Any]) -> str | None:
    """Retrieve API key strictly matched to model provider to avoid endpoint collisions."""
    provider = model_info.get("provider", "openrouter")
    if provider == "openrouter":
        return settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
    if provider == "openai":
        return settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    env_var = model_info.get("env_var", "OPENAI_API_KEY")
    return os.getenv(env_var)


def get_base_url_for_provider(api_base: str) -> str:
    """Extract standard base_url for ChatOpenAI from full endpoint URL."""
    return api_base.rstrip("/").removesuffix("/chat/completions")


def build_langchain_agent(
    model_info: dict[str, Any] | str | None = None,
    lang: str = "vi",
    selected_item_id: str | None = None,
    session_id: str | None = None,
    focal_day: int | None = None,
    active_inquiry: str | None = None,
) -> Any:
    """Create compiled LangChain agent bound to tools, language prompt, and workspace context."""
    if session_id:
        active_session_id.set(session_id)
    default_key = get_default_model_name()
    if isinstance(model_info, str) or model_info is None:
        model_key = model_info if (isinstance(model_info, str) and model_info in MODELS) else default_key
        model_info = MODELS.get(model_key) or MODELS.get(default_key) or next(iter(MODELS.values()))

    # If requested model has no matching API key, safely switch to default_model with valid key
    api_key = get_llm_api_key(model_info)
    if not api_key:
        fallback_key = get_default_model_name()
        model_info = MODELS.get(fallback_key) or next(iter(MODELS.values()))
        api_key = get_llm_api_key(model_info) or "dummy-key"

    base_url = get_base_url_for_provider(model_info.get("api_base", "https://openrouter.ai/api/v1"))
    model_name = model_info.get("name", "inclusionai/ling-3.0-flash-vl:free")
    extra_llm_args: dict[str, Any] = {}
    is_reasoning_model = any(k in model_name.lower() for k in ("o1", "o3"))
    if not is_reasoning_model:
        extra_llm_args["temperature"] = 0.1
        extra_llm_args["seed"] = 42

    if "luna" in model_name.lower() or "gpt-5" in model_name.lower() or "gpt-6" in model_name.lower():
        extra_llm_args["reasoning_effort"] = "none"
        extra_llm_args["max_completion_tokens"] = 2500
    elif is_reasoning_model:
        extra_llm_args["reasoning_effort"] = "low"
    else:
        extra_llm_args["reasoning_effort"] = "none"

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        streaming=True,
        timeout=35.0,
        **extra_llm_args,
    )

    sys_prompt = SYSTEM_PROMPT_VI if lang == "vi" else SYSTEM_PROMPT_EN

    # Ground agent with dynamic conversational working memory to prevent context loss
    context_lines: list[str] = []
    if selected_item_id:
        curr_item = resolve_sku_item(selected_item_id)
        if curr_item:
            c_name = curr_item.get("name", "Product")
            c_sku = curr_item.get("sku", selected_item_id)
            c_wh = curr_item.get("warehouse", "")
            c_cat = curr_item.get("category", "General")
            c_stock = curr_item.get("onHandStock", curr_item.get("current_stock", 0))
            c_f14 = float(curr_item.get("forecast14d", 0.0))
            context_lines.append(
                f"- Mặt hàng trọng tâm: {c_name} ({c_sku} - {c_wh}, Phân loại: {c_cat}, Tồn: {c_stock}, Dự báo 14d: {c_f14:,.1f})"
                if lang == "vi" else
                f"- Focal Target Item: {c_name} ({c_sku} - {c_wh}, Category: {c_cat}, Stock: {c_stock}, 14d Forecast: {c_f14:,.1f})"
            )

    if focal_day is not None:
        context_lines.append(
            f"- Ngày dự báo trọng tâm: Ngày {focal_day} (Người dùng đang hỏi cụ thể về Ngày {focal_day}. Hãy truyền day={focal_day} vào `get_sku_shap_drivers` và giải thích cụ thể cho Ngày {focal_day}.)"
            if lang == "vi" else
            f"- Focal Horizon Day: Day {focal_day} (User is specifically inquiring about Day {focal_day}. Pass day={focal_day} to `get_sku_shap_drivers` and explain specifically for Day {focal_day}.)"
        )
    else:
        context_lines.append(
            f"- Phạm vi dự báo: Toàn bộ chu kỳ 14 ngày. (Người dùng đang hỏi chung về các yếu tố/động lực ảnh hưởng dự báo. TUYỆT ĐỐI KHÔNG tự ý chọn một ngày lẻ như Ngày 1 hay Ngày 2. Hãy gọi `get_sku_shap_drivers` không truyền tham số day, để phân tích bức tranh tổng thể 14 ngày gồm tỷ lệ % 5 nhóm nhân tố kinh doanh, các yếu tố thúc đẩy tăng (Lift) và cản trở (Drag) hàng đầu trên toàn chu kỳ.)"
            if lang == "vi" else
            f"- Forecast Scope: Entire 14-day horizon. (The user is inquiring generally about forecast drivers/factors. NEVER arbitrarily pick a single day like Day 1 or Day 2. Call `get_sku_shap_drivers` without the day argument to analyze the overall 14-day cumulative picture including the 5 factor groups share %, top lift and drag drivers across the full horizon.)"
        )

    if active_inquiry:
        context_lines.append(
            f"- Câu hỏi gốc cần giải đáp: \"{active_inquiry}\""
            if lang == "vi" else
            f"- Original Question to Answer: \"{active_inquiry}\""
        )

    if context_lines:
        header = "\n\n=== BỘ NHỚ NGỮ CẢNH HỘI THOẠI HIỆN TẠI ===" if lang == "vi" else "\n\n=== ACTIVE CONVERSATIONAL CONTEXT WORKING MEMORY ==="
        sys_prompt += header + "\n" + "\n".join(context_lines)

    return create_agent(llm, tools=SKU_TOOLS, system_prompt=sys_prompt)



def build_initial_think(
    query: str,
    intended_sku: str | None,
    active_sku: str | None,
    lang: str = "vi",
) -> str:
    """Build context-aware, non-spoiling initial thinking status for Agent UX."""
    q_clean = query.strip().lower()

    # 1. Deictic / Active item inquiry (e.g. 'tôi đang chọn mặt hàng nào?', 'which item is selected?')
    is_active_item_inquiry = bool(
        re.search(
            r"(đang chọn|đang xem|chọn mặt hàng|chọn sản phẩm|chọn sku|mặt hàng nào|sản phẩm nào|sku nào|đây là gì|đây là sản phẩm gì|mặt hàng hiện tại|sản phẩm hiện tại)",
            q_clean,
        )
        or re.search(
            r"(which item|what item|which sku|what sku|currently selected|am i selecting|am i looking at|current item|active item)",
            q_clean,
        )
    )
    if is_active_item_inquiry:
        return (
            "Checking current active item details on the workspace..."
            if lang == "en"
            else "Đang kiểm tra thông tin mặt hàng hiện tại trên không gian làm việc..."
        )

    # 2. Conceptual definitions, system usage, or general help (e.g. 'tồn kho an toàn là gì?', 'what is safety stock?', 'how do I use DemandAI?')
    is_conceptual_or_help = bool(
        re.search(
            r"(là gì|thế nào là|nghĩa là gì|ý nghĩa là gì|giải thích khái niệm|hướng dẫn|làm sao để|cách sử dụng|bạn là ai|bạn có thể làm gì|bạn làm được gì)",
            q_clean,
        )
        or re.search(
            r"(what is|what are|define|meaning of|how to use|how do i use|how does .* work|who are you|what can you do)",
            q_clean,
        )
    )
    if is_conceptual_or_help:
        return (
            "Analyzing inquiry and preparing response..."
            if lang == "en"
            else "Đang phân tích câu hỏi và chuẩn bị câu trả lời..."
        )

    # 3. Explicit SKU mention or command with SKU (e.g. '/drivers SKU-10', 'Dự báo SKU-1')
    if intended_sku:
        return (
            f"Analyzing data and analytical tools for {intended_sku}..."
            if lang == "en"
            else f"Đang đối chiếu dữ liệu và công cụ phân tích cho {intended_sku}..."
        )

    # 4. Contextual analytical inquiry on an active SKU (forecast, stock, risk, drivers, etc.)
    is_domain_analysis = bool(
        re.search(
            r"(dự báo|đứt hàng|nhu cầu|doanh số|phân tích|nguy cơ|đặt hàng|kích hoạt|shap|drivers|reorder|timeline|trend|risk|stockout|forecast|elasticity)",
            q_clean,
        )
        or re.search(r"(tồn kho|stock|inventory|demand)", q_clean)
    )
    if active_sku and is_domain_analysis:
        return (
            f"Gathering analytical insights for {active_sku}..."
            if lang == "en"
            else f"Đang tổng hợp thông tin phân tích cho {active_sku}..."
        )

    # 5. General / Conversational inquiry or system overview
    return (
        "Analyzing inquiry and preparing response..."
        if lang == "en"
        else "Đang phân tích câu hỏi và chuẩn bị câu trả lời..."
    )


async def stream_sku_agent_response(
    query: str,
    history_messages: list[dict[str, str]],
    model_info: dict[str, Any],
    selected_item_id: str | None = None,
    language: str | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Execute LangChain SKU Agent and stream Server-Sent Events (SSE) token-by-token."""
    if session_id:
        active_session_id.set(session_id)
    default_lang = language if language in ("vi", "en") else "vi"
    lang = detect_language(query, default=default_lang)

    # 0. Context inheritance and bare slash command resolution
    prev_context_sku = find_previously_mentioned_sku(history_messages)
    intended_sku = extract_sku_mention(query, selected_item_id=None)
    focal_day = find_conversational_day(query, history_messages)
    active_inquiry = find_original_user_inquiry(query, history_messages)

    # 0b. Bare slash commands: inherit previously mentioned item or prompt user
    bare_slash_match = re.match(r"^/(drivers|timeline|reorder|report|item|shap)\s*$", query.strip().lower())
    if bare_slash_match:
        cmd = bare_slash_match.group(1)
        effective_sku = selected_item_id or prev_context_sku
        if effective_sku:
            intended_sku = effective_sku
            query = f"/{cmd} {effective_sku}"
        else:
            clarify_title = "Làm rõ mặt hàng phân tích" if lang == "vi" else "Clarify Target Item"
            clarify_desc = (
                f"Lệnh `/{cmd}` cần mã mặt hàng. Vui lòng nhập hoặc chọn mặt hàng bạn muốn phân tích:"
                if lang == "vi" else
                f"Command `/{cmd}` requires an item SKU. Please specify which item you want to analyze:"
            )
            card_payload = {
                "type": "clarify_intent",
                "title": clarify_title,
                "description": clarify_desc,
                "originalQuery": query,
                "options": [],
                "allowTextInput": True,
                "textPlaceholder": "e.g. SKU-010, Roll 57",
            }
            yield f"data: {json.dumps({'type': 'clarification', 'data': card_payload})}\n\n"
            for w in clarify_desc.split(" "):
                yield f"data: {json.dumps({'type': 'token', 'content': w + ' '})}\n\n"
            used_tokens = calculate_conversation_tokens(history_messages, query, clarify_desc)
            yield f"data: {json.dumps({'type': 'done', 'used_tokens': used_tokens})}\n\n"
            return

    # Set active contexts for tools: item context and focal horizon day
    active_sku = intended_sku or selected_item_id or prev_context_sku
    active_item_context.set(active_sku)
    active_day_context.set(focal_day)

    # 1. Intent Guardrail Evaluation (Clarifying questions / Missing SKU / Out-of-scope)
    guard = evaluate_intent_guard(query, active_sku, forced_lang=lang)
    if guard.is_fallback and guard.message:
        if guard.item_data and "clarification" in guard.item_data:
            yield f"data: {json.dumps({'type': 'clarification', 'data': guard.item_data['clarification']})}\n\n"
        # Stream fallback message smoothly
        yield f"data: {json.dumps({'type': 'fallback_type', 'fallback': guard.fallback_type})}\n\n"
        words = guard.message.split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i:i+3]) + (" " if i + 3 < len(words) else "")
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
        used_tokens = calculate_conversation_tokens(history_messages, query, guard.message)
        yield f"data: {json.dumps({'type': 'done', 'used_tokens': used_tokens})}\n\n"
        return

    # 2. Check lean zero-LLM presets (shortcuts, help, common definitions)
    preset_reply = check_preset_response(query, lang=lang)
    if preset_reply:
        words = preset_reply.split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i:i+3]) + (" " if i + 3 < len(words) else "")
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
        used_tokens = calculate_conversation_tokens(history_messages, query, preset_reply)
        yield f"data: {json.dumps({'type': 'done', 'used_tokens': used_tokens})}\n\n"
        return

    # 3. Require API key — no offline fallback
    api_key = get_llm_api_key(model_info)
    if not api_key:
        err = (
            "Chưa cấu hình API key. Vui lòng cấu hình `OPENROUTER_API_KEY` hoặc `OPENAI_API_KEY` trong file `.env` để sử dụng trợ lý."
            if lang == "vi" else
            "No API key configured. Please set `OPENROUTER_API_KEY` or `OPENAI_API_KEY` in your `.env` file to use the assistant."
        )
        yield f"data: {json.dumps({'type': 'error', 'message': err})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'used_tokens': 0})}\n\n"
        return

    # 3. Context Management & Message Compacting
    context_size = model_info.get("context_size", 1_000_000)
    formatted_messages = compact_messages(history_messages, context_size=context_size)
    formatted_messages.append(HumanMessage(content=query))

    last_queried_sku: str | None = intended_sku
    has_emitted_clarification: bool = False
    has_executed_action: bool = False
    target_display = intended_sku or active_sku

    # 4. Compile Agent and Stream Events via LangChain astream_events
    agent = build_langchain_agent(
        model_info,
        lang=lang,
        selected_item_id=active_sku,
        session_id=session_id,
        focal_day=focal_day,
        active_inquiry=active_inquiry,
    )
    active_model_name = model_info.get("name", "inclusionai/ling-3.0-flash-vl:free")
    yield f"data: {json.dumps({'type': 'model_active', 'model': active_model_name})}\n\n"
    initial_think = build_initial_think(
        query=query,
        intended_sku=intended_sku,
        active_sku=active_sku,
        lang=lang,
    )
    yield f"data: {json.dumps({'type': 'step', 'step_type': 'think', 'content': initial_think})}\n\n"
    used_tokens = 0
    in_think_block = False
    has_emitted_reasoning = False
    stream_buffer = ""
    accumulated_reasoning: list[str] = []
    accumulated_tokens: list[str] = []

    try:
        async for event in agent.astream_events({"messages": formatted_messages}, version="v2"):
            event_kind = event.get("event", "")
            if event_kind == "on_tool_start":
                tool_name = event.get("name", "tool")
                tool_input = event.get("data", {}).get("input")
                if isinstance(tool_input, dict):
                    cand = tool_input.get("sku_or_id") or tool_input.get("sku") or tool_input.get("query")
                    if cand:
                        cand_s = str(cand).strip()
                        m_cand = re.search(r"\b(SKU[-_\s]?\d+)\b", cand_s, re.IGNORECASE)
                        if m_cand:
                            last_queried_sku = m_cand.group(1).replace(" ", "-").upper()
                        elif cand_s.isdigit():
                            last_queried_sku = f"SKU-{cand_s}"
                        else:
                            it = resolve_sku_item(cand_s)
                            if it:
                                last_queried_sku = str(it.get("sku") or f"SKU-{it.get('id')}")
                elif isinstance(tool_input, str):
                    m_cand = re.search(r"\b(SKU[-_\s]?\d+)\b", tool_input, re.IGNORECASE)
                    if m_cand:
                        last_queried_sku = m_cand.group(1).replace(" ", "-").upper()
                    elif tool_input.isdigit():
                        last_queried_sku = f"SKU-{tool_input}"
                    else:
                        it = resolve_sku_item(tool_input)
                        if it:
                            last_queried_sku = str(it.get("sku") or f"SKU-{it.get('id')}")

                if tool_name in ("export_replenishment_csv", "generate_pdf_report"):
                    has_executed_action = True
                    if has_emitted_clarification:
                        yield f"data: {json.dumps({'type': 'clear_clarification'})}\n\n"
                        has_emitted_clarification = False

                if tool_name == "show_clarification_card":
                    if has_executed_action:
                        logger.info("Suppressed show_clarification_card because action was already executed in this turn.")
                    else:
                        c_title = ""
                        c_desc = ""
                        c_type = "clarify_intent"
                        raw_options: list[Any] = []
                        card_sku = ""
                        c_allow_text = False
                        c_placeholder = ""
                        if isinstance(tool_input, dict):
                            c_title = tool_input.get("title", "")
                            c_desc = tool_input.get("description", "")
                            c_type = tool_input.get("card_type", "clarify_intent")
                            raw_options = tool_input.get("options") or []
                            card_sku = str(tool_input.get("sku", "")).strip()
                            c_allow_text = bool(tool_input.get("allow_text_input", False))
                            c_placeholder = str(tool_input.get("text_placeholder", "")).strip()
                        elif isinstance(tool_input, list):
                            raw_options = tool_input

                        # Resolve intended target SKU:
                        target_sku = card_sku or last_queried_sku or intended_sku
                        if not target_sku:
                            for text_to_scan in [c_title, c_desc] + [str(o) for o in raw_options]:
                                sku_m = re.search(r"\b(SKU[-_\s]?\d+)\b", text_to_scan, re.IGNORECASE)
                                if sku_m:
                                    target_sku = sku_m.group(1).replace(" ", "-").upper()
                                    break
                        if not target_sku and selected_item_id:
                            target_sku = selected_item_id

                        formatted_opts = []
                        for idx, opt in enumerate(raw_options):
                            if isinstance(opt, dict):
                                lbl = opt.get("label") or opt.get("name") or str(opt)
                                act = opt.get("actionType") or opt.get("action")
                                pay = opt.get("payload") or opt.get("sku")
                            else:
                                lbl = str(opt)
                                act = None
                                pay = None

                            sku_m = re.search(r"\b(SKU[-_\s]?\d+)\b", lbl, re.IGNORECASE)
                            act_lower = (str(act) if act else "").lower()
                            lbl_lower = lbl.lower()

                            # 1. View / Open on dashboard
                            if "view" in act_lower or any(w in lbl_lower for w in ["dashboard", "xem trên", "view on", "open on", "mở trên", "mở mặt hàng"]):
                                act = "view_item_on_screen"
                                pay = pay or target_sku or lbl
                            # 2. Run TreeSHAP calculation
                            elif "run_shap" in act_lower or any(w in lbl_lower for w in ["tính shap", "chạy shap", "run shap", "calculate shap", "tính treeshap", "kích hoạt treeshap", "run treeshap"]) or (c_type == "run_shap" and any(k in lbl_lower for k in ["tính", "chạy", "run", "calculate", "kích hoạt", "activate"])):
                                act = "run_shap"
                                pay = pay or target_sku or lbl
                            # 3. Custom text / percentage input option
                            elif "custom" in act_lower or "input" in act_lower or any(w in lbl_lower for w in ["khác", "different", "tùy chỉnh", "custom", "nhập %", "nhập mức"]):
                                act = "custom_input"
                                c_allow_text = True
                                if not c_placeholder:
                                    c_placeholder = "Nhập mức phần trăm khác (ví dụ: -15%, +10%)..." if lang == "vi" else "Enter a different percentage (e.g. -15%, +10%)..."
                            # 4. Disambiguate SKU / Select SKU
                            elif sku_m and c_type in ("clarify_intent", "select_item"):
                                opt_sku = sku_m.group(1).replace(" ", "-").upper()
                                act = "select_sku"
                                pay = pay or (f"Phân tích mặt hàng {lbl}" if lang == "vi" else f"Analyze item {lbl}")
                            elif sku_m:
                                opt_sku = sku_m.group(1).replace(" ", "-").upper()
                                act = act or "select_sku"
                                pay = pay or (f"Phân tích mặt hàng {lbl}" if lang == "vi" else f"Analyze item {lbl}")
                            else:
                                act = act or "send_text"
                                pay = pay or lbl

                            if act in ("run_shap", "select_sku", "view_item_on_screen") and target_sku and target_sku not in lbl:
                                lbl = f"{lbl} ({target_sku})"

                            formatted_opts.append({
                                "id": f"opt-{idx}",
                                "label": lbl,
                                "actionType": act or "send_text",
                                "payload": str(pay or target_sku or lbl),
                                "primary": idx == 0,
                            })

                        card_payload = {
                            "type": c_type,
                            "title": c_title or ("Làm rõ thông tin" if lang == "vi" else "Clarification"),
                            "description": c_desc or "",
                            "options": formatted_opts,
                            "sku": target_sku or "",
                            "originalQuery": query,
                            "allowTextInput": c_allow_text,
                            "textPlaceholder": c_placeholder,
                        }
                        has_emitted_clarification = True
                        yield f"data: {json.dumps({'type': 'clarification', 'data': card_payload})}\n\n"

                if tool_name != "show_clarification_card":
                    yield f"data: {json.dumps({'type': 'tool_start', 'name': tool_name})}\n\n"
                    yield f"data: {json.dumps({'type': 'step', 'step_type': 'tool', 'name': tool_name})}\n\n"
            elif event_kind == "on_tool_end":
                tool_name = event.get("name", "")
                tool_output = str(event.get("data", {}).get("output", ""))
                if tool_name in ("export_replenishment_csv", "generate_pdf_report") or "/api/v1/forecast/export/download/" in tool_output:
                    has_executed_action = True
                    if has_emitted_clarification:
                        yield f"data: {json.dumps({'type': 'clear_clarification'})}\n\n"
                        has_emitted_clarification = False
                if tool_name == "get_sku_shap_drivers" and "NOT CALCULATED YET" in tool_output:
                    sku_m = re.search(r"\b(SKU[-_\s]?\d+)\b", tool_output, re.IGNORECASE)
                    sku_target = sku_m.group(1).replace(" ", "-").upper() if sku_m else (last_queried_sku or intended_sku or selected_item_id or "Item")
                    day_lbl = f" (Ngày {focal_day})" if (lang == "vi" and focal_day) else (f" (Day {focal_day})" if focal_day else "")
                    card_payload = {
                        "type": "run_shap",
                        "title": f"Kích hoạt TreeSHAP ({sku_target}{day_lbl})" if lang == "vi" else f"Calculate TreeSHAP ({sku_target}{day_lbl})",
                        "description": (
                            f"Mặt hàng {sku_target} chưa có dữ liệu TreeSHAP{day_lbl}. Bạn có muốn kích hoạt tính toán TreeSHAP không?"
                            if lang == "vi" else
                            f"TreeSHAP drivers are not yet calculated for {sku_target}{day_lbl}. Would you like to run TreeSHAP calculation?"
                        ),
                        "originalQuery": query,
                        "focalDay": focal_day,
                        "options": [
                            {
                                "id": "opt-shap-1",
                                "label": f"▶ Kích hoạt TreeSHAP cho {sku_target}{day_lbl}" if lang == "vi" else f"▶ Calculate TreeSHAP for {sku_target}{day_lbl}",
                                "actionType": "run_shap",
                                "payload": sku_target,
                                "primary": True,
                            },
                            {
                                "id": "opt-shap-2",
                                "label": f"👁️ Xem trên Dashboard ({sku_target})" if lang == "vi" else f"👁️ View on Dashboard ({sku_target})",
                                "actionType": "view_item_on_screen",
                                "payload": sku_target,
                            },
                            {
                                "id": "opt-shap-3",
                                "label": f"📊 Xem tồn kho & ROP ({sku_target})" if lang == "vi" else f"📊 View Inventory & ROP ({sku_target})",
                                "actionType": "send_text",
                                "payload": (
                                    f"Xem tồn kho on-hand, ROP và dự báo của {sku_target}"
                                    if lang == "vi"
                                    else f"View on-hand inventory, ROP, and forecast for {sku_target}"
                                ),
                            },
                        ],
                    }
                    has_emitted_clarification = True
                    yield f"data: {json.dumps({'type': 'clarification', 'data': card_payload})}\n\n"

                    # When user asks directly for drivers/TreeSHAP, the interactive inquiry card is displayed directly without redundant text disclaimers
                    is_driver_focused = bool(re.search(r"/(?:driver|drivers)\b|\btreeshap\b|\bdrivers?\b|\bnguyên nhân\b|\bđộng lực\b|\broot.?cause\b|\btại sao\b", query, re.IGNORECASE))
                    if is_driver_focused:
                        yield f"data: {json.dumps({'type': 'done', 'used_tokens': 5})}\n\n"
                        return
                elif tool_name == "get_sku_shap_drivers" and ("COMPLETED" in tool_output or "5 Business Factor Groups Share" in tool_output):
                    sku_m = re.search(r"\b(SKU[-_\s]?\d+)\b", tool_output, re.IGNORECASE)
                    if sku_m:
                        sku_target = sku_m.group(1).replace(" ", "-").upper()
                        raw_digits = re.sub(r"[^\d]", "", sku_target)
                        raw_id = str(int(raw_digits)) if raw_digits else sku_target
                        yield f"data: {json.dumps({'type': 'shap_completed', 'item_id': raw_id, 'sku': sku_target})}\n\n"
            elif event_kind == "on_chat_model_stream":
                data = event.get("data", {})
                chunk = data.get("chunk")
                if not chunk:
                    continue

                # 1. Capture dedicated reasoning content (o1/o3/Luna/DeepSeek/Ling style)
                extra = getattr(chunk, "additional_kwargs", None) or {}
                reasoning = extra.get("reasoning_content") or extra.get("reasoning")
                if reasoning:
                    reasoning_str = str(reasoning)
                    if not has_emitted_reasoning:
                        has_emitted_reasoning = True
                        reasoning_str = "\n\n" + reasoning_str
                    accumulated_reasoning.append(str(reasoning))
                    yield f"data: {json.dumps({'type': 'step', 'step_type': 'think', 'content': reasoning_str})}\n\n"

                # 2. Capture regular content with token buffer handling split <think> / </think> tags across chunks
                content = getattr(chunk, "content", "")
                if content and isinstance(content, str):
                    used_tokens += 1
                    stream_buffer += content

                    while stream_buffer:
                        if not in_think_block:
                            idx = stream_buffer.find("<think>")
                            if idx != -1:
                                prefix = stream_buffer[:idx]
                                if prefix:
                                    accumulated_tokens.append(prefix)
                                    yield f"data: {json.dumps({'type': 'token', 'content': prefix})}\n\n"
                                in_think_block = True
                                stream_buffer = stream_buffer[idx + len("<think>"):]
                                continue

                            # Check for partial prefix of "<think>" at the end of stream_buffer
                            has_partial = False
                            for length in range(min(len(stream_buffer), 6), 0, -1):
                                if "<think>".startswith(stream_buffer[-length:]):
                                    has_partial = True
                                    safe_text = stream_buffer[:-length]
                                    if safe_text:
                                        accumulated_tokens.append(safe_text)
                                        yield f"data: {json.dumps({'type': 'token', 'content': safe_text})}\n\n"
                                    stream_buffer = stream_buffer[-length:]
                                    break
                            if not has_partial:
                                accumulated_tokens.append(stream_buffer)
                                yield f"data: {json.dumps({'type': 'token', 'content': stream_buffer})}\n\n"
                                stream_buffer = ""
                            else:
                                break
                        else:
                            idx = stream_buffer.find("</think>")
                            if idx != -1:
                                think_text = stream_buffer[:idx]
                                if think_text:
                                    yield f"data: {json.dumps({'type': 'step', 'step_type': 'think', 'content': think_text})}\n\n"
                                in_think_block = False
                                stream_buffer = stream_buffer[idx + len("</think>"):]
                                continue

                            # Check for partial prefix of "</think>" at the end of stream_buffer
                            has_partial = False
                            for length in range(min(len(stream_buffer), 7), 0, -1):
                                if "</think>".startswith(stream_buffer[-length:]):
                                    has_partial = True
                                    safe_text = stream_buffer[:-length]
                                    if safe_text:
                                        yield f"data: {json.dumps({'type': 'step', 'step_type': 'think', 'content': safe_text})}\n\n"
                                    stream_buffer = stream_buffer[-length:]
                                    break
                            if not has_partial:
                                yield f"data: {json.dumps({'type': 'step', 'step_type': 'think', 'content': stream_buffer})}\n\n"
                                stream_buffer = ""
                            else:
                                break

        if stream_buffer:
            if in_think_block:
                yield f"data: {json.dumps({'type': 'step', 'step_type': 'think', 'content': stream_buffer})}\n\n"
            else:
                accumulated_tokens.append(stream_buffer)
                yield f"data: {json.dumps({'type': 'token', 'content': stream_buffer})}\n\n"

        if not accumulated_tokens and accumulated_reasoning:
            fallback_text = "".join(accumulated_reasoning).strip()
            if fallback_text:
                accumulated_tokens.append(fallback_text)
                yield f"data: {json.dumps({'type': 'token', 'content': fallback_text})}\n\n"

        # Suggest viewing the asked item on Dashboard if it differs from current on-screen selected item
        asked_sku = last_queried_sku or intended_sku
        if (
            asked_sku
            and not has_emitted_clarification
            and normalize_sku_code(asked_sku) != normalize_sku_code(selected_item_id)
        ):
            target_item = resolve_sku_item(asked_sku)
            if target_item:
                target_uid = str(target_item.get("id") or target_item.get("unique_id", ""))
                target_sku = target_item.get("sku", f"SKU-{target_uid}")
                target_name = target_item.get("name", "Product")
                suggest_card = {
                    "type": "select_item",
                    "title": f"Mở mặt hàng ({target_sku})" if lang == "vi" else f"View Item ({target_sku})",
                    "description": (
                        f"Bạn có muốn mở mặt hàng **{target_name} ({target_sku})** lên giao diện Dashboard để theo dõi biểu đồ và thông số không?"
                        if lang == "vi" else
                        f"Would you like to open **{target_name} ({target_sku})** on the dashboard to review charts and metrics?"
                    ),
                    "sku": target_sku,
                    "originalQuery": query,
                    "options": [
                        {
                            "id": "opt-view-suggest",
                            "label": f"👁️ Mở trên Dashboard ({target_sku})" if lang == "vi" else f"👁️ View on Dashboard ({target_sku})",
                            "actionType": "view_item_on_screen",
                            "payload": target_sku,
                            "primary": True,
                        }
                    ],
                }
                yield f"data: {json.dumps({'type': 'clarification', 'data': suggest_card})}\n\n"

        full_reply = "".join(accumulated_tokens).strip()
        used_tokens = calculate_conversation_tokens(history_messages, query, full_reply)
        yield f"data: {json.dumps({'type': 'done', 'used_tokens': used_tokens})}\n\n"

    except Exception as exc:
        logger.warning("Upstream LLM error in SKU Agent streaming: %s", exc)
        asked_sku = last_queried_sku or intended_sku
        if (
            asked_sku
            and not has_emitted_clarification
            and normalize_sku_code(asked_sku) != normalize_sku_code(selected_item_id)
        ):
            target_item = resolve_sku_item(asked_sku)
            if target_item:
                target_uid = str(target_item.get("id") or target_item.get("unique_id", ""))
                target_sku = target_item.get("sku", f"SKU-{target_uid}")
                target_name = target_item.get("name", "Product")
                suggest_card = {
                    "type": "select_item",
                    "title": f"Mở mặt hàng ({target_sku})" if lang == "vi" else f"View Item ({target_sku})",
                    "description": (
                        f"Bạn có muốn mở mặt hàng **{target_name} ({target_sku})** lên giao diện Dashboard để theo dõi biểu đồ và thông số không?"
                        if lang == "vi" else
                        f"Would you like to open **{target_name} ({target_sku})** on the dashboard to review charts and metrics?"
                    ),
                    "sku": target_sku,
                    "originalQuery": query,
                    "options": [
                        {
                            "id": "opt-view-suggest",
                            "label": f"👁️ Mở trên Dashboard ({target_sku})" if lang == "vi" else f"👁️ View on Dashboard ({target_sku})",
                            "actionType": "view_item_on_screen",
                            "payload": target_sku,
                            "primary": True,
                        }
                    ],
                }
                yield f"data: {json.dumps({'type': 'clarification', 'data': suggest_card})}\n\n"

        err_msg = get_standard_error_message(lang)
        yield f"data: {json.dumps({'type': 'error', 'message': err_msg})}\n\n"
        used_tokens = calculate_conversation_tokens(history_messages, query, err_msg)
        yield f"data: {json.dumps({'type': 'done', 'used_tokens': used_tokens})}\n\n"
