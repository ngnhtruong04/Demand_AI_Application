"""app.agent.fallback — Intent and SKU guardrails with interactive clarifying questions and standardized errors."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.agent.language import detect_language
from app.agent.tools import resolve_sku_item, find_matching_sku_items


@dataclass
class IntentGuardResult:
    is_fallback: bool
    fallback_type: str | None = None  # 'missing_sku', 'clarifying_intent', 'out_of_scope', 'error'
    message: str | None = None
    target_sku: str | None = None
    item_data: dict[str, Any] | None = None


def get_out_of_scope_message(lang: str = "vi") -> str:
    """Return standardized out-of-scope message for non-inventory/non-item inquiries."""
    if lang == "vi":
        return (
            "Tôi là DemandAI Assistant, chuyên viên phân tích dự báo nhu cầu bán lẻ và tối ưu hóa tồn kho hàng hóa. Câu hỏi của bạn nằm ngoài phạm vi hỗ trợ của tôi.\n"
            "Bạn có thể hỏi tôi về:\n"
            "•Phân tích nguy cơ đứt hàng hoặc dư thừa tồn kho cho một SKU (ví dụ: SKU-010).\n"
            "•Giải thích nguyên nhân tăng/giảm dự báo bằng TreeSHAP Drivers.\n"
            "•So sánh nhu cầu và rủi ro tồn kho với các mặt hàng cùng ngành."
        )
    return (
        "I am DemandAI Assistant, a specialist in retail demand forecasting and inventory replenishment optimization. Your question is outside my scope of support.\n"
        "You can ask me about:\n"
        "•Analyzing stockout or deadstock risks for a specific SKU (e.g. SKU-010).\n"
        "•Explaining forecast drivers and feature attributions using TreeSHAP Drivers.\n"
        "•Comparing demand velocity and inventory risks across category peers."
    )


OUT_OF_SCOPE_PATTERNS = [
    # Weather
    r"\b(?:thời tiết|nhiệt độ|trời mưa|trời nắng|dự báo thời tiết|bão|triều cường|weather|temperature|forecast weather|weather forecast|rainy|sunny)\b",
    # Games / Play / Entertainment
    r"\b(?:chơi game|chơi trò chơi|game gì|chơi cờ|đố vui|câu đố|đoán số|đoán chữ|chơi đi|chơi với tôi|play game|play a game|play chess|riddle|quiz)\b",
    # Storytelling / Jokes / Poetry / Creative writing / Music
    r"\b(?:kể chuyện|kể chuyện cười|kể chuyện ma|kể một câu chuyện|làm thơ|viết thơ|sáng tác thơ|hát đi|hát một bài|bài hát|tâm sự|bói toán|tử vi|cung hoàng đạo|joke|jokes|riddle|riddles|poem|poems|horoscope|funny joke|tell.*joke)\b",
    # General coding / Software development unrelated to retail/data
    r"\b(?:viết code|hướng dẫn lập trình|viết chương trình|code python|python code|viết hàm|viết app|lập trình web|html|css|javascript|leetcode|write (?:[\w]+ )?code|coding|write a script)\b",
    # Unrelated finance / Sports / Crypto / Lottery / Politics
    r"\b(?:giá vàng|giá btc|bitcoin|crypto|chứng khoán|vnindex|kết quả bóng đá|tỷ số bóng đá|tin tức thời sự|bầu cử|chính trị|football score|lottery|xổ số|kết quả xổ số)\b",
    # Cooking / Medical advice
    r"\b(?:nấu ăn|cách nấu|công thức nấu|cách làm món|món ăn ngon|triệu chứng bệnh|thuốc trị|khám bệnh|cook recipe|cooking recipe|medical advice)\b",
]

DOMAIN_KEYWORDS = [
    r"\bsku[-_\s]?\d+\b",
    r"\b(?:tồn kho|kho hàng|kho|nhập kho|xuất kho|dự báo|nhu cầu|mặt hàng|sản phẩm|hàng hóa|đặt hàng|đứt hàng|cháy hàng|deadstock|safety stock|bán lẻ|doanh số|giảm giá|tăng giá|báo cáo|chiết khấu|lead time|replenishment|inventory|warehouse|forecast|demand|stockout|stock|reorder|rop|shap|treeshap|dos|po|catalog|danh mục)\b",
    r"\b(?:bánh|roll|pastry|blueberry|donut|bread|cake)\b",
]


def is_out_of_scope_query(clean: str) -> bool:
    """Evaluate if a query is clearly out of scope (weather, gaming, creative writing, general code, etc.)."""
    clean_lower = clean.lower()

    # Weather queries override domain term 'dự báo' unless explicit item/inventory context is present
    if re.search(r"\b(?:dự báo thời tiết|thời tiết|nhiệt độ|trời mưa|trời nắng|weather forecast|forecast weather)\b", clean_lower):
        if not re.search(r"\b(?:sku[-_\s]?\d+|tồn kho|kho hàng|bánh|roll|pastry|donut)\b", clean_lower):
            return True

    is_out_of_scope_match = any(re.search(p, clean_lower) for p in OUT_OF_SCOPE_PATTERNS)
    if not is_out_of_scope_match:
        return False

    has_domain_context = any(re.search(p, clean_lower) for p in DOMAIN_KEYWORDS)
    if has_domain_context:
        return False

    return True


def extract_sku_mention(query: str, selected_item_id: str | None = None) -> str | None:
    """Extract candidate SKU from user text or workspace context."""
    clean = query.strip().lower()

    # 1. Regex match for SKU-XXX or SKU_XXX or SKU XXX (e.g. SKU-10, SKU-010)
    match = re.search(r"\bsku[-_\s]?(\d+)\b", clean)
    if match:
        return f"SKU-{int(match.group(1))}"

    # 2. Match known item by name first (e.g. "Roll 57", "Pastry 0", "Bread 1")
    if len(clean) >= 3:
        item = resolve_sku_item(clean)
        if item:
            uid = str(item.get("id") or item.get("unique_id", ""))
            return item.get("sku", f"SKU-{uid}")

    # 3. Match raw integer only if query is strictly numeric or prefixed by item/sku/mã
    if re.fullmatch(r"\d{1,5}", clean):
        return f"SKU-{int(clean)}"
    item_num_match = re.search(r"\b(?:item|mã|#|drivers|timeline|reorder|report|shap)\s*(\d{1,5})\b", clean)
    if item_num_match:
        return f"SKU-{int(item_num_match.group(1))}"

    # 4. Fallback to workspace selected_item_id ONLY when referencing 'this item' / 'sản phẩm này'
    deictic_patterns = [
        r"\bsản phẩm này\b",
        r"\bmặt hàng này\b",
        r"\bmón này\b",
        r"\bthis item\b",
        r"\bthis product\b",
        r"\bcurrent item\b",
        r"\bthe item\b",
        r"\bit\b",
        r"\bthis\b",
    ]
    is_deictic_ref = any(re.search(p, clean) for p in deictic_patterns)
    if is_deictic_ref:
        return selected_item_id

    return None


def evaluate_intent_guard(
    query: str,
    selected_item_id: str | None = None,
    forced_lang: str | None = None,
) -> IntentGuardResult:
    """Evaluate if user text is an ambiguous bare SKU requiring clarifying menu before calling LLM Agent.
    
    All general, overview, or out-of-scope inquiries pass directly to the LLM Agent.
    """
    clean = query.strip().lower()
    lang = forced_lang if forced_lang in ("vi", "en") else detect_language(query)

    # 0. Check if user prompt references a product name matching MULTIPLE items without explicit SKU code
    has_explicit_sku = bool(re.search(r"\bsku[-_\s]?\d+\b", clean))
    is_simulation_intent = bool(
        re.search(
            r"\b(giảm|giảm giá|mô phỏng|giả lập|what-if|what if|discount|khuyến mãi|tăng giá|nâng giá|hạ giá|xả hàng|deadstock|nếu|độ co giãn|co giãn|elasticity|tăng|markup|price increase|tối ưu giá)\b",
            clean
        )
    )
    if not has_explicit_sku and not is_simulation_intent:
        multi_matches = find_matching_sku_items(query)
        if len(multi_matches) > 1:
            prod_name = multi_matches[0].get("name", "Product")
            sku_lines_vi = []
            sku_lines_en = []
            for it in multi_matches[:6]:
                sku_code = it.get("sku", f"SKU-{it.get('id')}")
                wh = it.get("warehouse", "Kho")
                st = it.get("onHandStock", it.get("current_stock", 0))
                fc = float(it.get("forecast14d", 0.0))
                sku_lines_vi.append(f"• **{sku_code}** ({wh}) — Tồn: {st:,} | Dự báo: {fc:,.0f}")
                sku_lines_en.append(f"• **{sku_code}** ({wh}) — Stock: {st:,} | Forecast: {fc:,.0f}")

            clarification_data = {
                "type": "clarify_intent",
                "title": f"Làm rõ mã SKU ({prod_name})" if lang == "vi" else f"Clarify SKU ({prod_name})",
                "description": (
                    "Vui lòng chọn một mã SKU cụ thể bên dưới để xem phân tích chính xác:"
                    if lang == "vi"
                    else "Please select a specific SKU below to analyze:"
                ),
                "originalQuery": query,
                "productName": prod_name,
                "options": [
                    {
                        "label": f"{prod_name} - {it.get('sku') or 'SKU-' + str(it.get('id', ''))} ({it.get('warehouse', 'Kho')})",
                        "actionType": "select_sku",
                        "payload": (
                            f"Phân tích mặt hàng {prod_name} ({it.get('sku') or 'SKU-' + str(it.get('id', ''))} - Kho {it.get('warehouse', 'Kho')})"
                            if lang == "vi"
                            else f"Analyze item {prod_name} ({it.get('sku') or 'SKU-' + str(it.get('id', ''))} - {it.get('warehouse', 'Kho')} Warehouse)"
                        ),
                        "primary": idx == 0,
                    }
                    for idx, it in enumerate(multi_matches[:6])
                ],
            }

            msg = (
                f"Hệ thống tìm thấy **{len(multi_matches)} mặt hàng** có tên **{prod_name}** với các mã SKU và kho khác nhau:\n\n"
                + "\n".join(sku_lines_vi)
                + "\n\nVui lòng làm rõ bạn muốn phân tích mã SKU nào?"
                if lang == "vi" else
                f"Found **{len(multi_matches)} items** named **{prod_name}** across different SKUs and warehouses:\n\n"
                + "\n".join(sku_lines_en)
                + "\n\nPlease specify which SKU you would like to analyze:"
            )
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="clarify_sku_disambiguation",
                message=msg,
                target_sku=None,
                item_data={"matches": multi_matches, "clarification": clarification_data},
            )

    sku_mention = extract_sku_mention(query, selected_item_id)

    # 1. Non-existent SKU guard: if user asks for an explicit SKU that is not in the system
    if sku_mention:
        resolved_sku_item = resolve_sku_item(sku_mention)
        if not resolved_sku_item:
            msg = (
                f"Không tìm thấy mặt hàng **{sku_mention}** trong hệ thống dữ liệu kho và dự báo. Vui lòng kiểm tra lại mã SKU."
                if lang == "vi" else
                f"No item found for **{sku_mention}** in the inventory and forecast system. Please verify the SKU code."
            )
            clarification_data = {
                "type": "clarify_intent",
                "title": f"Không tìm thấy mặt hàng ({sku_mention})" if lang == "vi" else f"Item Not Found ({sku_mention})",
                "description": (
                    f"Mặt hàng **{sku_mention}** không tồn tại trong dữ liệu kho và dự báo. Vui lòng nhập mã SKU khác bên dưới:"
                    if lang == "vi" else
                    f"Item **{sku_mention}** was not found in the inventory or forecast dataset. Please enter another SKU below:"
                ),
                "originalQuery": query,
                "options": [],
                "allowTextInput": True,
                "textPlaceholder": "e.g. SKU-010, SKU-001, Pastry 0",
            }
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="sku_not_found",
                message=msg,
                target_sku=sku_mention,
                item_data={"clarification": clarification_data},
            )
    else:
        resolved_sku_item = None

    # Check if user specifically asks to view or open an item on the dashboard
    view_phrases = [
        "view item", "view the item", "open item", "open the item", "show item", "show the item",
        "view on dashboard", "open on dashboard", "show on dashboard",
        "xem mặt hàng", "xem mặt hàng này", "mở mặt hàng", "mở mặt hàng này", "mở trên dashboard", "xem trên dashboard",
        "hiển thị mặt hàng", "xem sản phẩm"
    ]
    if any(vp in clean for vp in view_phrases):
        target_item = resolved_sku_item or resolve_sku_item(selected_item_id or clean)
        if target_item:
            uid = str(target_item.get("id") or target_item.get("unique_id", ""))
            sku_code = target_item.get("sku", f"SKU-{uid}")
            name = target_item.get("name", "Product")
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="view_item_card",
                message=(
                    f"Bạn có muốn mở mặt hàng **{name} ({sku_code})** lên giao diện Dashboard không?"
                    if lang == "vi" else
                    f"Would you like to open **{name} ({sku_code})** on the workspace dashboard?"
                ),
                target_sku=sku_code,
                item_data={
                    "clarification": {
                        "type": "select_item",
                        "title": f"Mở mặt hàng ({sku_code})" if lang == "vi" else f"Open Item ({sku_code})",
                        "description": (
                            f"Mở chi tiết **{name} ({sku_code})** lên bảng làm việc để theo dõi biểu đồ và thông số."
                            if lang == "vi" else
                            f"Open details for **{name} ({sku_code})** on the dashboard to review graphs and metrics."
                        ),
                        "sku": sku_code,
                        "originalQuery": query,
                        "options": [
                            {
                                "id": "opt-view-1",
                                "label": f"👁️ Mở trên Dashboard ({sku_code})" if lang == "vi" else f"👁️ Open on Dashboard ({sku_code})",
                                "actionType": "view_item_on_screen",
                                "payload": sku_code,
                                "primary": True,
                            },
                            {
                                "id": "opt-view-2",
                                "label": f"📊 Xem phân tích trong chat ({sku_code})" if lang == "vi" else f"📊 View Analysis in Chat ({sku_code})",
                                "actionType": "send_text",
                                "payload": (
                                    f"Xem tồn kho on-hand, ROP và dự báo của {sku_code}"
                                    if lang == "vi"
                                    else f"View on-hand inventory, ROP, and forecast for {sku_code}"
                                ),
                                "primary": False,
                            },
                        ],
                    }
                },
            )

    # Check if user specifically asks to calculate or run TreeSHAP
    shap_calc_patterns = [
        r"\b(?:tính|chạy|kích hoạt|bật)\s+(?:toán\s+)?(?:tree)?shap\b",
        r"\b(?:calculate|run|compute|activate)\s+(?:tree)?shap\b",
        r"^\s*/(?:shap|treeshap)\b",
    ]
    if any(re.search(p, clean) for p in shap_calc_patterns):
        target_item = resolved_sku_item or resolve_sku_item(sku_mention or selected_item_id or clean)
        if target_item:
            uid = str(target_item.get("id") or target_item.get("unique_id", ""))
            sku_code = target_item.get("sku", f"SKU-{uid}")
            name = target_item.get("name", "Product")
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="run_shap_card",
                message=(
                    f"Bạn có muốn kích hoạt tính toán giải thích TreeSHAP cho mặt hàng **{name} ({sku_code})** không?"
                    if lang == "vi" else
                    f"Would you like to activate TreeSHAP explainability calculation for **{name} ({sku_code})**?"
                ),
                target_sku=sku_code,
                item_data={
                    "clarification": {
                        "type": "run_shap",
                        "title": f"Tính toán TreeSHAP ({sku_code})" if lang == "vi" else f"Calculate TreeSHAP ({sku_code})",
                        "description": (
                            f"Kích hoạt giải thuật TreeSHAP để phân tích 5 nhóm động lực thúc đẩy dự báo cho **{name} ({sku_code})** (quá trình có thể mất 5-10 giây)."
                            if lang == "vi" else
                            f"Run TreeSHAP algorithm to explain 5 business driver groups for **{name} ({sku_code})** (takes ~5-10 seconds)."
                        ),
                        "sku": sku_code,
                        "originalQuery": query,
                        "options": [
                            {
                                "id": "opt-shap-1",
                                "label": f"▶ Kích hoạt TreeSHAP cho {sku_code}" if lang == "vi" else f"▶ Run TreeSHAP for {sku_code}",
                                "actionType": "run_shap",
                                "payload": sku_code,
                                "primary": True,
                            },
                            {
                                "id": "opt-shap-2",
                                "label": f"👁️ Mở trên Dashboard ({sku_code})" if lang == "vi" else f"👁️ View on Dashboard ({sku_code})",
                                "actionType": "view_item_on_screen",
                                "payload": sku_code,
                                "primary": False,
                            },
                            {
                                "id": "opt-shap-3",
                                "label": f"📊 Xem tồn kho & ROP ({sku_code})" if lang == "vi" else f"📊 View Inventory & ROP ({sku_code})",
                                "actionType": "send_text",
                                "payload": (
                                    f"Xem tồn kho on-hand, ROP và dự báo của {sku_code}"
                                    if lang == "vi"
                                    else f"View on-hand inventory, ROP, and forecast for {sku_code}"
                                ),
                                "primary": False,
                            },
                        ],
                    }
                },
            )
        else:
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="clarify_sku_for_shap",
                message=(
                    "Vui lòng chỉ định mã SKU bạn muốn kích hoạt tính toán giải thích TreeSHAP:"
                    if lang == "vi" else
                    "Please specify which SKU you would like to run TreeSHAP calculation for:"
                ),
                target_sku=None,
                item_data={
                    "clarification": {
                        "type": "clarify_intent",
                        "title": "Kích hoạt TreeSHAP" if lang == "vi" else "Activate TreeSHAP",
                        "description": (
                            "Nhập mã SKU (ví dụ: SKU-010, SKU-4471) bạn muốn tính toán TreeSHAP:"
                            if lang == "vi" else
                            "Enter the SKU code (e.g. SKU-010, SKU-4471) to calculate TreeSHAP:"
                        ),
                        "originalQuery": query,
                        "options": [],
                        "allowTextInput": True,
                        "textPlaceholder": "e.g. SKU-010, SKU-4471",
                    }
                },
            )

    if not sku_mention:
        # Check out-of-scope intent guard (Layer 1 fast refusal for non-retail/non-inventory queries)
        if is_out_of_scope_query(clean):
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="out_of_scope",
                message=get_out_of_scope_message(lang),
            )
        # Pass directly to LLM: LLM answers portfolio questions, general conversation or domain queries
        return IntentGuardResult(is_fallback=False)

    # Check for ambiguous bare SKU (only when user literally typed just a SKU code or raw number like 'SKU-010' or '10')
    bare_sku_patterns = [r"^sku[-_]?\d+$", r"^item[-_]?\d+$", r"^\d+$"]
    is_bare_sku = any(re.match(p, clean) for p in bare_sku_patterns)
    is_ambiguous = is_bare_sku

    if is_ambiguous:
        item = resolved_sku_item or resolve_sku_item(sku_mention)
        if item:
            name = item.get("name", "Product")
            sku = item.get("sku", sku_mention)
            status = str(item.get("status", item.get("scenario_group", "In Stock"))).upper()
            f14 = float(item.get("forecast14d", 0.0))
            stock = int(item.get("onHandStock", item.get("current_stock", 0)))

            msg = (
                f"Tôi đã tìm thấy dữ liệu phiên mới nhất cho sản phẩm **{name} ({sku})** (Trạng thái: **{status}**, Dự báo 14 ngày: **{f14:,.0f} đơn vị**, Tồn kho hiện tại: **{stock:,} đơn vị**).\n\n"
                f"Bạn đang muốn đi sâu vào khía cạnh nào của sản phẩm này?"
                if lang == "vi" else
                f"I found the latest forecast records for **{name} ({sku})** (Status: **{status}**, 14-day Forecast: **{f14:,.0f} units**, Current Stock: **{stock:,} units**).\n\n"
                f"Which specific aspect would you like to explore?"
            )
            clarification_data = {
                "type": "clarify_intent",
                "title": f"Khám phá {name} ({sku})" if lang == "vi" else f"Explore {name} ({sku})",
                "description": (
                    f"Trạng thái: {status} | Dự báo 14 ngày: {f14:,.1f} đơn vị | Tồn kho: {stock:,} đơn vị"
                    if lang == "vi"
                    else f"Status: {status} | 14-day Forecast: {f14:,.1f} units | Current Stock: {stock:,} units"
                ),
                "sku": sku,
                "originalQuery": query,
                "options": [
                    {
                        "id": "opt-reorder",
                        "label": "📦 Quản trị kho vận (ROP & Đặt hàng)" if lang == "vi" else "📦 Inventory & Stockout Risk (ROP)",
                        "actionType": "send_text",
                        "payload": f"Kiểm tra tồn kho và ROP cho {sku}" if lang == "vi" else f"Check inventory health and ROP for {sku}",
                        "primary": True,
                    },
                    {
                        "id": "opt-drivers",
                        "label": "🔍 Nguyên nhân dự báo (TreeSHAP)" if lang == "vi" else "🔍 Forecast Drivers (TreeSHAP)",
                        "actionType": "send_text",
                        "payload": f"Giải thích nguyên nhân dự báo TreeSHAP cho {sku}" if lang == "vi" else f"Explain TreeSHAP forecast drivers for {sku}",
                        "primary": False,
                    },
                    {
                        "id": "opt-peers",
                        "label": "📊 So sánh cùng ngành hàng" if lang == "vi" else "📊 Category Peers Comparison",
                        "actionType": "send_text",
                        "payload": f"So sánh {sku} với các mặt hàng cùng phân khúc" if lang == "vi" else f"Compare {sku} with peers in the category",
                        "primary": False,
                    },
                    {
                        "id": "opt-timeline",
                        "label": "📈 Lịch trình dự báo từng ngày" if lang == "vi" else "📈 Daily Projections Timeline",
                        "actionType": "send_text",
                        "payload": f"Xem dự báo từng ngày và điểm rơi cho {sku}" if lang == "vi" else f"Show daily forecast series and peak day for {sku}",
                        "primary": False,
                    },
                ],
            }
            return IntentGuardResult(
                is_fallback=True,
                fallback_type="clarifying_intent",
                message=msg,
                target_sku=sku,
                item_data={"item": item, "clarification": clarification_data},
            )

    # All valid inquiries reach LLM Agent
    return IntentGuardResult(is_fallback=False, target_sku=sku_mention)


def get_standard_error_message(lang: str = "vi") -> str:
    """Return fixed, standardized error message when upstream LLM times out or fails."""
    if lang == "vi":
        return (
            "⚠️ Hệ thống AI tạm thời không thể hoàn thành phản hồi do nhà cung cấp mô hình bị gián đoạn hoặc quá thời gian chờ (Timeout). Vui lòng thử lại sau giây lát."
        )
    return (
        "⚠️ The AI service is temporarily unavailable due to upstream provider timeout or rate limits. Please try again in a moment."
    )
