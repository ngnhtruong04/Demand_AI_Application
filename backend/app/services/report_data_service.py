"""report_data_service.py — Data normalization and business calculation engine for Executive PDF & CSV reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import math
import re
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from app.core.config import BACKEND_ROOT
from app.db.session import SessionLocal, engine
from app.services.forecast_persistence import compute_dynamic_status, get_inactive_uids

# Canonical topic configurations
REPORT_TOPICS: dict[str, dict[str, str]] = {
    "overview": {
        "id": "overview",
        "title_vi": "INVENTORY OVERVIEW & 14-DAY DEMAND FORECAST REPORT",
        "subtitle_en": "PORTFOLIO INVENTORY STATUS & 14-DAY DEMAND FORECAST",
        "display_vi": "Inventory Overview & Forecast",
        "title_en": "INVENTORY OVERVIEW & 14-DAY DEMAND FORECAST REPORT",
        "display_en": "Inventory Overview & Forecast",
        "theme_color": "#1d4ed8",  # Royal Blue
    },
    "critical": {
        "id": "critical",
        "title_vi": "CRITICAL STOCKOUT RISKS & REPLENISHMENT ACTION REPORT",
        "subtitle_en": "CRITICAL STOCKOUT RISKS & 14-DAY REPLENISHMENT ACTION PLAN",
        "display_vi": "Critical Stockout & Replenishment",
        "title_en": "CRITICAL STOCKOUT RISKS & REPLENISHMENT ACTION REPORT",
        "display_en": "Critical Stockout & Replenishment",
        "theme_color": "#ea580c",  # Amber / Orange
    },
    "deadstock": {
        "id": "deadstock",
        "title_vi": "SLOW-MOVING & DEADSTOCK CAPITAL EFFICIENCY REPORT",
        "subtitle_en": "SLOW-MOVING & EXCESS INVENTORY CAPITAL EFFICIENCY ANALYSIS",
        "display_vi": "Deadstock & Slow-Moving Inventory",
        "title_en": "SLOW-MOVING & DEADSTOCK CAPITAL EFFICIENCY REPORT",
        "display_en": "Deadstock & Slow-Moving Inventory",
        "theme_color": "#d21d0a",
    },
    "best_seller": {
        "id": "best_seller",
        "title_vi": "HIGH FORECAST DEMAND & BEST SELLERS MONITOR REPORT",
        "subtitle_en": "HIGH FORECAST DEMAND ITEMS & STOCK AVAILABILITY MONITOR",
        "display_vi": "High Forecast Demand & Best Sellers",
        "title_en": "HIGH FORECAST DEMAND & BEST SELLERS MONITOR REPORT",
        "display_en": "High Forecast Demand & Best Sellers",
        "theme_color": "#4da20c",
    },
}

SYSTEM_KNOWN_WAREHOUSES = [
    "Brno_1",
    "Budapest_1",
    "Frankfurt_1",
    "Munich_1",
    "Prague_1",
    "Prague_2",
    "Prague_3",
]


@dataclass
class ReportMetadata:
    focus_key: str
    focus_title_vi: str
    focus_subtitle_en: str
    focus_display_vi: str
    theme_color: str
    warehouse_scope_label: str
    warehouses_included: list[str]
    snapshot_date: Optional[str]
    forecast_start_date: Optional[str]
    forecast_end_date: Optional[str]
    forecast_horizon_days: int
    run_id: Optional[str]
    model_version: Optional[str]
    export_timestamp: str
    timezone_name: str
    data_source: str
    is_demo: bool
    total_records_in_scope: int
    unique_skus_in_scope: int
    matching_records_count: int
    missing_data_count: int
    inactive_excluded_count: int
    risk_distribution: dict[str, int]
    total_on_hand_stock: int
    total_forecast_14d: float
    total_preliminary_replenishment: int
    executive_insights: list[str]


@dataclass
class ProcessedReportItem:
    unique_id: str
    sku: str
    name: str
    category: str
    warehouse: str
    current_stock: int
    forecast_14d: Optional[float]
    daily_forecast: Optional[float]
    days_of_supply: Optional[float]
    dos_display: str
    lead_time_days: int
    safety_stock: float
    baseline_rop: float
    dynamic_rop: float
    suggested_replenishment_14d: Optional[int]
    status: str
    depletion_risk_day: str
    lead_time_warning: Optional[str]
    alert_reason: str
    recommended_action: str


@dataclass
class ReportDataset:
    metadata: ReportMetadata
    items: list[ProcessedReportItem]
    top_action_items: list[ProcessedReportItem]
    is_empty: bool
    empty_reason: Optional[str] = None


def resolve_focus_topic(focus_area: str) -> dict[str, str]:
    """Canonicalize topic identifier strictly preserving compatibility."""
    cleaned = str(focus_area or "overview").strip().lower()
    if "dead" in cleaned or "thừa" in cleaned or "chậm" in cleaned:
        return REPORT_TOPICS["deadstock"]
    elif any(w in cleaned for w in ["crit", "stockout", "reorder", "thiếu", "cạn", "bổ sung", "khẩn cấp"]):
        return REPORT_TOPICS["critical"]
    elif any(w in cleaned for w in ["best", "sale", "cao", "nhu cầu"]):
        return REPORT_TOPICS["best_seller"]
    return REPORT_TOPICS["overview"]


def resolve_warehouse_filter(
    warehouse_input: str,
    available_warehouses: Optional[list[str]] = None,
) -> tuple[list[str], str, Optional[str]]:
    """Strict warehouse resolver preventing substring crosstalk (e.g. Prague_1 vs Prague_2).
    
    Returns:
        (matching_warehouses_list, display_label, error_message)
    """
    avail = available_warehouses or SYSTEM_KNOWN_WAREHOUSES
    target = str(warehouse_input or "").strip()

    if not target or target.lower() in ("all", "all warehouses", "tat ca", "tất cả", "toàn bộ", "toàn bộ kho"):
        return sorted(avail), f"Entire Warehouse Network ({len(avail)} Warehouses)", None

    # 1. Exact match (case-insensitive)
    for w in avail:
        if w.lower() == target.lower():
            return [w], w, None

    # 2. Check if user typed a warehouse base name like "Prague" which matches multiple
    matching = [w for w in avail if target.lower() in w.lower()]
    if len(matching) == 1:
        return matching, matching[0], None
    elif len(matching) > 1:
        # Multiple warehouses match substring -> Ambiguous! Require exact specification
        return (
            [],
            target,
            f"Warehouse name '{target}' is ambiguous (matches {len(matching)} warehouses: {', '.join(matching)}). Please specify exact warehouse name.",
        )

    return (
        [],
        target,
        f"Warehouse '{target}' not found. Available warehouses: {', '.join(sorted(avail))}",
    )


def calculate_item_metrics(
    raw: dict[str, Any],
    daily_points: Optional[list[dict[str, Any]]] = None,
) -> ProcessedReportItem:
    """Standardized metric calculator adhering strictly to business equations:
    
    Daily Velocity = 14d Forecast / 14
    Days of Supply = On-hand Stock / Daily Velocity
    Dynamic ROP = (Daily Velocity * Lead Time) + Safety Stock
    Preliminary Replenishment = max(0, ceil(14d Forecast + Safety Stock - On-hand Stock))
    """
    uid = str(raw.get("unique_id") or raw.get("id") or "")
    sku = str(raw.get("sku") or f"SKU-{uid}")
    name = str(raw.get("name") or "Unknown Item")
    category = str(raw.get("category") or "General")
    warehouse = str(raw.get("warehouse") or "Unknown Warehouse")

    # Current stock (physical on-hand, not sellable without reservation data)
    raw_stock = raw.get("current_stock")
    if raw_stock is None:
        raw_stock = raw.get("onHandStock")
    current_stock = int(raw_stock) if raw_stock is not None else 0

    lead_time_days = int(raw.get("lead_time_days") or raw.get("leadTimeDays") or 0)
    safety_stock = float(raw.get("safety_stock") or raw.get("safetyStock") or 0.0)
    baseline_rop = float(raw.get("baseline_reorder_point") or raw.get("reorderPoint") or 0.0)

    raw_f14 = raw.get("forecast_14d")
    if raw_f14 is None:
        raw_f14 = raw.get("forecast14d")

    # Strict distinction between f14=0, missing forecast (None), and negative
    if raw_f14 is None:
        forecast_14d = None
        daily_forecast = None
        days_of_supply = None
        dos_display = "Missing Data"
        dynamic_rop = baseline_rop
        suggested_replenishment = None
    else:
        forecast_14d = float(raw_f14)
        daily_forecast = forecast_14d / 14.0

        if daily_forecast == 0:
            days_of_supply = None
            dos_display = "N/A (Zero Demand)"
        elif daily_forecast > 0:
            days_of_supply = current_stock / daily_forecast
            dos_display = f"{days_of_supply:.1f} days"
        else:
            days_of_supply = None
            dos_display = "Dự báo không hợp lệ"

        # Dynamic ROP calculation (no intermediate rounding)
        if daily_forecast >= 0:
            calc_rop = (daily_forecast * lead_time_days) + safety_stock
            dynamic_rop = float(round(calc_rop, 2))
        else:
            dynamic_rop = baseline_rop

        # Preliminary replenishment estimate for 14-day cycle
        net_requirement = forecast_14d + safety_stock - current_stock
        suggested_replenishment = max(0, math.ceil(net_requirement))

    # Status determination (prioritize official system classification)
    status = str(raw.get("status") or raw.get("scenario_group") or "In Stock")
    if forecast_14d is not None and status not in ("In Stock", "Monitor", "Reorder", "Critical", "Deadstock"):
        computed_st, _ = compute_dynamic_status(
            stock=current_stock,
            f14d=forecast_14d,
            safety_stock=safety_stock,
            baseline_rop=baseline_rop,
            lead_time=lead_time_days,
        )
        status = computed_st

    # Depletion risk day from daily points
    depletion_risk_day = "No daily time-series data"
    if daily_points and current_stock >= 0 and forecast_14d and forecast_14d > 0:
        cum_demand = 0.0
        crashed_day = None
        for pt in daily_points:
            pred = float(pt.get("predicted_sales") or pt.get("predicted") or 0.0)
            cum_demand += pred
            if cum_demand >= current_stock:
                crashed_day = pt.get("date") or f"Day {pt.get('day', pt.get('horizon_day', '?'))}"
                break
        if crashed_day:
            depletion_risk_day = f"Projected stockout on {crashed_day}"
        else:
            depletion_risk_day = "No stockout projected in 14-day window"
    elif forecast_14d == 0:
        depletion_risk_day = "No forecasted demand"

    # Lead time constraint warning
    lead_time_warning = None
    if lead_time_days > 14:
        lead_time_warning = f"Lead time ({lead_time_days} days) exceeds 14-day forecast window; extended planning required."

    # Explanations & Action Recommendations
    replenish_str = f"{suggested_replenishment:,} units" if suggested_replenishment is not None else "N/A"
    if status == "Critical":
        alert_reason = f"Stock ({current_stock:,}) breached safety buffer ({safety_stock:.0f}). DOS: {dos_display}."
        recommended_action = f"Prioritize warehouse transfer or expedite shipment. Est. replenishment: {replenish_str}."
    elif status == "Reorder":
        alert_reason = f"Stock ({current_stock:,}) below dynamic ROP ({dynamic_rop:.0f}). Risk of stockout before arrival (Lead time: {lead_time_days}d)."
        recommended_action = f"Issue replenishment order immediately. Est. replenishment: {replenish_str}."
    elif status == "Deadstock":
        alert_reason = f"Stock ({current_stock:,}) on hand with near-zero forecasted demand (DOS: {dos_display})."
        recommended_action = f"Halt reorders; liquidate or transfer to active warehouses to free up working capital."
    elif status == "Monitor":
        alert_reason = f"Stock approaching reorder threshold (within 20% above dynamic ROP)."
        recommended_action = f"Track daily outbound depletion; confirm supplier lead times."
    else:
        alert_reason = f"Stock healthy, above dynamic ROP ({dynamic_rop:.0f}) and safety buffer."
        recommended_action = f"Maintain regular supply cadence; no replenishment action needed."

    return ProcessedReportItem(
        unique_id=uid,
        sku=sku,
        name=name,
        category=category,
        warehouse=warehouse,
        current_stock=current_stock,
        forecast_14d=forecast_14d,
        daily_forecast=daily_forecast,
        days_of_supply=days_of_supply,
        dos_display=dos_display,
        lead_time_days=lead_time_days,
        safety_stock=safety_stock,
        baseline_rop=baseline_rop,
        dynamic_rop=dynamic_rop,
        suggested_replenishment_14d=suggested_replenishment,
        status=status,
        depletion_risk_day=depletion_risk_day,
        lead_time_warning=lead_time_warning,
        alert_reason=alert_reason,
        recommended_action=recommended_action,
    )


def build_executive_insights(
    topic_id: str,
    meta: dict[str, Any],
    all_scope_items: list[ProcessedReportItem],
    matched_items: list[ProcessedReportItem],
) -> list[str]:
    """Generate 3 to 5 realistic, deterministic executive insights derived strictly from aggregated numbers."""
    total_scope = len(all_scope_items)
    if total_scope == 0:
        return ["No inventory records found within analysis scope."]

    total_stock_all = sum(it.current_stock for it in all_scope_items)
    total_f14_all = sum(it.forecast_14d or 0.0 for it in all_scope_items)

    risk_counts = {
        "Critical": sum(1 for it in all_scope_items if it.status == "Critical"),
        "Reorder": sum(1 for it in all_scope_items if it.status == "Reorder"),
        "Monitor": sum(1 for it in all_scope_items if it.status == "Monitor"),
        "In Stock": sum(1 for it in all_scope_items if it.status == "In Stock"),
        "Deadstock": sum(1 for it in all_scope_items if it.status == "Deadstock"),
    }
    crit_reorder_cnt = risk_counts["Critical"] + risk_counts["Reorder"]
    crit_pct = (crit_reorder_cnt / total_scope) * 100 if total_scope else 0.0
    deadstock_cnt = risk_counts["Deadstock"]
    dead_pct = (deadstock_cnt / total_scope) * 100 if total_scope else 0.0

    total_replenish_scope = sum(it.suggested_replenishment_14d or 0 for it in all_scope_items)

    insights: list[str] = []

    # 1. Scale and Aggregate Flow
    insights.append(
        f"Review scope covers {total_scope:,} SKU–warehouse records ({meta.get('unique_skus', total_scope):,} unique SKUs). "
        f"Total stock on-hand is {total_stock_all:,.0f} units, meeting total 14-day forecasted demand of {total_f14_all:,.0f} units."
    )

    # 2. Risk Distribution
    insights.append(
        f"Inventory risk breakdown: {risk_counts['Critical']} Critical and {risk_counts['Reorder']} Reorder items, "
        f"accounting for {crit_pct:.1f}% of catalog. {deadstock_cnt} items ({dead_pct:.1f}%) are classified as slow-moving/excess (Deadstock)."
    )

    # 3. Replenishment Requirement
    if crit_reorder_cnt > 0:
        crit_reorder_replenish = sum(
            it.suggested_replenishment_14d or 0 for it in all_scope_items if it.status in ("Critical", "Reorder")
        )
        insights.append(
            f"Preliminary replenishment requirement for at-risk items (Critical + Reorder) is {crit_reorder_replenish:,.0f} units "
            f"(portfolio total: {total_replenish_scope:,.0f} units). Note: Theoretical baseline excluding on-order quantities and MOQ."
        )
    else:
        insights.append(
            "No items currently in Critical stockout status at inventory snapshot."
        )

    # 4. Lead time constraint & short-term depletion
    lead_time_exceeded = [it for it in all_scope_items if it.lead_time_days > 14]
    if lead_time_exceeded:
        insights.append(
            f"{len(lead_time_exceeded)} items have supplier lead times exceeding the 14-day forecast window (up to {max(it.lead_time_days for it in lead_time_exceeded)} days); "
            f"medium-term planning recommended."
        )
    else:
        rapid_deplete = [it for it in all_scope_items if it.days_of_supply is not None and it.days_of_supply <= 3.0 and it.current_stock > 0]
        if rapid_deplete:
            insights.append(
                f"{len(rapid_deplete)} items have Days of Supply (DOS) below 3 days; immediate replenishment recommended to prevent stockouts."
            )
        else:
            insights.append(
                "All items in portfolio have supplier lead times within manageable 14-day operational horizons."
            )

    # 5. Focus-specific executive highlight
    if topic_id == "critical":
        top_crit = [it for it in matched_items if it.status == "Critical"]
        if top_crit:
            sample = top_crit[0]
            insights.append(
                f"Most urgent item: '{sample.name}' ({sample.sku}) at {sample.warehouse} "
                f"has only {sample.current_stock:,} units remaining (DOS: {sample.dos_display}, Lead time: {sample.lead_time_days} days, Dynamic ROP: {sample.dynamic_rop:.0f})."
            )
    elif topic_id == "deadstock":
        if matched_items:
            dead_stock_sum = sum(it.current_stock for it in matched_items)
            insights.append(
                f"Deadstock items tie up {dead_stock_sum:,.0f} physical units; "
                f"recommend commercial discounting or warehouse transfers to free working capital."
            )
    elif topic_id == "best_seller":
        if matched_items:
            top_best = matched_items[0]
            insights.append(
                f"Top demand leader: '{top_best.name}' ({top_best.sku}) at {top_best.warehouse} "
                f"with {top_best.forecast_14d:,.0f} units forecasted over 14 days (avg {top_best.daily_forecast:.1f} units/day). Current stock: {top_best.current_stock:,} units."
            )

    return insights[:5]


def fetch_report_dataset(
    focus_area: str = "overview",
    warehouse_filter: str = "",
    raw_items_override: Optional[list[dict[str, Any]]] = None,
    use_inactive_items: bool = False,
) -> ReportDataset:
    """Fetch, normalize, filter, and calculate complete dataset for Executive PDF/CSV reporting."""
    topic = resolve_focus_topic(focus_area)
    topic_id = topic["id"]

    # Current export timestamp in Vietnam Local Time (UTC+7)
    now_vn = datetime.now(timezone.utc).astimezone(timezone(datetime.now().astimezone().utcoffset() or timezone.utc.utcoffset(None)))
    export_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # If raw_items_override is passed (e.g. unit tests or pre-cached items)
    if raw_items_override is not None:
        avail_whs = sorted(list({str(it.get("warehouse", "")) for it in raw_items_override if it.get("warehouse")}))
        target_whs, wh_label, err_msg = resolve_warehouse_filter(warehouse_filter, avail_whs or SYSTEM_KNOWN_WAREHOUSES)
        if err_msg:
            empty_meta = ReportMetadata(
                focus_key=topic_id,
                focus_title_vi=topic["title_vi"],
                focus_subtitle_en=topic["subtitle_en"],
                focus_display_vi=topic["display_vi"],
                theme_color=topic["theme_color"],
                warehouse_scope_label=wh_label,
                warehouses_included=[],
                snapshot_date="Chưa xác định",
                forecast_start_date="Chưa xác định",
                forecast_end_date="Chưa xác định",
                forecast_horizon_days=14,
                run_id="Mock/Override",
                model_version="In-memory Test",
                export_timestamp=export_str,
                timezone_name="UTC+07:00 (Asia/Ho_Chi_Minh)",
                data_source="Dữ liệu kiểm thử / Override",
                is_demo=True,
                total_records_in_scope=0,
                unique_skus_in_scope=0,
                matching_records_count=0,
                missing_data_count=0,
                inactive_excluded_count=0,
                risk_distribution={},
                total_on_hand_stock=0,
                total_forecast_14d=0.0,
                total_preliminary_replenishment=0,
                executive_insights=[],
            )
            return ReportDataset(metadata=empty_meta, items=[], top_action_items=[], is_empty=True, empty_reason=err_msg)

        # Filter items by warehouse and inactive status
        inactive_set = get_inactive_uids() if not use_inactive_items else set()
        scope_raw = [
            it for it in raw_items_override
            if (not target_whs or str(it.get("warehouse", "")).strip() in target_whs)
            and (not inactive_set or str(it.get("unique_id") or it.get("id")) not in inactive_set)
        ]
        inactive_excluded_cnt = len(raw_items_override) - len(scope_raw) if not use_inactive_items else 0
        all_processed = [calculate_item_metrics(it, it.get("daily_points")) for it in scope_raw]
        metadata_source = "Bộ nhớ kiểm thử (Mock / Memory Dataset)"
        snap_date_str = "2024-06-03"
        f_start_str = "2024-06-03"
        f_end_str = "2024-06-16"
        active_run_id = "test-run"
        model_ver = "Test Model"
        is_demo_flag = True
    else:
        # Load directly from PostgreSQL database ensuring data consistency across tables
        with engine.connect() as conn:
            # 1. Fetch active / latest forecast run metadata
            run_query = """
                SELECT run_id, model_version, horizon_days, forecast_start_date, forecast_end_date, is_latest, created_at
                FROM core.forecast_runs
                ORDER BY is_latest DESC, created_at DESC
                LIMIT 1
            """
            run_row = conn.execute(text(run_query)).mappings().fetchone()

            active_run_id = str(run_row["run_id"]) if run_row else None
            model_ver = str(run_row["model_version"]) if run_row else "Chưa xác định"
            f_start_str = str(run_row["forecast_start_date"]) if run_row else "Chưa xác định"
            f_end_str = str(run_row["forecast_end_date"]) if run_row else "Chưa xác định"

            # 2. Get available warehouses from core.inventory
            db_whs = [r[0] for r in conn.execute(text("SELECT DISTINCT warehouse FROM core.inventory ORDER BY warehouse")).fetchall()]
            target_whs, wh_label, err_msg = resolve_warehouse_filter(warehouse_filter, db_whs or SYSTEM_KNOWN_WAREHOUSES)
            if err_msg:
                empty_meta = ReportMetadata(
                    focus_key=topic_id,
                    focus_title_vi=topic["title_vi"],
                    focus_subtitle_en=topic["subtitle_en"],
                    focus_display_vi=topic["display_vi"],
                    theme_color=topic["theme_color"],
                    warehouse_scope_label=wh_label,
                    warehouses_included=[],
                    snapshot_date="Chưa xác định",
                    forecast_start_date=f_start_str,
                    forecast_end_date=f_end_str,
                    forecast_horizon_days=14,
                    run_id=active_run_id,
                    model_version=model_ver,
                    export_timestamp=export_str,
                    timezone_name="UTC+07:00 (Asia/Ho_Chi_Minh)",
                    data_source="PostgreSQL RDS",
                    is_demo=False,
                    total_records_in_scope=0,
                    unique_skus_in_scope=0,
                    matching_records_count=0,
                    missing_data_count=0,
                    risk_distribution={},
                    total_on_hand_stock=0,
                    total_forecast_14d=0.0,
                    total_preliminary_replenishment=0,
                    executive_insights=[],
                )
                return ReportDataset(metadata=empty_meta, items=[], top_action_items=[], is_empty=True, empty_reason=err_msg)

            inactive_uids_list = list(get_inactive_uids()) if not use_inactive_items else []
            inactive_excluded_cnt = len(inactive_uids_list)

            # 3. Query combined inventory + snapshot + forecast item summary
            # Prevents duplicates by strictly joining snapshot_date = (SELECT MAX(snapshot_date) FROM core.inventory_snapshot)
            data_query = """
                SELECT 
                    inv.unique_id, 
                    inv.name, 
                    inv.warehouse, 
                    inv.l1_category_name_en as category,
                    snap.current_stock, 
                    snap.safety_stock, 
                    snap.baseline_reorder_point, 
                    snap.lead_time_days, 
                    COALESCE(s.scenario_group, snap.scenario_group) as scenario_group,
                    s.forecast_14d,
                    s.days_of_supply as db_dos,
                    snap.snapshot_date,
                    snap.is_demo
                FROM core.inventory inv
                JOIN core.inventory_snapshot snap ON inv.unique_id = snap.unique_id
                LEFT JOIN core.forecast_item_summary s ON inv.unique_id = s.unique_id AND s.run_id = :run_id
                WHERE snap.snapshot_date = (SELECT MAX(snapshot_date) FROM core.inventory_snapshot)
                """ + (" AND inv.warehouse = ANY(:wh_list)" if target_whs else "") + """
                """ + (" AND NOT (inv.unique_id = ANY(:inactive_uids))" if not use_inactive_items and inactive_uids_list else "") + """
                ORDER BY inv.unique_id
            """
            params: dict[str, Any] = {"run_id": active_run_id}
            if target_whs:
                params["wh_list"] = target_whs
            if not use_inactive_items and inactive_uids_list:
                params["inactive_uids"] = inactive_uids_list

            db_rows = conn.execute(text(data_query), params).mappings().fetchall()

            # 4. Query daily points for depletion date calculation
            daily_points_map: dict[str, list[dict[str, Any]]] = {}
            if active_run_id:
                pts_query = """
                    SELECT unique_id, date, horizon_day, predicted_sales
                    FROM core.forecast_daily_points
                    WHERE run_id = :run_id
                    ORDER BY unique_id, horizon_day
                """
                pts_rows = conn.execute(text(pts_query), {"run_id": active_run_id}).mappings().fetchall()
                for p in pts_rows:
                    u_id = str(p["unique_id"])
                    if u_id not in daily_points_map:
                        daily_points_map[u_id] = []
                    daily_points_map[u_id].append({
                        "day": p["horizon_day"],
                        "date": str(p["date"]),
                        "predicted_sales": float(p["predicted_sales"] or 0.0),
                    })

            snap_date_str = str(db_rows[0]["snapshot_date"]) if db_rows else "Chưa xác định"
            is_demo_flag = bool(db_rows[0]["is_demo"]) if db_rows else False
            metadata_source = "PostgreSQL RDS (core.forecast_runs, core.inventory, core.inventory_snapshot)"

            all_processed = [
                calculate_item_metrics(dict(r), daily_points_map.get(str(r["unique_id"])))
                for r in db_rows
            ]

    # Overall scope aggregations
    total_records = len(all_processed)
    unique_skus = len(set(it.unique_id for it in all_processed))
    missing_count = sum(1 for it in all_processed if it.forecast_14d is None or it.current_stock is None)

    risk_distribution = {
        "Critical": sum(1 for it in all_processed if it.status == "Critical"),
        "Reorder": sum(1 for it in all_processed if it.status == "Reorder"),
        "Monitor": sum(1 for it in all_processed if it.status == "Monitor"),
        "In Stock": sum(1 for it in all_processed if it.status == "In Stock"),
        "Deadstock": sum(1 for it in all_processed if it.status == "Deadstock"),
    }

    # Filter items matching the requested focus topic
    if topic_id == "deadstock":
        matched = [it for it in all_processed if it.status == "Deadstock"]
        matched.sort(key=lambda x: x.current_stock, reverse=True)
    elif topic_id == "critical":
        matched = [
            it for it in all_processed
            if it.status in ("Critical", "Reorder")
            or (it.daily_forecast is not None and it.daily_forecast > 0 and (it.days_of_supply or 999.0) <= 14.0)
            or (it.current_stock <= it.dynamic_rop)
        ]
        # Sort by urgency: lowest DOS first, then highest replenishment
        matched.sort(key=lambda x: (x.days_of_supply if x.days_of_supply is not None else 999.0, -(x.suggested_replenishment_14d or 0)))
    elif topic_id == "best_seller":
        matched = [it for it in all_processed if it.forecast_14d is not None and it.forecast_14d > 0]
        matched.sort(key=lambda x: x.forecast_14d or 0.0, reverse=True)
    else:  # overview
        matched = list(all_processed)
        # Sort overview prioritizing risk items first
        status_rank = {"Critical": 1, "Reorder": 2, "Deadstock": 3, "Monitor": 4, "In Stock": 5}
        matched.sort(key=lambda x: (status_rank.get(x.status, 6), -(x.forecast_14d or 0.0)))

    # Aggregates for matching items
    matched_stock = sum(it.current_stock for it in matched)
    matched_f14 = sum(it.forecast_14d or 0.0 for it in matched)
    matched_replenish = sum(it.suggested_replenishment_14d or 0 for it in matched)

    # Executive insights
    insights = build_executive_insights(
        topic_id=topic_id,
        meta={"unique_skus": unique_skus},
        all_scope_items=all_processed,
        matched_items=matched,
    )

    metadata = ReportMetadata(
        focus_key=topic_id,
        focus_title_vi=topic["title_vi"],
        focus_subtitle_en=topic["subtitle_en"],
        focus_display_vi=topic["display_vi"],
        theme_color=topic["theme_color"],
        warehouse_scope_label=wh_label,
        warehouses_included=target_whs,
        snapshot_date=snap_date_str,
        forecast_start_date=f_start_str,
        forecast_end_date=f_end_str,
        forecast_horizon_days=14,
        run_id=active_run_id,
        model_version=model_ver,
        export_timestamp=export_str,
        timezone_name="UTC+07:00 (Asia/Ho_Chi_Minh)",
        data_source=metadata_source,
        is_demo=is_demo_flag,
        total_records_in_scope=total_records,
        unique_skus_in_scope=unique_skus,
        matching_records_count=len(matched),
        missing_data_count=missing_count,
        inactive_excluded_count=inactive_excluded_cnt if 'inactive_excluded_cnt' in locals() else 0,
        risk_distribution=risk_distribution,
        total_on_hand_stock=matched_stock,
        total_forecast_14d=matched_f14,
        total_preliminary_replenishment=matched_replenish,
        executive_insights=insights,
    )

    if not matched:
        if topic_id == "critical":
            detail_msg = "Healthy Inventory Levels. No items in Critical or Reorder status across this scope."
        elif topic_id == "best_seller":
            detail_msg = "No items with positive forecasted demand found across this scope."
        elif topic_id == "deadstock":
            detail_msg = "Portfolio Clean. No slow-moving or excess inventory items found across this scope."
        else:
            detail_msg = f"No items matching focus topic found across this scope."

        empty_msg = (
            f"Analysis Scope: {wh_label} (Total: {total_records:,} SKU–warehouse records). "
            f"{detail_msg} "
            f"(Note: Reflects current inventory snapshot and forecast model run)."
        )
        return ReportDataset(
            metadata=metadata,
            items=[],
            top_action_items=[],
            is_empty=True,
            empty_reason=empty_msg,
        )

    # Top action items for executive summary table & charts (e.g. top 15)
    top_action = matched[:15]

    return ReportDataset(
        metadata=metadata,
        items=matched,
        top_action_items=top_action,
        is_empty=False,
    )
