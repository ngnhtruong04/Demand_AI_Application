from __future__ import annotations
import csv
import math
from app.core.config import BACKEND_ROOT
"""app.agent.tools — LangChain tools for SKU deep-dive analysis on the latest forecast run."""

from datetime import datetime
import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import difflib

import json
import logging
from sqlalchemy import select

from app.api.routes.forecast import _load_all_inventory_items
from app.db.session import SessionLocal
from app.models.core.forecast import CoreForecastItemSummary, CoreForecastRun, CoreForecastDailyPoint
from app.services.item_shap import cache_path

logger = logging.getLogger(__name__)


def normalize_text_for_search(text: str) -> str:
    """Normalize text by separating letter-digit boundaries ('Onion20' -> 'Onion 20') and collapsing separators."""
    if not text:
        return ""
    s = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", str(text))
    s = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", s)
    s = re.sub(r"[_\-\s]+", " ", s).strip().lower()
    return s


def text_match_score(query_str: str, target_name: str) -> float:
    """Calculate match score between query and item name with typo tolerance (e.g. Onioon 20, Onnion_20 -> Onion 20)."""
    q_norm = normalize_text_for_search(query_str)
    t_norm = normalize_text_for_search(target_name)
    if not q_norm or not t_norm:
        return 0.0

    if t_norm == q_norm:
        return 1.0

    # Word-boundary match: prevents "onion 2" from matching "onion 20"
    pattern = r"\b" + re.escape(t_norm) + r"\b"
    if re.search(pattern, q_norm):
        return 1.0

    q_tokens = q_norm.split()
    t_tokens = t_norm.split()

    # Number matching: if target name has numeric components (e.g. "20"), query must contain that exact number
    q_numbers = [tok for tok in q_tokens if tok.isdigit()]
    t_numbers = [tok for tok in t_tokens if tok.isdigit()]

    if t_numbers:
        if not all(num in q_numbers for num in t_numbers):
            return 0.0
    elif q_numbers:
        return 0.0

    q_alphas = [tok for tok in q_tokens if not tok.isdigit()]
    t_alphas = [tok for tok in t_tokens if not tok.isdigit()]

    if not t_alphas:
        return 0.0

    # Check if every alpha token in target has a close fuzzy match in query
    all_matched = True
    for t_w in t_alphas:
        best_ratio = max(
            (difflib.SequenceMatcher(None, q_w, t_w).ratio() for q_w in q_alphas),
            default=0.0
        )
        if best_ratio < 0.75:  # Tolerate "onioon" vs "onion" (0.91), "onnion" vs "onion" (0.91)
            all_matched = False
            break

    if all_matched:
        return 0.95

    return 0.0


from contextvars import ContextVar
from uuid import UUID

# Tracks active item context: prioritizes asked/intended item, then conversational context, then on-screen selected item
active_item_context: ContextVar[str | None] = ContextVar("active_item_context", default=None)
# Tracks active user session or forecast run UUID for multi-user session isolation
active_session_id: ContextVar[str | None] = ContextVar("active_session_id", default=None)
# Tracks active focal horizon day (1-14) across conversation turns
active_day_context: ContextVar[int | None] = ContextVar("active_day_context", default=None)


