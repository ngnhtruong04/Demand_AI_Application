"""app.agent.presets — Lean Python wrapper for zero-LLM presets & deterministic responses."""
from __future__ import annotations

import re
from typing import Any

from app.agent.tools import get_portfolio_overview, query_inventory_wiki, list_warehouses_summary

# Guardrail response templates
OUT_OF_SCOPE_RESPONSES = {
    "vi": (
        "Tôi là DemandAI Assistant, chuyên viên phân tích dự báo nhu cầu bán lẻ và tối ưu hóa tồn kho hàng hóa. "
        "Câu hỏi của bạn nằm ngoài phạm vi hỗ trợ của tôi.\n"
        "Bạn có thể hỏi tôi về:\n"
        "•Phân tích nguy cơ đứt hàng hoặc dư thừa tồn kho cho một SKU (ví dụ: SKU-010).\n"
        "•Giải thích nguyên nhân tăng/giảm dự báo bằng TreeSHAP Drivers.\n"
        "•So sánh nhu cầu và rủi ro tồn kho với các mặt hàng cùng ngành."
    ),
    "en": (
        "I am DemandAI Assistant, a specialist in retail demand forecasting and inventory replenishment optimization. "
        "Your question is outside my scope of support.\n"
        "You can ask me about:\n"
        "•Analyzing stockout or deadstock risks for a specific SKU (e.g. SKU-010).\n"
        "•Explaining forecast drivers and feature attributions using TreeSHAP Drivers.\n"
        "•Comparing demand velocity and inventory risks across category peers."
    ),
}

FORECAST_REQUIRED_MESSAGES = {
    "vi": (
        "⚠️ **Bạn chưa chạy dự báo (Run Forecast)!**\n\n"
        "Để đảm bảo câu trả lời chính xác, hệ thống yêu cầu bạn phải khởi chạy dự báo nhu cầu trước. "
        "Trợ lý chỉ có thể phân tích dữ liệu tồn kho, ROP và động lực TreeSHAP sau khi có phiên dự báo mới nhất."
    ),
    "en": (
        "⚠️ **Forecast not executed yet!**\n\n"
        "To ensure grounded analysis, you must run a demand forecast before asking the assistant. "
        "The assistant requires active forecast records to evaluate stockout risks, ROP, and TreeSHAP drivers."
    ),
}

HELP_SUMMARY = {
    "vi": (
        "### 🤖 Trợ lý DemandAI - Danh mục Lệnh & Kỹ năng\n\n"
        "- `/warehouse <kho>`: Tra cứu danh sách kho, rà soát tồn kho hoặc xuất báo cáo PDF / file CSV theo từng kho.\n"
        "- `/overview`: Xem bức tranh toàn cảnh sức khỏe kho, tỷ lệ tồn kho và tổng cầu 14 ngày.\n"
        "- `/reorder <sku>`: Phân tích ROP, số ngày tồn kho (DOS) và lượng đặt hàng (PO) khuyến nghị.\n"
        "- `/timeline <sku>`: Chuỗi dự báo 14 ngày, ngày bán cao điểm và lịch trình cạn hàng.\n"
        "- `/drivers <sku>`: 5 nhóm nhân tố TreeSHAP tác động đến dự báo nhu cầu (giá, mùa vụ, lags).\n"
        "- `/peers <ngành>`: So sánh vị thế, thị phần và sản phẩm thay thế trong cùng danh mục.\n"
        "- `/item <sku>`: Thông tin phân cấp L1-L4, hạn sử dụng và kho lưu trữ.\n"
        "- `/report <sku>`: Báo cáo điều hành 14 ngày kết hợp tồn kho, chuỗi thời gian và khuyến nghị PO.\n"
        "- `/risks`: Danh sách các mặt hàng có nguy cơ đứt hàng khẩn cấp hoặc Deadstock chôn vốn.\n\n"
        "*Bạn cũng có thể hỏi trực tiếp bằng ngôn ngữ tự nhiên, ví dụ: 'Khi nào SKU-010 hết hàng?'*"
    ),
    "en": (
        "### 🤖 DemandAI Assistant - Commands & Skills\n\n"
        "- `/warehouse <name>`: Warehouse lookup, inventory review, and targeted PDF/CSV report export.\n"
        "- `/overview`: Portfolio-wide inventory health, demand-to-stock ratio, and critical alerts.\n"
        "- `/reorder <sku>`: ROP analysis, Days of Supply (DOS), and recommended PO replenishment units.\n"
        "- `/timeline <sku>`: 14-day daily timeline, peak velocity days, and running depletion dates.\n"
        "- `/drivers <sku>`: TreeSHAP explainability across root-cause driver groups (price, promo, seasonality).\n"
        "- `/peers <category>`: Category peer rankings, share of demand, and substitutes.\n"
        "- `/item <sku>`: Hierarchy L1-L4, shelf life, and warehouse location.\n"
        "- `/report <sku>`: Structured 14-day executive forecast report with concrete PO actions.\n"
        "- `/risks`: Critical stockout alerts and deadstock capital sinks across portfolio.\n\n"
        "*You can also ask in plain English, e.g.: 'When will SKU-010 run out of stock?'*"
    ),
}


def check_preset_response(query: str, lang: str = "en") -> str | None:
    """Evaluate if a query matches a known deterministic preset that requires no LLM tokens.
    
    Returns the formatted reply string, or None if the query should proceed to the LLM agent.
    """
    clean = query.strip().lower()
    norm_lang = "vi" if lang == "vi" else "en"

    # 1. Quick Help / Slash Help
    if clean in ("/help", "help", "trợ giúp", "hướng dẫn", "bạn có thể làm gì", "what can you do"):
        return HELP_SUMMARY[norm_lang]

    # 2. Direct portfolio overview shortcut
    if clean in ("/overview", "tổng quan kho", "portfolio overview", "toàn bộ kho"):
        return get_portfolio_overview.invoke({"focus": "all"})

    if clean in ("/risks", "/anomalies", "rủi ro tồn kho", "cảnh báo đứt hàng", "inventory risks"):
        return get_portfolio_overview.invoke({"focus": "critical"})

    # Warehouse lookup preset
    if clean in ("/warehouse", "/warehouses", "danh sách kho", "tìm kho", "các kho hiện có", "danh mục kho", "warehouse list", "list warehouses", "show warehouses", "warehouses"):
        return list_warehouses_summary.invoke({"warehouse": ""})

    if clean.startswith("/warehouse"):
        raw_arg = clean[len("/warehouse"):].strip()
        action_words = ["pdf", "báo cáo", "report", "csv", "nhập", "xuất", "export", "order", "đặt hàng", "download", "tải", "generate"]
        if raw_arg and not any(w in raw_arg for w in action_words):
            return list_warehouses_summary.invoke({"warehouse": raw_arg})

    # 3. Pure metric definition queries with no specific SKU mentioned
    metric_map = {
        "rop là gì": "rop",
        "reorder point là gì": "rop",
        "what is rop": "rop",
        "explain rop": "rop",
        "days of supply là gì": "daysOfSupply",
        "what is days of supply": "daysOfSupply",
        "safety stock là gì": "safetyStock",
        "what is safety stock": "safetyStock",
        "deadstock là gì": "Deadstock",
        "what is deadstock": "Deadstock",
    }
    if clean in metric_map:
        return query_inventory_wiki.invoke({"term": metric_map[clean]})

    return None