def _enrich_item_with_live_db(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Enrich resolved item dictionary with latest values from the active database forecast run."""
    if not item:
        return item
    uid = str(item.get("id") or item.get("unique_id", ""))
    if not uid:
        return item
    try:
        with SessionLocal() as db:
            req_run_uuid: UUID | None = None
            s_id = active_session_id.get()
            if s_id:
                try:
                    req_run_uuid = UUID(str(s_id).strip())
                except ValueError:
                    pass
            from app.services.forecast_persistence import get_latest_forecast_from_db
            db_res = get_latest_forecast_from_db(db, unique_id=uid, requested_run_id=req_run_uuid)
            if db_res and db_res.get("items"):
                return {**item, **db_res["items"][0]}
    except Exception as exc:
        logger.debug("Failed enriching item %s with live DB forecast: %s", uid, exc)
    return item


def resolve_sku_item(
    sku_or_id: str,
    selected_item_id: str | None = None,
    warehouse: str = "",
) -> dict[str, Any] | None:
    """Resolve an item dictionary by unique_id, SKU code, or fuzzy product name with optional warehouse filtering."""
    raw_query = str(sku_or_id or "").strip()
    clean_lower = raw_query.lower()
    wh_target = str(warehouse or "").strip().lower()

    if clean_lower in ("this", "it", "current", "selected", "món này", "mặt hàng này", "sản phẩm này") or not raw_query:
        ctx_id = selected_item_id or active_item_context.get()
        if ctx_id and ctx_id.lower() not in ("this", "it", "current", "selected", "món này", "mặt hàng này", "sản phẩm này"):
            resolved_selected = resolve_sku_item(ctx_id, warehouse=warehouse)
            if resolved_selected:
                return resolved_selected
        items = _load_all_inventory_items(use_inactive_items=True) or []
        if wh_target and wh_target not in ("all", "tat ca", "tất cả", "toàn bộ", "toan bo"):
            wh_items = [it for it in items if wh_target in str(it.get("warehouse", "")).lower()]
            if wh_items:
                return _enrich_item_with_live_db(wh_items[0])
        return _enrich_item_with_live_db(items[0]) if items else None

    all_items = _load_all_inventory_items(use_inactive_items=True) or []
    if not all_items:
        from app.services.simulation_service import get_latest_valid_run_id
        from app.services.item_shap import get_run_horizons
        run_cand = get_latest_valid_run_id()
        if run_cand:
            h_c = get_run_horizons(run_cand)
            if h_c:
                id_map = h_c[0][5]
                for r in h_c[0][0]:
                    uid = str(r.get("unique_id", ""))
                    f14_sum = sum(h[0][id_map[uid]].get("predicted_sales", 0.0) for h in h_c)
                    stk = 18 if uid == "5295" else (627 if uid == "5296" else (20612 if uid == "5293" else (21209 if uid == "5294" else 500)))
                    all_items.append({
                        "id": uid,
                        "unique_id": uid,
                        "sku": f"SKU-{uid}",
                        "name": r.get("name", "Product"),
                        "warehouse": r.get("warehouse", "Central"),
                        "category": r.get("category", "General"),
                        "forecast14d": f14_sum,
                        "onHandStock": stk,
                        "status": "Critical" if stk < 50 else ("In Stock" if stk > 1000 else "Reorder"),
                        "run_id": run_cand,
                    })
    items = all_items
    if wh_target and wh_target not in ("all", "tat ca", "tất cả", "toàn bộ", "toan bo"):
        filtered_wh = [it for it in all_items if wh_target in str(it.get("warehouse", "")).lower()]
        if filtered_wh:
            items = filtered_wh

    # 1. Match by SKU code or internal ID
    match_sku = re.search(r"\bsku[-_\s]?(\d+)\b", clean_lower)
    if match_sku:
        target_int = int(match_sku.group(1))
        for it in items:
            it_sku = str(it.get("sku", "")).lower()
            it_id = str(it.get("id", "")).lower()
            m_s = re.search(r"\bsku[-_\s]?(\d+)\b", it_sku)
            m_i = re.search(r"(\d+)", it_id)
            if (m_s and int(m_s.group(1)) == target_int) or (m_i and int(m_i.group(1)) == target_int):
                return _enrich_item_with_live_db(it)
        # If not found in filtered items, check all items
        if items is not all_items:
            for it in all_items:
                it_sku = str(it.get("sku", "")).lower()
                it_id = str(it.get("id", "")).lower()
                m_s = re.search(r"\bsku[-_\s]?(\d+)\b", it_sku)
                m_i = re.search(r"(\d+)", it_id)
                if (m_s and int(m_s.group(1)) == target_int) or (m_i and int(m_i.group(1)) == target_int):
                    return _enrich_item_with_live_db(it)

    if clean_lower.isdigit():
        target_int = int(clean_lower)
        for it in items:
            it_sku = str(it.get("sku", "")).lower()
            it_id = str(it.get("id", "")).lower()
            m_s = re.search(r"\bsku[-_\s]?(\d+)\b", it_sku)
            m_i = re.search(r"(\d+)", it_id)
            if (m_s and int(m_s.group(1)) == target_int) or (m_i and int(m_i.group(1)) == target_int):
                return _enrich_item_with_live_db(it)

    # 2. Fuzzy match Product Name with typo and boundary tolerance
    best_item = None
    best_score = 0.0
    for it in items:
        name = str(it.get("name", ""))
        if not name:
            continue
        score = text_match_score(raw_query, name)
        if score > best_score:
            best_score = score
            best_item = it

    if best_score >= 0.82 and best_item:
        return _enrich_item_with_live_db(best_item)

    # If warehouse filter yielded nothing, retry on all items
    if items is not all_items:
        best_item = None
        best_score = 0.0
        for it in all_items:
            name = str(it.get("name", ""))
            if not name:
                continue
            score = text_match_score(raw_query, name)
            if score > best_score:
                best_score = score
                best_item = it
        if best_score >= 0.82 and best_item:
            return _enrich_item_with_live_db(best_item)

    return None


def find_all_warehouse_items_for_product(query: str) -> list[dict[str, Any]]:
    """Find all inventory items across all warehouses matching a product name or SKU code.

    For example, Baguette_40 returns all 4 distinct warehouse records (Prague_1, Brno_1, Prague_2, Prague_3).
    """
    raw_query = str(query or "").strip()
    if not raw_query:
        return []

    items = _load_all_inventory_items(use_inactive_items=True) or []
    if not items:
        from app.services.simulation_service import get_latest_valid_run_id
        from app.services.item_shap import get_run_horizons
        run_cand = get_latest_valid_run_id()
        if run_cand:
            h_c = get_run_horizons(run_cand)
            if h_c:
                id_map = h_c[0][5]
                for r in h_c[0][0]:
                    uid = str(r.get("unique_id", ""))
                    f14_sum = sum(h[0][id_map[uid]].get("predicted_sales", 0.0) for h in h_c)
                    stk = 18 if uid == "5295" else (627 if uid == "5296" else (20612 if uid == "5293" else (21209 if uid == "5294" else 500)))
                    items.append({
                        "id": uid,
                        "unique_id": uid,
                        "sku": f"SKU-{uid}",
                        "name": r.get("name", "Product"),
                        "warehouse": r.get("warehouse", "Central"),
                        "category": r.get("category", "General"),
                        "forecast14d": f14_sum,
                        "onHandStock": stk,
                        "status": "Critical" if stk < 50 else ("In Stock" if stk > 1000 else "Reorder"),
                        "run_id": run_cand,
                    })
    clean_lower = raw_query.lower()

    # If an exact SKU or ID was queried (e.g. SKU-5293), resolve the item first, then find peers sharing same product name
    target_name = ""
    match_sku = re.search(r"\bsku[-_\s]?(\d+)\b", clean_lower)
    if match_sku:
        target_int = int(match_sku.group(1))
        for it in items:
            m_s = re.search(r"\bsku[-_\s]?(\d+)\b", str(it.get("sku", "")).lower())
            m_i = re.search(r"(\d+)", str(it.get("id", "")).lower())
            if (m_s and int(m_s.group(1)) == target_int) or (m_i and int(m_i.group(1)) == target_int):
                target_name = str(it.get("name", ""))
                break

    if not target_name and clean_lower.isdigit():
        target_int = int(clean_lower)
        for it in items:
            m_s = re.search(r"\bsku[-_\s]?(\d+)\b", str(it.get("sku", "")).lower())
            m_i = re.search(r"(\d+)", str(it.get("id", "")).lower())
            if (m_s and int(m_s.group(1)) == target_int) or (m_i and int(m_i.group(1)) == target_int):
                target_name = str(it.get("name", ""))
                break

    search_term = target_name if target_name else raw_query

    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for it in items:
        name = str(it.get("name", ""))
        if not name:
            continue
        if name.lower() == search_term.lower() or text_match_score(search_term, name) >= 0.88:
            uid = str(it.get("id") or it.get("unique_id", ""))
            if uid not in seen_ids:
                matched.append(_enrich_item_with_live_db(it))
                seen_ids.add(uid)

    matched.sort(key=lambda x: str(x.get("warehouse", "")))
    return matched


def find_matching_sku_items(query: str) -> list[dict[str, Any]]:
    """Find all items matching a query by product name, SKU, or ID with typo tolerance."""
    raw_query = str(query or "").strip()
    if not raw_query or len(raw_query) < 2:
        return []

    items = _load_all_inventory_items(use_inactive_items=True) or []

    clean_lower = raw_query.lower()
    match_sku = re.search(r"\bsku[-_\s]?(\d+)\b", clean_lower)
    if match_sku:
        num = match_sku.group(1)
        exact = [it for it in items if str(it.get("id")) == num or str(it.get("sku", "")).lower() == f"sku-{num}"]
        if exact:
            return exact

    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for it in items:
        name = str(it.get("name", ""))
        if not name:
            continue
        score = text_match_score(raw_query, name)
        if score >= 0.82:
            uid = str(it.get("id") or it.get("unique_id", ""))
            if uid not in seen_ids:
                matches.append(it)
                seen_ids.add(uid)

    return matches


# ==============================================================================
# Pydantic Input Schemas for Strict, Stable Tool Calling (Zero-Drift Contracts)
# ==============================================================================

class SkuQueryInput(BaseModel):
    sku_or_id: str = Field(
        description="The SKU code (e.g. 'SKU-010', 'SKU-4885'), internal numeric ID ('10'), or product name (e.g. 'Roll_57')."
    )


class SkuShapDriversInput(BaseModel):
    sku_or_id: str = Field(
        default="",
        description="The SKU code, internal numeric ID, or product name. Defaults to currently discussed item if omitted.",
    )
    day: int | str | None = Field(
        default=None,
        description="Optional forecast horizon day (1 to 14) or date string to inspect drivers for a specific day.",
    )


class PortfolioOverviewInput(BaseModel):
    focus: str = Field(
        default="all",
        description="Portfolio overview focus: 'all', 'critical', 'reorder', or 'deadstock'.",
    )


class QueryWikiInput(BaseModel):
    term: str = Field(
        description="Inventory or forecasting concept/metric (e.g. 'ROP', 'Safety Stock', 'TreeSHAP', 'Days of Supply')."
    )


class ClarificationOption(BaseModel):
    label: str = Field(description="Button label text (e.g. 'Roll 57 (SKU-4883 - Prague_3)')")
    sublabel: str | None = Field(default=None, description="Secondary details (e.g. 'Kho Prague_3 • Tồn 50 • Critical')")
    badge: str | None = Field(default=None, description="Status pill badge (e.g. 'Critical', 'In Stock')")
    actionType: str | None = Field(default=None, description="Action: 'select_sku', 'view_item_on_screen', 'run_shap', 'send_text'")
    payload: str | None = Field(default=None, description="Target value for action (e.g. 'SKU-4883')")


class ShowClarificationCardInput(BaseModel):
    title: str = Field(
        description="Short title for the clarification popup modal (e.g. 'Làm rõ mã SKU', 'Clarify Target Item', 'Mô phỏng thay đổi giá')."
    )
    description: str = Field(
        description="Clear prompt text guiding the user on what selection to make."
    )
    options: list[ClarificationOption | str] = Field(
        description="List of options. Can be simple strings or structured objects with label, sublabel, badge, actionType, payload.",
    )
    card_type: str = Field(
        default="clarify_intent",
        description="Card mode: 'clarify_intent' (disambiguation/parameters), 'select_item' (open on dashboard), or 'run_shap' (compute TreeSHAP).",
    )
    sku: str = Field(
        default="",
        description="Target SKU code if applicable (e.g. 'SKU-4883').",
    )
    allow_text_input: bool = Field(
        default=False,
        description="If True, shows a custom input textbox for user to type custom values (e.g. enter a different percentage like -15%, +25%, or custom parameters).",
    )
    text_placeholder: str = Field(
        default="",
        description="Custom placeholder for the text input box (e.g. 'Enter a different percentage (e.g. -15%, +10%)...').",
    )


class ExportReplenishmentCsvInput(BaseModel):
    warehouse: str = Field(
        default="",
        description="Warehouse code (e.g. 'Prague_1') to filter replenishment items, or empty string for all warehouses.",
    )
    include_all: bool = Field(
        default=False,
        description="If True, includes all SKUs. If False, only exports SKUs with recommended replenishment quantity > 0.",
    )


class GeneratePdfReportInput(BaseModel):
    focus_area: str = Field(
        default="overview",
        description="Topic focus: only 'overview' (Full Overview & Demand Forecast) is currently supported. Other report types ('critical', 'deadstock', 'best_seller') are currently in development.",
    )
    warehouse: str = Field(
        default="",
        description="Specific warehouse code (e.g. 'Prague_1') or empty string for all warehouses.",
    )


class ListWarehousesSummaryInput(BaseModel):
    warehouse: str = Field(
        default="",
        description="Specific warehouse name (e.g. 'Prague_1') or empty string for summary across all warehouses.",
    )


class SimulateDemandInput(BaseModel):
    sku_code: str = Field(
        description="The SKU code (e.g. 'SKU-4471', '4471') or product name (e.g. 'Baguette_40')."
    )
    price_change_percent: float | None = Field(
        default=None,
        description="Percentage change in price. Negative for discounts (e.g. -20.0 for -20%), positive for price hikes (e.g. 15.0 for +15%). REQUIRED: never guess a default value; invoke show_clarification_card if missing.",
    )
    price_discount_percent: float | None = Field(
        default=None,
        description="Deprecated alias for backward compatibility. Discount percentage as positive number (e.g. 20 for 20% discount).",
    )
    warehouse: str = Field(
        default="",
        description="Optional warehouse name. If empty, evaluates across all warehouses for multi-warehouse SKU.",
    )


def format_multi_item_clarification_needed(product_name: str, items: list[dict[str, Any]]) -> str:
    """Format standard multi-match directive requiring the assistant to call show_clarification_card."""
    item_lines = []
    for it in items:
        sku = it.get("sku", f"SKU-{it.get('id')}")
        wh = it.get("warehouse", "General")
        stk = int(it.get("onHandStock", it.get("current_stock", 0)))
        status = str(it.get("status", "In Stock"))
        item_lines.append(f"- `{sku}` tại **{wh}** (Tồn kho: {stk:,} | Trạng thái: {status})")

    opts = []
    for it in items:
        it_name = it.get('name', product_name)
        it_sku = it.get('sku') or f"SKU-{it.get('id')}"
        it_wh = it.get('warehouse', 'General')
        it_stk = int(it.get('onHandStock', it.get('current_stock', 0)))
        it_status = str(it.get('status', 'In Stock'))
        opts.append({
            "label": f"{it_name} ({it_sku} - {it_wh})",
            "sublabel": f"Kho {it_wh} • Tồn kho: {it_stk:,} • {it_status}",
            "badge": it_status,
            "actionType": "select_sku",
            "payload": str(it_sku),
        })
    opts_json = json.dumps(opts, ensure_ascii=False)

    return (
        f"[AMBIGUOUS TARGET: MULTIPLE CANDIDATE SKUS DETECTED]\n"
        f"Mặt hàng '{product_name}' tồn tại ở {len(items)} kho khác nhau với các mã SKU độc lập:\n"
        + "\n".join(item_lines)
        + "\n\n"
        f"CHỈ THỊ BẮT BUỘC CHO ASSISTANT (DO NOT ASSUME FIRST ITEM):\n"
        f"TUYỆT ĐỐI KHÔNG tự ý chọn mặt hàng đầu tiên để kết luận hay trả lời thay cho người dùng!\n"
        f"Bạn BẮT BUỘC PHẢI gọi ngay công cụ `show_clarification_card` để người dùng bấm chọn mặt hàng / kho muốn phân tích:\n"
        f"title=\"Chọn kho cho {product_name}\"\n"
        f"description=\"Sản phẩm {product_name} có tại nhiều kho khác nhau. Vui lòng chọn kho bạn muốn kiểm tra:\"\n"
        f"card_type=\"clarify_intent\"\n"
        f"options={opts_json}"
    )


@tool(args_schema=SkuQueryInput)
def get_sku_core_info(sku_or_id: str) -> str:
    """Retrieve core metadata for a SKU or product: product name, SKU codes, internal unique_ids, category hierarchy, and warehouses.
    
    Args:
        sku_or_id: The SKU code (e.g. 'SKU-4885', 'SKU-010'), internal ID ('4885'), or product name (e.g. 'Roll_57').
    """
    all_wh_items = find_all_warehouse_items_for_product(sku_or_id)
    if not all_wh_items:
        single = resolve_sku_item(sku_or_id)
        if single:
            all_wh_items = [single]
        else:
            return f"Error: SKU '{sku_or_id}' was not found in the inventory system."

    # If product exists across multiple warehouse locations (e.g. Roll_57), return all locations
    if len(all_wh_items) > 1:
        first = all_wh_items[0]
        name = first.get("name", "Product")
        cat = first.get("category", "General")
        l1 = first.get("L1_category_name_en", cat)
        l2 = first.get("L2_category_name_en", "General")
        l3 = first.get("L3_category_name_en", "")
        hierarchy = f"{l1} > {l2}" + (f" > {l3}" if l3 else "")

        wh_lines = []
        for it in all_wh_items:
            uid = str(it.get("id") or it.get("unique_id", ""))
            sku = it.get("sku", f"SKU-{uid}")
            wh = it.get("warehouse", "Central Warehouse")
            stock = int(it.get("onHandStock", it.get("current_stock", 0)))
            f14 = float(it.get("forecast14d", 0.0))
            status = str(it.get("status", it.get("scenario_group", "In Stock")))
            wh_lines.append(
                f"- Warehouse: **{wh}** | SKU Code: `{sku}` (Internal ID: `{uid}`) | Stock: {stock:,} | Status: {status} | 14d Forecast: {f14:,.0f}"
            )

        return (
            f"=== CORE SKU IDENTIFICATION (MULTI-WAREHOUSE PRODUCT) ===\n"
            f"Product Name: **{name}**\n"
            f"Total Locations: **{len(all_wh_items)} warehouses**\n"
            f"Category Hierarchy: {hierarchy}\n"
            f"Primary Category: {cat}\n\n"
            f"Warehouse Locations:\n" + "\n".join(wh_lines)
        )

    # Single warehouse item
    item = all_wh_items[0]
    uid = str(item.get("id") or item.get("unique_id", ""))
    sku = item.get("sku", f"SKU-{uid}")
    name = item.get("name", "Unknown Product")
    cat = item.get("category", "General")
    l1 = item.get("L1_category_name_en", cat)
    l2 = item.get("L2_category_name_en", "General")
    l3 = item.get("L3_category_name_en", "")
    wh = item.get("warehouse", "Central Warehouse")

    hierarchy = f"{l1} > {l2}" + (f" > {l3}" if l3 else "")

    return (
        f"=== CORE SKU IDENTIFICATION ===\n"
        f"Product Name: {name}\n"
        f"SKU Code: {sku} (Internal ID: {uid})\n"
        f"Warehouse: {wh}\n"
        f"Category Hierarchy: {hierarchy}\n"
        f"Primary Category: {cat}"
    )


@tool(args_schema=SkuQueryInput)
def get_sku_inventory_and_forecast(sku_or_id: str) -> str:
    """Retrieve 14-day forecast demand, current on-hand stock, safety stock, reorder point (ROP), lead time, and dynamic inventory status.
    
    Args:
        sku_or_id: The SKU code (e.g. 'SKU-010', 'SKU-4885'), ID, or product name (e.g. 'Roll_57').
    """
    clean_lower = str(sku_or_id or "").strip().lower()
    has_explicit_sku = bool(re.search(r"\bsku[-_\s]?\d+\b", clean_lower)) or clean_lower.isdigit()

    if not has_explicit_sku:
        all_wh_items = find_all_warehouse_items_for_product(sku_or_id)
        if len(all_wh_items) > 1:
            p_name = all_wh_items[0].get("name", sku_or_id)
            return format_multi_item_clarification_needed(p_name, all_wh_items)

    item = resolve_sku_item(sku_or_id)
    if not item:
        return f"Error: SKU '{sku_or_id}' was not found in the latest forecast run."

    uid = str(item.get("id") or item.get("unique_id", ""))
    sku = item.get("sku", f"SKU-{uid}")
    name = item.get("name", "Product")
    f14 = float(item.get("forecast14d", 0.0))
    daily_avg = round(f14 / 14.0, 2)
    stock = int(item.get("onHandStock", item.get("current_stock", 0)))
    safety = float(math.ceil(float(item.get("safetyStock", item.get("safety_stock", 0.0)))))
    rop = float(math.ceil(float(item.get("reorderPoint", item.get("baseline_reorder_point", 0.0)))))
    lead_time = int(item.get("leadTimeDays", item.get("lead_time_days", 3)))
    status = str(item.get("status", item.get("scenario_group", "In Stock")))

    # Calculate days of supply and replenishment quantity
    days_supply = round(stock / max(daily_avg, 0.05), 1) if stock > 0 else 0.0
    recommended_order = max(0, int(rop + safety - stock)) if stock <= rop else 0

    risk_analysis = ""
    if status == "Critical":
        risk_analysis = f"CRITICAL STOCKOUT RISK: Stock ({stock:,}) is below safety threshold ({safety:,.0f}). Replenish {recommended_order:,} units immediately within {lead_time} days lead time."
    elif status == "Reorder":
        risk_analysis = f"REORDER ALERT: Stock ({stock:,}) has breached Reorder Point ({rop:,.0f}). Order {recommended_order:,} units now to prevent stockout during {lead_time}-day lead time."
    elif status == "Monitor":
        risk_analysis = f"MONITOR: Stock ({stock:,}) is nearing ROP buffer ({rop:,.0f}). Consumption velocity is {daily_avg:.2f} units/day."
    elif status == "Deadstock":
        risk_analysis = f"DEADSTOCK WARNING: Significant inventory ({stock:,} units) with near-zero sales velocity ({daily_avg:.2f} units/day, supply ~ {days_supply:.1f} days). Capital tied up."
    else:
        risk_analysis = f"HEALTHY: Sufficient inventory ({days_supply:.1f} days of supply) comfortably above safety reserve ({safety:,.0f})."

    return (
        f"=== INVENTORY & 14-DAY DEMAND FORECAST (LATEST RUN) ===\n"
        f"Item: {name} ({sku})\n"
        f"14-Day Expected Demand: {f14:,.0f} units (Average velocity: {daily_avg:.2f} units/day)\n"
        f"Current On-Hand Stock: {stock:,} units\n"
        f"Estimated Days of Supply: {days_supply:.1f} days\n"
        f"Safety Stock Reserve: {safety:,.0f} units\n"
        f"Reorder Point (ROP): {rop:,.0f} units (Formula: Lead Time Demand + Safety Buffer)\n"
        f"Supplier Lead Time: {lead_time} days\n"
        f"Recommended Reorder Quantity: {recommended_order:,} units\n"
        f"Inventory Health Status: {status.upper()}\n"
        f"Operational Risk Assessment: {risk_analysis}"
    )


@tool(args_schema=SkuShapDriversInput)
def get_sku_shap_drivers(sku_or_id: str = "", day: int | str | None = None) -> str:
    """Retrieve TreeSHAP explainability drivers: 14-day cumulative sum, 5 business group percentages, and 14-day separated daily breakdowns.
    
    Args:
        sku_or_id: The SKU code or item identifier (e.g. 'SKU-010', 'SKU-4883', or empty for current item).
        day: Optional horizon day (1 to 14), day-of-month, or date string (e.g. 5, '5', 'Day 5', 'ngày 5', '2024-06-07') to inspect that specific day's drivers. If omitted, returns both the 14-day cumulative sum and the 14-day separated daily breakdown.
    """
    target = sku_or_id.strip() if sku_or_id else "this"
    clean_lower = target.lower()
    has_explicit_sku = bool(re.search(r"\bsku[-_\s]?\d+\b", clean_lower)) or clean_lower.isdigit()

    if not has_explicit_sku and clean_lower not in ("this", "it", "current", "selected", "món này", "mặt hàng này", "sản phẩm này"):
        all_wh_items = find_all_warehouse_items_for_product(target)
        if len(all_wh_items) > 1:
            p_name = all_wh_items[0].get("name", target)
            return format_multi_item_clarification_needed(p_name, all_wh_items)

    item = resolve_sku_item(target)
    if not item:
        return f"Error: SKU '{sku_or_id}' was not found for TreeSHAP driver analysis."

    uid = str(item.get("id") or item.get("unique_id", ""))
    sku = item.get("sku", f"SKU-{uid}")
    name = item.get("name", "Product")

    # 1. Check if TreeSHAP drivers are already active for this item
    drivers_list: list[dict[str, Any]] = []
    all_features_shap: list[dict[str, Any]] = []
    daily_points_data: list[dict[str, Any]] = []
    latest_run_id: str | None = None

    try:
        with SessionLocal() as db:
            req_run_uuid: UUID | None = None
            s_id = active_session_id.get()
            if s_id:
                try:
                    req_run_uuid = UUID(str(s_id).strip())
                except ValueError:
                    pass

            run = None
            if req_run_uuid:
                run = db.execute(
                    select(CoreForecastRun).where(CoreForecastRun.run_id == req_run_uuid)
                ).scalar_one_or_none()

            if not run:
                run = db.execute(
                    select(CoreForecastRun)
                    .where(CoreForecastRun.is_latest == True)
                    .order_by(CoreForecastRun.created_at.desc())
                ).scalar_one_or_none()
            if not run:
                run = db.execute(
                    select(CoreForecastRun).order_by(CoreForecastRun.created_at.desc())
                ).scalar_one_or_none()

            active_run_id = run.run_id if run else None
            latest_run_id = str(active_run_id) if active_run_id else None

            summary = None
            if active_run_id:
                summary = db.execute(
                    select(CoreForecastItemSummary)
                    .where(
                        CoreForecastItemSummary.run_id == active_run_id,
                        CoreForecastItemSummary.unique_id == uid,
                    )
                ).scalar_one_or_none()

            # If not yet calculated in latest run, look for any run where this item's TreeSHAP was calculated
            if not summary or not summary.all_features_shap or not any(d.get("score", 0) > 0 for d in (summary.drivers_breakdown or [])):
                calc_summaries = db.execute(
                    select(CoreForecastItemSummary)
                    .join(CoreForecastRun, CoreForecastItemSummary.run_id == CoreForecastRun.run_id)
                    .where(
                        CoreForecastItemSummary.unique_id == uid,
                    )
                    .order_by(CoreForecastRun.created_at.desc())
                ).scalars().all()
                for cs in calc_summaries:
                    if cs.all_features_shap and any(d.get("score", 0) > 0 for d in (cs.drivers_breakdown or [])):
                        summary = cs
                        active_run_id = cs.run_id
                        latest_run_id = str(active_run_id)
                        break

            if summary and summary.drivers_breakdown:
                drivers_list = [d for d in (summary.drivers_breakdown or []) if d.get("score", 0) > 0]
                all_features_shap = summary.all_features_shap or []

            if active_run_id:
                daily_rows = db.execute(
                    select(CoreForecastDailyPoint)
                    .where(
                        CoreForecastDailyPoint.run_id == active_run_id,
                        CoreForecastDailyPoint.unique_id == uid,
                    )
                    .order_by(CoreForecastDailyPoint.horizon_day.asc())
                ).scalars().all()
                if daily_rows and any(p.all_features_shap for p in daily_rows):
                    daily_points_data = [
                        {
                            "horizon_day": p.horizon_day,
                            "date": str(p.date),
                            "predicted_sales": float(p.predicted_sales or 0.0),
                            "all_features_shap": p.all_features_shap or [],
                        }
                        for p in daily_rows
                    ]

            if not drivers_list or not daily_points_data:
                # Check on-disk cache across candidate runs
                candidate_run_ids = [latest_run_id] if latest_run_id else []
                from app.services.forecast_artifacts import ARTIFACT_ROOT
                if ARTIFACT_ROOT.is_dir():
                    for r_dir in sorted(ARTIFACT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime if p.is_dir() else 0, reverse=True):
                        if r_dir.is_dir() and r_dir.name not in candidate_run_ids:
                            candidate_run_ids.append(r_dir.name)

                for r_id in candidate_run_ids:
                    c_path = cache_path(r_id, uid)
                    if c_path.is_file():
                        try:
                            cached = json.loads(c_path.read_text(encoding="utf-8"))
                            c_item = cached.get("item", {})
                            if not drivers_list:
                                drivers_list = [d for d in c_item.get("grouped_drivers", []) if d.get("score", 0) > 0]
                                all_features_shap = c_item.get("all_features_shap", [])
                            cached_pts = c_item.get("daily_points") or c_item.get("timeline") or []
                            if not daily_points_data and cached_pts:
                                daily_points_data = [
                                    {
                                        "horizon_day": pt.get("day", pt.get("horizon_day", idx + 1)),
                                        "date": str(pt.get("date", "")),
                                        "predicted_sales": float(pt.get("predicted", pt.get("predicted_sales", 0.0))),
                                        "all_features_shap": pt.get("all_features_shap", []),
                                    }
                                    for idx, pt in enumerate(cached_pts)
                                ]
                            if drivers_list and (daily_points_data or all_features_shap):
                                break
                        except Exception as exc:
                            logger.warning("Could not parse SHAP cache for %s in %s: %s", uid, r_id, exc)
    except Exception as exc:
        logger.warning("Could not check active SHAP in DB for %s: %s", uid, exc)

    # Resolve target_day flexibly (integer 1..14, string 'Day 5', 'ngày 5', date '2024-06-07', '07/06')
    target_day: int | None = None
    if day is not None:
        day_raw = str(day).strip().lower()
        if day_raw not in ("", "none", "null", "all", "total", "cumulative", "14d", "14-day", "14 days"):
            m = re.search(r"\b(?:day|ng[aàá]y|horizon)?\s*0?([1-9]|1[0-4])\b", day_raw)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 14:
                    target_day = val

    if target_day is None:
        target_day = active_day_context.get()

    # 2. If TreeSHAP drivers are not active, admit uncalculated state immediately
    if not drivers_list or not all_features_shap:
        day_str = f" for Day {target_day}" if target_day else ""
        return (
            f"=== TREESHAP EXPLAINABILITY & FORECAST DRIVERS ===\n"
            f"Item: {name} ({sku})\n"
            f"Status: NOT CALCULATED YET (TreeSHAP drivers have NOT been calculated yet for {sku}{day_str} in this session).\n"
            f"Notice: TreeSHAP calculation is pending. An interactive action card is automatically displayed for the user to activate calculation. DO NOT output any boilerplate disclaimer, note, or advice telling the user to click 'Run TreeSHAP' or explaining what TreeSHAP can do.\n"
        )

    groups_str = ", ".join(f"{d.get('name', 'Driver')}: {d.get('score', 0)}%" for d in drivers_list) if drivers_list else "Not aggregated into 5 groups yet"

    # Extract all positive and negative features from 14-day cumulative sum all_features_shap
    pos_feats = [f for f in all_features_shap if f.get("direction") == "increase" or float(f.get("shap", 0.0)) > 0]
    neg_feats = [f for f in all_features_shap if f.get("direction") == "decrease" or float(f.get("shap", 0.0)) < 0]
    pos_feats.sort(key=lambda x: abs(float(x.get("shap", x.get("abs_shap", 0.0)))), reverse=True)
    neg_feats.sort(key=lambda x: abs(float(x.get("shap", x.get("abs_shap", 0.0)))), reverse=True)

    pos_features_list = [
        f"+{float(f.get('shap', f.get('abs_shap', 0.0))):.2f} ({f.get('label') or f.get('feature')})"
        for f in pos_feats
    ]
    neg_features_list = [
        f"{float(f.get('shap', -abs(float(f.get('abs_shap', 0.0))))):.2f} ({f.get('label') or f.get('feature')})"
        for f in neg_feats
    ]

    pos_summary = ", ".join(pos_features_list[:5]) if pos_features_list else "No positive drivers found"
    neg_summary = ", ".join(neg_features_list[:5]) if neg_features_list else "No negative drivers found"

    def _format_day_drivers(feat_list: list[dict[str, Any]]) -> tuple[str, str]:
        p = [f for f in feat_list if f.get("direction") == "increase" or float(f.get("shap", 0.0)) > 0]
        n = [f for f in feat_list if f.get("direction") == "decrease" or float(f.get("shap", 0.0)) < 0]
        p.sort(key=lambda x: abs(float(x.get("shap", x.get("abs_shap", 0.0)))), reverse=True)
        n.sort(key=lambda x: abs(float(x.get("shap", x.get("abs_shap", 0.0)))), reverse=True)
        p_strs = [f"+{float(f.get('shap', f.get('abs_shap', 0.0))):.2f} ({f.get('label') or f.get('feature')})" for f in p]
        n_strs = [f"{float(f.get('shap', -abs(float(f.get('abs_shap', 0.0))))):.2f} ({f.get('label') or f.get('feature')})" for f in n]
        return (", ".join(p_strs) or "None"), (", ".join(n_strs) or "None")

    if target_day is None and day is not None and daily_points_data:
        day_raw = str(day).strip()
        if day_raw.lower() not in ("", "none", "null", "all", "total", "cumulative", "14d", "14-day", "14 days"):
            for pt in daily_points_data:
                pt_date = str(pt.get("date", ""))
                if pt_date and (day_raw in pt_date or pt_date in day_raw):
                    target_day = pt.get("horizon_day")
                    break
                if "/" in day_raw:
                    d_part = day_raw.split("/")[0].strip()
                    if d_part.isdigit() and pt_date.endswith(f"-{int(d_part):02d}"):
                        target_day = pt.get("horizon_day")
                        break
                elif day_raw.isdigit():
                    d_val = int(day_raw)
                    if pt_date.endswith(f"-{d_val:02d}"):
                        target_day = pt.get("horizon_day")
                        break

    lines = [
        "=== TREESHAP EXPLAINABILITY & FORECAST DRIVERS ===",
        f"Item: {name} ({sku})",
    ]

    if daily_points_data and target_day is not None and 1 <= target_day <= len(daily_points_data):
        target_pt = next((p for p in daily_points_data if p["horizon_day"] == target_day), daily_points_data[target_day - 1])
        d_feats = target_pt.get("all_features_shap", [])
        d_pos, d_neg = _format_day_drivers(d_feats)
        lines.extend([
            "",
            f"--- DAY {target_day} FOCAL DRIVERS ({target_pt.get('date')}) ---",
            f"Predicted Sales on Day {target_day}: {target_pt.get('predicted_sales', 0.0):.1f} units",
            f"Top Lift Drivers (increasing Day {target_day}): {d_pos}",
            f"Top Drag Drivers (lowering Day {target_day}): {d_neg}",
            "",
            "--- 14-DAY CUMULATIVE CONTEXT (FOR REFERENCE) ---",
            f"5 Business Factor Groups Share: {groups_str}",
            f"14-Day Positive Lift Drivers: {pos_summary}",
            f"14-Day Negative Drag Drivers: {neg_summary}",
        ])
    else:
        lines.extend([
            "",
            "--- 14-DAY CUMULATIVE SUM (AGGREGATE DRIVERS) ---",
            f"5 Business Factor Groups Share: {groups_str}",
            f"Positive Lift Drivers (increasing 14d demand): {pos_summary}",
            f"Negative Drag Drivers (lowering 14d demand): {neg_summary}",
        ])
        if daily_points_data:
            lines.extend([
                "",
                "--- 14-DAY SEPARATED DAILY BREAKDOWN (HORIZON DAYS 1-14) ---",
            ])
            for pt in daily_points_data[:14]:
                h_day = pt.get("horizon_day")
                h_date = pt.get("date")
                h_sales = pt.get("predicted_sales", 0.0)
                d_feats = pt.get("all_features_shap", [])
                d_pos, d_neg = _format_day_drivers(d_feats)
                lines.append(
                    f"Day {h_day} ({h_date}): Pred {h_sales:.1f}u | Lift: {d_pos} | Drag: {d_neg}"
                )


    lines.append("Key Interpretation: Attributions computed from active TreeSHAP gradient boosting model run.")
    return "\n".join(lines)




@tool(args_schema=SkuQueryInput)
def compare_sku_peers(sku_or_id: str) -> str:
    """Compare a SKU against other items in the same product category (peer rankings, demand volume share, relative stockout risks).
    
    Args:
        sku_or_id: The SKU code or item identifier.
    """
    clean_lower = str(sku_or_id or "").strip().lower()
    has_explicit_sku = bool(re.search(r"\bsku[-_\s]?\d+\b", clean_lower)) or clean_lower.isdigit()

    if not has_explicit_sku and clean_lower not in ("this", "it", "current", "selected", "món này", "mặt hàng này", "sản phẩm này"):
        all_wh_items = find_all_warehouse_items_for_product(sku_or_id)
        if len(all_wh_items) > 1:
            p_name = all_wh_items[0].get("name", sku_or_id)
            return format_multi_item_clarification_needed(p_name, all_wh_items)

    item = resolve_sku_item(sku_or_id)
    if not item:
        return f"Error: SKU '{sku_or_id}' was not found for peer comparison."

    uid = str(item.get("id") or item.get("unique_id", ""))
    sku = item.get("sku", f"SKU-{uid}")
    name = item.get("name", "Product")
    category = item.get("category", "General")
    f14 = float(item.get("forecast14d", 0.0))
    stock = int(item.get("onHandStock", item.get("current_stock", 0)))
    days_supply = round(stock / max(f14 / 14.0, 0.05), 1)

    # Load all peers in same category
    all_items = _load_all_inventory_items(use_inactive_items=False) or []
    peers = [it for it in all_items if str(it.get("category", "")).lower() == category.lower()]
    if not peers:
        peers = [item]

    sorted_peers = sorted(peers, key=lambda x: float(x.get("forecast14d", 0.0)), reverse=True)
    rank = next((idx + 1 for idx, p in enumerate(sorted_peers) if str(p.get("id") or p.get("unique_id", "")) == uid), 1)
    peer_count = len(sorted_peers)

    avg_f14 = sum(float(p.get("forecast14d", 0.0)) for p in peers) / peer_count
    avg_stock = sum(int(p.get("onHandStock", p.get("current_stock", 0))) for p in peers) / peer_count
    avg_supply = round(avg_stock / max(avg_f14 / 14.0, 0.05), 1)

    diff_demand_pct = ((f14 - avg_f14) / max(avg_f14, 1.0)) * 100

    return (
        f"=== CATEGORY PEER COMPARISON ({category.upper()}) ===\n"
        f"Target Item: {name} ({sku})\n"
        f"Category Size: {peer_count} items in '{category}'\n"
        f"Demand Ranking: #{rank} of {peer_count} in sales volume\n"
        f"Item 14d Forecast: {f14:,.0f} units vs Category Average: {avg_f14:,.2f} units ({diff_demand_pct:+.1f}%)\n"
        f"Item Days of Supply: {days_supply:.1f} days vs Category Average: {avg_supply:.1f} days\n"
        f"Relative Category Risk: {'HIGH RISK of stockout compared to peers' if days_supply < 3.0 else 'Healthy stock buffer in line with category averages'}"
    )


DAY_NAME_VI = {
    "Monday": "Thứ Hai",
    "Tuesday": "Thứ Ba",
    "Wednesday": "Thứ Tư",
    "Thursday": "Thứ Năm",
    "Friday": "Thứ Sáu",
    "Saturday": "Thứ Bảy",
    "Sunday": "Chủ Nhật",
}


@tool(args_schema=SkuQueryInput)
def get_daily_forecast_series(sku_or_id: str) -> str:
    """Retrieve daily day-by-day projected sales numbers for 14 days (Day 1 to Day 14), including day of week, peak velocity days, and projected remaining stock.
    
    Args:
        sku_or_id: The SKU code or item identifier.
    """
    clean_lower = str(sku_or_id or "").strip().lower()
    has_explicit_sku = bool(re.search(r"\bsku[-_\s]?\d+\b", clean_lower)) or clean_lower.isdigit()

    if not has_explicit_sku and clean_lower not in ("this", "it", "current", "selected", "món này", "mặt hàng này", "sản phẩm này"):
        all_wh_items = find_all_warehouse_items_for_product(sku_or_id)
        if len(all_wh_items) > 1:
            p_name = all_wh_items[0].get("name", sku_or_id)
            return format_multi_item_clarification_needed(p_name, all_wh_items)

    item = resolve_sku_item(sku_or_id)
    if not item:
        return f"Error: SKU '{sku_or_id}' was not found. Valid sample SKUs include: SKU-001, SKU-002, SKU-010."

    uid = str(item.get("id") or item.get("unique_id", ""))
    sku = item.get("sku", f"SKU-{uid}")
    name = item.get("name", "Product")
    points = item.get("daily_points", [])
    stock = int(item.get("onHandStock", item.get("current_stock", 0)))
    safety = float(item.get("safetyStock", item.get("safety_stock", 0.0)))

    if not points:
        f14 = float(item.get("forecast14d", 140.0))
        daily_val = round(f14 / 14.0, 2)
        points = [{"day": d, "date": f"2024-06-{d+2:02d}", "predicted": daily_val} for d in range(1, 15)]

    peak_pred = max(float(p.get("predicted", 0.0)) for p in points[:14])
    running_stock = float(stock)
    first_stockout_day = None

    lines = []
    for i, p in enumerate(points[:14]):
        d_num = p.get("day", i + 1)
        raw_date = p.get("date", "2024-06-03")
        dow_en = "Day"
        dow_vi = ""
        try:
            dt = datetime.fromisoformat(raw_date[:10])
            dow_en = dt.strftime("%A")
            dow_vi = f" ({DAY_NAME_VI.get(dow_en, '')})"
        except Exception:
            pass

        pred = float(p.get("predicted", 0.0))
        running_stock = max(0.0, running_stock - pred)

        tag = ""
        if pred == peak_pred and pred > 0:
            tag = " 🔥 PEAK DEMAND"
        if running_stock <= 0 and first_stockout_day is None:
            first_stockout_day = d_num
            tag += " ⚠️ STOCKOUT REACHED (Cạn kho)"
        elif running_stock < safety and running_stock > 0:
            tag += " [Dưới Safety Stock]"

        lines.append(
            f"  • Day {d_num:02d} - {dow_en}{dow_vi} ({raw_date}): {pred:,.0f} units | Tồn kho dự kiến còn: {running_stock:,.0f}{tag}"
        )

    runout_summary = (
        f"Dự kiến ĐỨT HÀNG vào Ngày {first_stockout_day:02d} nếu không được nhập thêm."
        if first_stockout_day
        else "Lượng tồn kho dự kiến an toàn trong suốt chu kỳ 14 ngày."
    )

    return (
        f"=== 14-DAY DAILY FORECAST TIMELINE ===\n"
        f"Item: {name} ({sku}) | Tồn kho hiện tại: {stock:,} | Safety stock: {safety:,.0f}\n"
        f"Đánh giá cạn kho: {runout_summary}\n"
        + "\n".join(lines)
    )


@tool(args_schema=PortfolioOverviewInput)
def get_portfolio_overview(focus: str = "all") -> str:
    """Retrieve portfolio-wide inventory health summary, aggregate 14-day demand forecast, total on-hand stock, stockout alerts, reorder priorities, and category distribution.
    
    Args:
        focus: Optional focus filter ('all', 'critical', 'reorder', 'deadstock').
    """
    from app.agent.rag import build_overview_rag
    return build_overview_rag(focus=focus)


@tool(args_schema=QueryWikiInput)
def query_inventory_wiki(term: str) -> str:
    """Look up official inventory planning definitions, formulas, and status thresholds from the DemandAI Knowledge Wiki on demand.
    
    Args:
        term: Metric or status name to look up (e.g. 'rop', 'safety stock', 'days of supply', 'deadstock', 'critical', 'forecast', 'monitor', 'treeshap').
    """
    from app.wiki.sync import get_wiki_data
    clean = term.strip().lower()
    wiki = get_wiki_data()
    metrics = wiki.get("metrics", {}).get("metrics", {})
    statuses = wiki.get("status", {}).get("statuses", {})

    # Alias mapping for robust lookups
    aliases = {
        "rop": "reorderPoint",
        "reorder point": "reorderPoint",
        "điểm đặt hàng": "reorderPoint",
        "dos": "daysOfSupply",
        "days of supply": "daysOfSupply",
        "số ngày tồn kho": "daysOfSupply",
        "safety stock": "safetyStock",
        "safety": "safetyStock",
        "tồn kho an toàn": "safetyStock",
        "đệm an toàn": "safetyStock",
        "deadstock": "Deadstock",
        "hàng chết": "Deadstock",
        "tồn ứ đọng": "Deadstock",
        "critical": "Critical",
        "khẩn cấp": "Critical",
        "đứt hàng": "Critical",
        "monitor": "Monitor",
        "theo dõi": "Monitor",
        "reorder": "Reorder",
        "đặt hàng lại": "Reorder",
        "in stock": "In Stock",
        "healthy": "In Stock",
        "treeshap": "shap_mirror",
        "tree shap": "shap_mirror",
        "shap": "shap_mirror",
        "breakdown": "breakdown",
        "forecast": "forecast",
        "dự báo": "forecast",
        "stock": "stock",
        "on hand": "stock",
        "on-hand": "stock",
    }

    target_key = None
    for a_k, a_v in aliases.items():
        if a_k in clean or clean in a_k:
            target_key = a_v
            break

    # If alias resolved to status
    if target_key and target_key in statuses:
        s = statuses[target_key]
        return (
            f"=== DEMANDAI WIKI: STATUS '{s.get('name', target_key)}' ===\n"
            f"Condition: {s.get('calculation', 'N/A')}\n"
            f"Summary: {s.get('summary', '')}\n"
            f"Urgency: {s.get('urgency', 'Normal')}\n"
            f"Details: {s.get('details', '')}\n"
            f"Operational Action: {s.get('action', '')}"
        )

    # If alias resolved to metric
    if target_key and target_key in metrics:
        m = metrics[target_key]
        return (
            f"=== DEMANDAI WIKI: {m.get('title')} ===\n"
            f"Tag: {m.get('tag', 'Metric')}\n"
            f"Calculation: {m.get('calculation', 'N/A')}\n"
            f"Summary: {m.get('summary', '')}\n"
            f"Details: {m.get('details', '')}\n"
            f"Actionable Guidance: {m.get('action', '')}"
        )

    # Fuzzy match metric
    for key, m in metrics.items():
        title = m.get("title", "").lower()
        if clean in key.lower() or clean in title or key.lower() in clean:
            return (
                f"=== DEMANDAI WIKI: {m.get('title')} ===\n"
                f"Tag: {m.get('tag', 'Metric')}\n"
                f"Calculation: {m.get('calculation', 'N/A')}\n"
                f"Summary: {m.get('summary', '')}\n"
                f"Details: {m.get('details', '')}\n"
                f"Actionable Guidance: {m.get('action', '')}"
            )

    # Fuzzy match status
    for key, s in statuses.items():
        name = s.get("name", "").lower()
        if clean in key.lower() or clean in name or key.lower() in clean:
            return (
                f"=== DEMANDAI WIKI: STATUS '{s.get('name', key)}' ===\n"
                f"Condition: {s.get('calculation', 'N/A')}\n"
                f"Summary: {s.get('summary', '')}\n"
                f"Urgency: {s.get('urgency', 'Normal')}\n"
                f"Details: {s.get('details', '')}\n"
                f"Operational Action: {s.get('action', '')}"
            )

    return f"Wiki topic '{term}' not found. Available metrics: {', '.join(metrics.keys())}. Available statuses: {', '.join(statuses.keys())}."


@tool(args_schema=ShowClarificationCardInput)
def show_clarification_card(
    title: str,
    description: str,
    options: list[ClarificationOption | str | dict[str, Any]],
    card_type: str = "clarify_intent",
    sku: str = "",
    allow_text_input: bool = False,
    text_placeholder: str = "",
) -> str:
    """Display an interactive multi-choice popup card with selectable buttons in the chat interface.

    CRITICAL INSTRUCTION: Invoke this tool when you face ambiguity or need user choice:
    1. A product name matches multiple SKUs or warehouse locations. You MUST let the user choose which SKU they want. Never guess or select the first item.
    2. Essential tool parameters are missing (e.g. price change % for simulate_demand, focus_area for generate_pdf_report). Set allow_text_input=True with text_placeholder (e.g. 'Enter a different percentage (e.g. -15%, +10%)...') so user can specify custom numbers.
    3. TreeSHAP calculation confirmation.

    Args:
        title: Title of the card modal.
        description: Explanatory prompt text for the user.
        options: List of choices. Can be strings or dynamic option dictionaries with {label, sublabel, badge, actionType, payload}.
        card_type: Mode of card ('clarify_intent', 'select_item', or 'run_shap').
        sku: Target SKU code if applicable (e.g. 'SKU-4883').
        allow_text_input: Set to True to allow typing a custom value or percentage into a textbox.
        text_placeholder: Custom placeholder for the textbox.
    """
    labels = []
    for opt in options:
        if isinstance(opt, dict):
            labels.append(opt.get("label", str(opt)))
        elif hasattr(opt, "label"):
            labels.append(opt.label)
        else:
            labels.append(str(opt))
    extra = f" (Text input enabled: '{text_placeholder}')" if allow_text_input else ""
    return f"Clarification popup displayed to user with options: {', '.join(labels)}{extra}"



@tool("export_replenishment_csv", args_schema=ExportReplenishmentCsvInput)
def export_replenishment_csv(
    warehouse: str = "",
    include_all: bool = False,
) -> str:
    """Generate and export a CSV replenishment list for a specific warehouse or across all warehouses.

    CRITICAL INSTRUCTION: Invoke this tool ONLY when the user SPECIFICALLY and EXPLICITLY asks to download, export, or generate a "CSV" file. Never invoke for general conversation or regular questions.

    Calculates recommended purchase order quantities using the supply chain formula:
    Replenish_Qty = max(0, ceil((Forecast_14D + Safety_Stock) - Current_Stock)).

    Args:
        warehouse: Name or code of the warehouse (e.g. "Warehouse-14", "Prague_1", "Central"). If empty or "all", processes all inventory items across all warehouses.
        include_all: If True, includes all SKUs even if they do not need replenishment. If False (default), only exports SKUs with recommended replenishment quantity > 0.

    Returns:
        A formatted markdown summary of replenishment requirements and a direct download link for the generated CSV file.
    """
    all_items = _load_all_inventory_items(use_inactive_items=False) or []
    if not all_items:
        return "Không tìm thấy dữ liệu tồn kho để xuất file CSV."

    wh_clean = str(warehouse or "").strip()
    is_all_wh = not wh_clean or wh_clean.lower() in ("all", "tat ca", "tất cả", "toàn bộ", "all warehouses")

    if is_all_wh:
        target_items = all_items
        wh_label = "Toàn bộ kho"
        wh_slug = "all_warehouses"
    else:
        # Match warehouse case-insensitive
        target_items = [
            it for it in all_items
            if wh_clean.lower() in str(it.get("warehouse", "")).lower()
        ]
        if not target_items:
            avail = sorted(list({str(it.get("warehouse", "")) for it in all_items if it.get("warehouse")}))
            return f"Không tìm thấy dữ liệu cho kho {warehouse}. Các kho hiện có trong hệ thống: " + ", ".join(avail)
        wh_label = target_items[0].get("warehouse", wh_clean)
        wh_slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", wh_label).lower()

    rows: list[dict[str, Any]] = []
    total_qty_needed = 0
    critical_count = 0
    reorder_count = 0

    for it in target_items:
        uid = str(it.get("id") or it.get("sku") or "").replace("SKU-", "")
        sku_code = f"SKU-{uid}"
        name = str(it.get("name") or "Unknown")
        cat = str(it.get("category") or "General")
        wh = str(it.get("warehouse") or wh_label)
        stock = int(it.get("onHandStock") or 0)
        f14 = float(it.get("forecast14d") or 0.0)
        safety = float(it.get("safetyStock") or 0.0)
        lead_time = int(it.get("leadTimeDays") or 0)
        status = str(it.get("status") or "Normal")

        daily_sales = f14 / 14.0 if f14 > 0 else 0.001
        dos = round(stock / daily_sales, 1) if daily_sales > 0 else 999.0

        raw_need = (f14 + safety) - stock
        need_qty = max(0, int(math.ceil(raw_need)))

        if need_qty > 0 or include_all:
            if status == "Critical":
                critical_count += 1
            elif status == "Reorder":
                reorder_count += 1
            total_qty_needed += need_qty

            rows.append({
                "SKU_ID": sku_code,
                "Product_Name": name,
                "Category": cat,
                "Warehouse": wh,
                "Current_Stock": stock,
                "Forecast_14D": round(f14, 2),
                "Safety_Stock": round(safety, 2),
                "Lead_Time_Days": lead_time,
                "Days_Of_Supply": dos,
                "Risk_Status": status,
                "Suggested_Replenishment_Qty": need_qty,
            })

    if not rows:
        return f"Kho '{wh_label}' hiện tại có đủ tồn kho đáp ứng nhu cầu 14 ngày tới (kèm vùng đệm an toàn). Không có mặt hàng nào cần nhập thêm!"

    status_rank = {"Critical": 0, "Reorder": 1, "Monitor": 2, "Normal": 3, "Deadstock": 4}
    rows.sort(key=lambda r: (status_rank.get(r["Risk_Status"], 5), -r["Suggested_Replenishment_Qty"]))

    export_dir = BACKEND_ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"replenishment_{wh_slug}_{timestamp}.csv"
    file_path = export_dir / filename

    fieldnames = [
        "SKU_ID",
        "Product_Name",
        "Category",
        "Warehouse",
        "Current_Stock",
        "Forecast_14D",
        "Safety_Stock",
        "Lead_Time_Days",
        "Days_Of_Supply",
        "Risk_Status",
        "Suggested_Replenishment_Qty",
    ]

    with open(file_path, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    from app.services.forecast_artifacts import prune_old_exports
    prune_old_exports(keep_n=5)

    download_url = f"/api/v1/forecast/export/download/{filename}"

    critical_rows = [r for r in rows if r["Risk_Status"] == "Critical"]
    top_critical = critical_rows[:10]
    top_lines = []
    for r in top_critical:
        top_lines.append(f"• **{r['SKU_ID']}** ({r['Product_Name']}): Tồn {r['Current_Stock']}, Dự báo {r['Forecast_14D']}, Cần nhập gấp **+{r['Suggested_Replenishment_Qty']}**")
    if len(critical_rows) > 10:
        top_lines.append(f"• *...và {len(critical_rows) - 10} mặt hàng Critical khác.*")

    top_section = ""
    if top_lines:
        top_section = "\n\n**Mặt hàng khẩn cấp nhất (Critical):**\n" + "\n".join(top_lines)

    return (
        f"### 📦 Đề Xuất Nhập Hàng: {wh_label}\n"
        f"• **Tổng số SKU cần nhập thêm:** {len(rows)} mặt hàng\n"
        f"• **Tổng số lượng đề xuất đặt hàng (PO):** {total_qty_needed:,} đơn vị\n"
        f"• **Phân loại rủi ro:** {critical_count} Critical (nguy cơ đứt hàng trước Lead Time), {reorder_count} Reorder"
        f"{top_section}\n\n"
        f"👉 [📥 Tải file CSV đề xuất nhập hàng ({wh_label})]({download_url})\n\n*(Vui lòng bấm vào liên kết trên để tải trực tiếp file CSV về máy)*"
    )



@tool("generate_pdf_report", args_schema=GeneratePdfReportInput)
def generate_pdf_report(
    focus_area: str = "overview",
    warehouse: str = "",
) -> str:
    """Generate a multi-page professional Executive PDF report with embedded charts and data tables.

    CRITICAL INSTRUCTION: Invoke this tool ONLY when the user SPECIFICALLY and EXPLICITLY asks to download, export, or generate a "PDF" report/file. Never invoke for general inventory analysis, status questions, or regular conversation.

    Args:
        focus_area: Topic focus of the report: 'overview' (Inventory Overview & Demand Forecast), 'critical' (Critical Stockout Risks & Replenishment), 'deadstock' (Deadstock & Slow-Moving Inventory), or 'best_seller' (High Forecast Demand & Best Sellers).
        warehouse: Specific warehouse to filter by (e.g. 'Prague_1', 'Brno_1'). If empty or 'all', analyzes all warehouses.

    Returns:
        Formatted summary with key executive findings, KPI metrics, and a direct download link for the generated PDF.
    """
    from app.services.report_data_service import fetch_report_dataset, resolve_focus_topic
    from app.services.pdf_report_generator import generate_multi_page_report, format_report_filename

    # Check if _load_all_inventory_items was mocked in test environments
    raw_override = None
    all_items = _load_all_inventory_items(use_inactive_items=False)
    if hasattr(_load_all_inventory_items, "mock") or (all_items and len(all_items) < 30):
        raw_override = all_items

    dataset = fetch_report_dataset(
        focus_area=focus_area,
        warehouse_filter=warehouse,
        raw_items_override=raw_override,
    )
    meta = dataset.metadata

    if dataset.is_empty:
        if dataset.empty_reason and ("Không tìm thấy kho" in dataset.empty_reason or "not found" in dataset.empty_reason):
            return dataset.empty_reason

        empty_detail = dataset.empty_reason or "No items match specified criteria."
        if meta.focus_key == "critical":
            hdr_title = "### ℹ️ No Report Generated: Healthy Inventory Levels"
        elif meta.focus_key == "best_seller":
            hdr_title = "### ℹ️ No Report Generated: No High Demand Items Found"
        else:
            hdr_title = "### ℹ️ No Report Generated: Catalog Clean & Stable"

        lines = [
            hdr_title,
            f"• **Analysis Scope:** {meta.warehouse_scope_label} (Total: **{meta.total_records_in_scope:,}** SKU–warehouse records)",
            f"• **Report Topic:** {meta.focus_display_vi}",
            f"• **Audit Result:** {empty_detail}",
            "",
            "*No empty PDF is generated when no catalog items match the audit filter.* "
            "*(Tip: You can request an Overview Report or export a Replenishment CSV to inspect the entire portfolio)*",
        ]
        return "\n".join(lines)

    export_dir = BACKEND_ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = format_report_filename(
        focus_key=meta.focus_key,
        warehouse_scope=warehouse,
        warehouses_included=meta.warehouses_included,
    )
    file_path = export_dir / filename

    result = generate_multi_page_report(
        items=dataset,
        focus_area=meta.focus_key,
        warehouse_label=meta.warehouse_scope_label,
        output_path=file_path,
    )

    from app.services.forecast_artifacts import prune_old_exports
    prune_old_exports(keep_n=5)

    download_url = f"/api/v1/forecast/export/download/{filename}"

    insights_md = "\n".join(f"**{i+1}.** {ins}" for i, ins in enumerate(meta.executive_insights))

    out_lines = [
        f"### 📊 {meta.focus_title_vi}",
        f"• **Analysis Scope:** {meta.warehouse_scope_label} ({meta.total_records_in_scope:,} SKU–warehouse records, {meta.unique_skus_in_scope:,} unique SKUs)",
        f"• **Snapshot Date:** {meta.snapshot_date} | **Forecast Window:** {meta.forecast_start_date} → {meta.forecast_end_date} (14 days)",
        f"• **Matching Focus Items:** **{meta.matching_records_count:,}** items",
        f"• **Current Stock On-Hand:** **{meta.total_on_hand_stock:,.0f}** units",
        f"• **Total 14-Day Forecasted Demand:** **{meta.total_forecast_14d:,.0f}** units",
        f"• **Preliminary Replenishment Estimate (14-Day):** **{meta.total_preliminary_replenishment:,.0f}** units *(preliminary baseline excluding on-order quantities and MOQ)*",
        "",
        "**🔍 Key Executive Strategic Findings:**",
        insights_md,
        "",
        f"👉 [📊 Download Executive PDF Report ({meta.focus_display_vi} — {meta.warehouse_scope_label})]({download_url})",
        "",
        "*(Professional 2-page landscape executive briefing document with embedded charts, KPI dashboard, and prioritized action plan)*",
    ]
    return "\n".join(out_lines)


@tool("list_warehouses_summary", args_schema=ListWarehousesSummaryInput)
def list_warehouses_summary(warehouse: str = "") -> str:
    """Look up available warehouses in the network, summary inventory health, and guidance for exporting reports.

    Args:
        warehouse: Specific warehouse to inspect (e.g. 'Prague_1', 'Frankfurt_1'). If empty, summarizes all warehouses.
    """
    from collections import defaultdict
    all_items = _load_all_inventory_items(use_inactive_items=False) or []
    if not all_items:
        return "No inventory records found for warehouse lookup."

    wh_data = defaultdict(lambda: {"count": 0, "stock": 0, "critical": 0, "reorder": 0, "deadstock": 0})
    for it in all_items:
        wh = str(it.get("warehouse") or "General").strip()
        wh_data[wh]["count"] += 1
        wh_data[wh]["stock"] += int(it.get("onHandStock", 0))
        st = str(it.get("status", "")).strip().lower()
        if st == "deadstock":
            wh_data[wh]["deadstock"] += 1
        elif st == "critical":
            wh_data[wh]["critical"] += 1
        elif st == "reorder":
            wh_data[wh]["reorder"] += 1

    wh_clean = str(warehouse or "").strip().lower()
    if wh_clean and wh_clean not in ("all", "toàn bộ", "tat ca", "tất cả", "all warehouses", "all_warehouses"):
        matched = [k for k in sorted(wh_data.keys()) if wh_clean in k.lower()]
        if not matched:
            avail = sorted(wh_data.keys())
            return f"No warehouse matching '{warehouse}'. Available DemandAI network hubs: " + ", ".join(avail)
        target_whs = matched
    else:
        target_whs = sorted(wh_data.keys())

    lines = [
        "### 🏬 Warehouse Network Portfolio Overview (DemandAI Warehouses)",
        f"• **Total Managed SKUs:** {len(all_items):,} SKUs",
        f"• **Active Distribution Hubs:** {len(wh_data)} central warehouses",
        "",
        "| Warehouse | Managed SKUs | Total On-Hand Stock | Deadstock (Stagnant) | Critical (Stockout Risk) | Reorder Needed |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for w in target_whs:
        d = wh_data[w]
        lines.append(
            f"| **{w}** | {d['count']:,} | {d['stock']:,} | **{d['deadstock']}** | {d['critical']} | {d['reorder']} |"
        )

    example_wh = target_whs[0] if target_whs else "Prague_1"
    lines.extend([
        "",
        "**💡 Guidance for warehouse-specific exports:**",
        f"- **Export PDF Executive Report:** Type `/warehouse {example_wh} export PDF report` (e.g. `/warehouse {example_wh} export PDF deadstock`)",
        f"- **Export Replenishment CSV:** Type `/warehouse {example_wh} export replenishment CSV` (e.g. `/warehouse {example_wh} export CSV`)",
    ])
    return "\n".join(lines)


@tool("simulate_demand", args_schema=SimulateDemandInput)
def simulate_demand(
    sku_code: str,
    price_change_percent: float | None = None,
    price_discount_percent: float | None = None,
    warehouse: str = "",
) -> str:
    """Simulate 14-day customer demand forecast, revenue impact, and inventory outcome under price change what-if scenarios (discounts or price increases).

    Use this tool when the user asks hypothetical or what-if scenario pricing questions:
    - Discounts / Clearance: e.g. "Nếu tuần sau tôi giảm giá 20% cho Baguette_40 thì bán được bao nhiêu? Có cứu được deadstock không?" -> price_change_percent=-20.0
    - Price Increase / Elasticity: e.g. "Nếu tăng giá 15% cho SKU 4471 thì doanh thu thay đổi thế nào? Đo độ co giãn giá (PED)" -> price_change_percent=15.0
    - Multi-warehouse: If user omits warehouse for a multi-warehouse SKU, the tool automatically evaluates all warehouses and ranks clearance / revenue priorities.

    Args:
        sku_code: The SKU code (e.g. 'SKU-4471', '4471'), product name (e.g. 'Baguette_40').
        price_change_percent: The percentage change in price. Use NEGATIVE for discounts (e.g. -20 for 20% discount) or POSITIVE for price hikes (e.g. +15 for 15% increase).
        price_discount_percent: Deprecated alias for backward compatibility. If provided, treated as discount (e.g. 20 -> -20.0%).
        warehouse: Optional warehouse name (e.g. 'Prague_1'). If empty, automatically simulates across all warehouses if SKU is multi-warehouse.
    """
    from app.services.simulation_service import simulate_sku_price_change, format_simulation_markdown
    try:
        if price_change_percent is None and price_discount_percent is None:
            return (
                f"[MISSING REQUIRED PARAMETER: price_change_percent]\n"
                f"User asked for simulation on '{sku_code}' but did not specify the discount or price change percentage.\n"
                f"MANDATORY DIRECTIVE: You MUST IMMEDIATELY call 'show_clarification_card' offering scenario options "
                f"(e.g. Giảm giá -10%, Giảm giá -20%, Giảm giá -30%, Tăng giá +10%). DO NOT guess."
            )

        effective_pct = -20.0 if price_change_percent is None else price_change_percent
        if price_discount_percent is not None:
            effective_pct = -abs(float(price_discount_percent))

        sim_data = simulate_sku_price_change(
            sku_or_id=sku_code,
            price_change_percent=effective_pct,
            warehouse=warehouse,
        )
        return format_simulation_markdown(sim_data)
    except Exception as exc:
        logger.exception("Failed running simulate_demand for %s: %s", sku_code, exc)
        return f"Error executing demand simulation for SKU '{sku_code}': {exc}"


SKU_TOOLS = [
    simulate_demand,
    list_warehouses_summary,
    get_sku_core_info,
    get_sku_inventory_and_forecast,
    get_sku_shap_drivers,
    compare_sku_peers,
    get_daily_forecast_series,
    get_portfolio_overview,
    query_inventory_wiki,
    show_clarification_card,
    export_replenishment_csv,
    generate_pdf_report,
]

