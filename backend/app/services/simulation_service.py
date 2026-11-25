"""app.services.simulation_service — What-If Scenario Simulation Engine for DemandAI.

Runs real-time ML re-inference across 14 forecast horizons using preloaded
Ensemble models (LightGBM, XGBoost, CatBoost) to simulate external impacts
(e.g. price discounts for clearance, price increases for revenue elasticity, promotions)
on SKU demand and inventory clearance.

Supports both:
1. Single-warehouse deep-dive simulation.
2. Multi-warehouse comparative network simulation with inter-warehouse stock transfer analytics.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb

from app.core.config import BACKEND_ROOT, settings
from app.agent.tools import resolve_sku_item, find_all_warehouse_items_for_product
from app.pipeline.recursive_ensemble import get_global_models, MODELS_DIR
from app.services.forecast_artifacts import ARTIFACT_ROOT
from app.services.item_shap import get_run_horizons

CURRENCY = settings.default_currency_unit

logger = logging.getLogger(__name__)


def get_latest_valid_run_id(preferred_run_id: str | None = None) -> str | None:
    """Find the latest valid UUID run_id in ARTIFACT_ROOT that has all horizon pickles available."""
    from uuid import UUID
    if preferred_run_id:
        try:
            valid_uuid = str(UUID(str(preferred_run_id)))
            p = ARTIFACT_ROOT / valid_uuid
            if (p / "horizon-1.pickle").is_file():
                return valid_uuid
        except ValueError:
            pass

    if not ARTIFACT_ROOT.exists():
        return None

    candidates: list[tuple[float, str]] = []
    for entry in ARTIFACT_ROOT.iterdir():
        try:
            valid_uuid = str(UUID(entry.name))
        except ValueError:
            continue
        if entry.is_dir() and not entry.is_symlink():
            if (entry / "horizon-1.pickle").is_file() and (entry / "horizon-14.pickle").is_file():
                candidates.append((entry.stat().st_mtime, valid_uuid))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    return None


def simulate_single_sku_price_change(
    item: dict[str, Any],
    price_change_pct: float,
) -> dict[str, Any]:
    """Execute 14-day ML ensemble simulation for a single resolved SKU item under two-way price change.

    Args:
        item: Resolved SKU metadata dictionary.
        price_change_pct: Float percentage change. Negative = discount (e.g. -20.0), Positive = price increase (e.g. +15.0).
    """
    uid = str(item.get("id") or item.get("unique_id", ""))
    sku = str(item.get("sku", f"SKU-{uid}"))
    name = str(item.get("name", "Unknown Product"))
    wh = str(item.get("warehouse", "Central Warehouse"))
    category = str(item.get("category", "General"))

    current_stock = float(item.get("onHandStock", 0.0) or item.get("current_stock", 0.0) or 0.0)
    current_status = str(item.get("status", "In Stock"))
    safety_stock = float(item.get("safetyStock", 0.0) or 0.0)
    reorder_point = float(item.get("reorderPoint", 0.0) or 0.0)
    lead_time = int(item.get("leadTimeDays", 3) or 3)
    baseline_forecast_14d = float(item.get("forecast14d", 0.0) or 0.0)

    is_price_increase = price_change_pct > 0.0
    is_discount = price_change_pct < 0.0
    discount_pct = abs(price_change_pct) if is_discount else 0.0
    increase_pct = price_change_pct if is_price_increase else 0.0

    discount_ratio = discount_pct / 100.0
    increase_ratio = increase_pct / 100.0

    run_id = get_latest_valid_run_id(item.get("run_id"))
    horizons = get_run_horizons(run_id) if run_id else None

    simulated_forecast_14d = 0.0
    daily_breakdown: list[dict[str, Any]] = []
    sell_price = 0.0
    new_price = 0.0
    inference_method = "ensemble_ml"

    if horizons is not None and len(horizons) == 14 and uid in horizons[0][5]:
        try:
            lgb, xgb_m, cat = get_global_models(MODELS_DIR)
            w_lgb, w_xgb, w_cat = 0.34, 0.30, 0.36

            rows: list[pd.DataFrame] = []
            baseline_daily: list[float] = []
            dates: list[str] = []

            for h_idx, (day_recs, pdf, _l, _x, _c, id_map) in enumerate(horizons, 1):
                idx = id_map[uid]
                rec = day_recs[idx]
                baseline_daily.append(float(rec.get("predicted_sales", 0.0)))
                dates.append(str(rec.get("date", f"Day {h_idx}")))

                r = pdf.iloc[[idx]].copy()
                sell_p = float(r["sell_price_main"].values[0]) if "sell_price_main" in r.columns else 100.0
                sell_price = sell_p

                if is_discount:
                    # Discount scenario: type_0_discount, max_discount, discounted_price
                    new_p = sell_p * (1.0 - discount_ratio)
                    r["type_0_discount"] = np.float32(discount_ratio)
                    existing_max = float(r["max_discount"].values[0]) if "max_discount" in r.columns else 0.0
                    r["max_discount"] = np.float32(max(existing_max, discount_ratio))
                    r["discounted_price"] = np.float32(new_p)
                elif is_price_increase:
                    # Price increase scenario: sell_price_main updated, no discount
                    new_p = sell_p * (1.0 + increase_ratio)
                    r["sell_price_main"] = np.float32(new_p)
                    r["discounted_price"] = np.float32(new_p)
                    r["type_0_discount"] = np.float32(0.0)
                    r["max_discount"] = np.float32(0.0)
                else:
                    new_p = sell_p

                rows.append(r)

            if is_discount:
                new_price = sell_price * (1.0 - discount_ratio)
            elif is_price_increase:
                new_price = sell_price * (1.0 + increase_ratio)
            else:
                new_price = sell_price

            # Vectorized multi-horizon batch inference
            batch_df = pd.concat(rows, ignore_index=True)
            p_lgb = np.asarray(lgb.predict(batch_df), dtype=np.float32)
            dmat = xgb.DMatrix(batch_df, enable_categorical=True)
            p_xgb = np.asarray(xgb_m.predict(dmat), dtype=np.float32)
            p_cat = np.asarray(cat.predict(batch_df), dtype=np.float32)

            ens_sqrt = np.clip(w_lgb * p_lgb + w_xgb * p_xgb + w_cat * p_cat, 0.0, None)
            sim_daily = np.square(ens_sqrt)
            simulated_forecast_14d = float(sim_daily.sum())

            for h in range(14):
                daily_breakdown.append({
                    "day": h + 1,
                    "date": dates[h],
                    "baseline": round(baseline_daily[h], 2),
                    "simulated": round(float(sim_daily[h]), 2),
                    "delta": round(float(sim_daily[h]) - baseline_daily[h], 2),
                })
        except Exception as exc:
            logger.warning("ML Ensemble re-inference failed for %s, falling back to analytical elasticity: %s", uid, exc)
            inference_method = "elasticity_fallback"
            simulated_forecast_14d = 0.0
    else:
        inference_method = "elasticity_fallback"

    # Fallback if ML inference was not possible or returned 0
    if simulated_forecast_14d <= 0.0:
        inference_method = "elasticity_fallback"
        sell_price = 100.0
        elasticity = -1.8
        if is_discount:
            multiplier = max(0.1, 1.0 + abs(elasticity) * discount_ratio)
            new_price = sell_price * (1.0 - discount_ratio)
        elif is_price_increase:
            multiplier = max(0.05, 1.0 + elasticity * increase_ratio)
            new_price = sell_price * (1.0 + increase_ratio)
        else:
            multiplier = 1.0
            new_price = sell_price
        simulated_forecast_14d = baseline_forecast_14d * multiplier

    if sell_price <= 0.0:
        sell_price = 100.0
    if new_price <= 0.0:
        new_price = sell_price * (1.0 + price_change_pct / 100.0)

    demand_delta = simulated_forecast_14d - baseline_forecast_14d
    pct_change = (
        ((simulated_forecast_14d / baseline_forecast_14d) - 1.0) * 100.0
        if baseline_forecast_14d > 0.0
        else 0.0
    )

    remaining_stock = max(0.0, current_stock - simulated_forecast_14d)
    baseline_velocity = baseline_forecast_14d / 14.0
    simulated_velocity = simulated_forecast_14d / 14.0

    baseline_dos = current_stock / baseline_velocity if baseline_velocity > 0.01 else 999.0
    simulated_dos = current_stock / simulated_velocity if simulated_velocity > 0.01 else 999.0

    # Financial & Revenue Metrics
    baseline_revenue_14d = baseline_forecast_14d * sell_price
    simulated_revenue_14d = simulated_forecast_14d * new_price
    revenue_delta = simulated_revenue_14d - baseline_revenue_14d
    revenue_pct_change = (
        (revenue_delta / baseline_revenue_14d * 100.0)
        if baseline_revenue_14d > 0.0
        else 0.0
    )

    # Price Elasticity of Demand (PED)
    pct_price_change = (new_price - sell_price) / sell_price if sell_price > 0 else 0.0
    pct_demand_change = (demand_delta / baseline_forecast_14d) if baseline_forecast_14d > 0 else 0.0
    ped = (pct_demand_change / pct_price_change) if abs(pct_price_change) > 1e-4 else 0.0

    if abs(ped) > 1.2:
        elasticity_label = "Co giãn cao (Price Elastic - Nhạy cảm giá)"
    elif abs(ped) >= 0.8:
        elasticity_label = "Co giãn đơn vị (Unit Elastic)"
    else:
        elasticity_label = "Bất co giãn (Inelastic - Ít nhạy cảm giá)"

    is_deadstock = (
        current_status.strip().lower() == "deadstock"
        or baseline_dos >= 180.0
        or (current_stock > 100 and baseline_velocity < 0.5)
    )

    # Verdict Synthesis
    recommended_discount = 0.0
    if is_price_increase:
        # Price Increase Verdict
        action_type = "price_increase"
        if revenue_delta >= 0:
            verdict = (
                f"✅ **TĂNG GIÁ KHẢ THI — TỐI ƯU HÓA DOANH THU & BIÊN LỢI NHUẬN:**\n"
                f"Sản phẩm có độ nhạy cảm giá thấp ({elasticity_label}, PED = {ped:.2f}). "
                f"Tăng giá **+{increase_pct:.0f}%** (từ {sell_price:,.2f} lên {new_price:,.2f} {CURRENCY}) chỉ làm thay đổi nhu cầu **{demand_delta:+,.0f} đơn ({pct_change:+.1f}%)**, "
                f"nhưng thúc đẩy Doanh thu 14 ngày tăng thêm **+{revenue_delta:,.2f} {CURRENCY} (+{revenue_pct_change:+.1f}%)**! "
                f"Khuyến nghị áp dụng chính sách giá mới để tối đa hóa lợi nhuận ròng."
            )
        else:
            verdict = (
                f"⚠️ **CẢNH BÁO TỔN THẤT DOANH THU KHI TĂNG GIÁ:**\n"
                f"Sản phẩm có độ nhạy cảm giá đáng kể ({elasticity_label}, PED = {ped:.2f}). "
                f"Tăng giá **+{increase_pct:.0f}%** khiến sức mua sụt giảm **{demand_delta:,.0f} đơn ({pct_change:+.1f}%)**, "
                f"làm hụt mất **{revenue_delta:,.2f} {CURRENCY} ({revenue_pct_change:+.1f}%)** doanh thu 14 ngày. "
                f"Khuyến nghị giữ nguyên giá niêm yết hoặc chỉ tăng nhẹ dưới 5%."
            )

        if current_status in ("Critical", "Reorder") or baseline_dos < 7.0:
            verdict += (
                f"\n\n💡 **Kéo dài chu kỳ tồn kho (Demand Throttling):** "
                f"Tốc độ bán giảm xuống **{simulated_velocity:.1f} cái/ngày**, giúp kéo dài thời gian đáp ứng từ "
                f"**{baseline_dos:.1f} ngày** lên **{simulated_dos:.1f} ngày** (+{simulated_dos - baseline_dos:.1f} ngày), "
                f"tạo vùng đệm an toàn câu giờ chờ lô hàng PO mới kịp cập kho."
            )
        clearance_status = "price_optimized"
        surplus_stock = remaining_stock
    else:
        # Discount / Clearance Verdict
        action_type = "discount"
        if remaining_stock <= 0.01:
            clearance_status = "fully_cleared"
            deplete_day = round(current_stock / simulated_velocity, 1) if simulated_velocity > 0 else 14.0
            verdict = (
                f"✅ **CỨU ĐƯỢC DEADSTOCK HOÀN TOÀN!** "
                f"Nhu cầu tăng vượt lượng tồn kho. Toàn bộ {current_stock:,.0f} cái dự kiến sẽ được bán hết "
                f"sau khoảng {deplete_day:,.1f} ngày (trước khi hết chu kỳ 14 ngày). "
                f"Doanh thu dự kiến đạt **{simulated_revenue_14d:,.2f} {CURRENCY}** ({revenue_delta:+,.2f} {CURRENCY}). "
                f"Lưu ý chuẩn bị kế hoạch bổ sung hàng nếu muốn tiếp tục duy trì doanh số sau khuyến mãi."
            )
            surplus_stock = 0.0
            recommended_discount = discount_pct
        else:
            surplus_stock = remaining_stock
            days_to_clear_surplus = round(current_stock / simulated_velocity, 1) if simulated_velocity > 0 else 999.0

            if baseline_forecast_14d > 0.0:
                expansion_needed = (current_stock / baseline_forecast_14d) - 1.0
                est_discount_14d = min(80.0, max(discount_pct + 10.0, (expansion_needed / 2.0) * 100.0))
                expansion_needed_30d = (current_stock / (baseline_forecast_14d * (30.0 / 14.0))) - 1.0
                est_discount_30d = min(75.0, max(discount_pct + 5.0, (expansion_needed_30d / 2.0) * 100.0))
                recommended_discount = round(est_discount_30d, 0)
            else:
                recommended_discount = 45.0

            if is_deadstock:
                clearance_status = "partial_deadstock_remaining"
                verdict = (
                    f"⚠️ **CHƯA CỨU HẾT DEADSTOCK!** "
                    f"Mặc dù nhu cầu dự kiến tăng lên **{simulated_forecast_14d:,.0f} đơn** (+{pct_change:.1f}%), "
                    f"nhưng tồn kho hiện tại đang là **{current_stock:,.0f} cái**, bạn vẫn sẽ **dư {surplus_stock:,.0f} cái**. "
                    f"Với tốc độ mới, bạn cần tới **{days_to_clear_surplus:,.0f} ngày** nữa mới xả hết lượng tồn kho này. "
                    f"Bạn nên cân nhắc mức giảm sâu hơn (khoảng **{recommended_discount:.0f}%**) hoặc kết hợp combo/flash sale để dứt điểm tồn kho."
                )
            else:
                clearance_status = "healthy_surplus"
                verdict = (
                    f"ℹ️ **Tồn kho đáp ứng tốt:** Sau kỳ khuyến mãi, sản phẩm còn dư **{surplus_stock:,.0f} cái** "
                    f"(đủ cung ứng khoảng {simulated_dos:,.1f} ngày), không bị đứt hàng và vẫn giữ mức tồn kho an toàn. "
                    f"Doanh thu 14 ngày ước tính: **{simulated_revenue_14d:,.2f} {CURRENCY}** ({revenue_delta:+,.2f} {CURRENCY})."
                )

    return {
        "success": True,
        "mode": "single_warehouse",
        "action_type": action_type,
        "sku": sku,
        "name": name,
        "category": category,
        "warehouse": wh,
        "price_change_percent": price_change_pct,
        "discount_percent": discount_pct,
        "increase_percent": increase_pct,
        "sell_price": round(sell_price, 2),
        "new_price": round(new_price, 2),
        "baseline_forecast_14d": round(baseline_forecast_14d, 1),
        "simulated_forecast_14d": round(simulated_forecast_14d, 1),
        "demand_delta": round(demand_delta, 1),
        "pct_change": round(pct_change, 1),
        "baseline_revenue_14d": round(baseline_revenue_14d, 2),
        "simulated_revenue_14d": round(simulated_revenue_14d, 2),
        "revenue_delta": round(revenue_delta, 2),
        "revenue_pct_change": round(revenue_pct_change, 1),
        "price_elasticity_demand": round(ped, 2),
        "elasticity_label": elasticity_label,
        "current_stock": round(current_stock, 0),
        "remaining_stock": round(remaining_stock, 0),
        "surplus_stock": round(surplus_stock, 0),
        "baseline_daily_velocity": round(baseline_velocity, 1),
        "simulated_daily_velocity": round(simulated_velocity, 1),
        "baseline_dos": round(baseline_dos, 1),
        "simulated_dos": round(simulated_dos, 1),
        "safety_stock": round(safety_stock, 1),
        "reorder_point": round(reorder_point, 1),
        "lead_time": lead_time,
        "current_status": current_status,
        "is_deadstock": is_deadstock,
        "clearance_status": clearance_status,
        "deadstock_verdict": verdict,
        "recommended_discount": round(recommended_discount, 0),
        "inference_method": inference_method,
        "daily_breakdown": daily_breakdown,
    }


def simulate_multi_warehouse_price_change(
    items: list[dict[str, Any]],
    price_change_pct: float,
) -> dict[str, Any]:
    """Execute multi-warehouse ML ensemble simulation across all distribution hubs for a product under two-way price change."""
    if not items:
        return {"success": False, "error": "No warehouse records found to simulate."}

    prod_name = items[0].get("name", "Product")
    prod_cat = items[0].get("category", "General")

    is_price_increase = price_change_pct > 0.0
    is_discount = price_change_pct < 0.0
    discount_pct = abs(price_change_pct) if is_discount else 0.0
    increase_pct = price_change_pct if is_price_increase else 0.0

    discount_ratio = discount_pct / 100.0
    increase_ratio = increase_pct / 100.0

    run_id = get_latest_valid_run_id(items[0].get("run_id"))
    horizons = get_run_horizons(run_id) if run_id else None

    # Load models
    lgb, xgb_m, cat = None, None, None
    if horizons is not None and len(horizons) == 14:
        try:
            lgb, xgb_m, cat = get_global_models(MODELS_DIR)
        except Exception:
            lgb = None

    wh_results: list[dict[str, Any]] = []

    for it in items:
        uid = str(it.get("id") or it.get("unique_id", ""))
        wh = str(it.get("warehouse", "Unknown"))
        sku = str(it.get("sku", f"SKU-{uid}"))
        stock = float(it.get("onHandStock", 0.0) or it.get("current_stock", 0.0) or 0.0)
        status = str(it.get("status", "In Stock"))
        base_f14 = float(it.get("forecast14d", 0.0) or 0.0)

        sim_f14 = 0.0
        sell_p = 100.0
        if horizons and lgb and uid in horizons[0][5]:
            try:
                id_map = horizons[0][5]
                idx = id_map[uid]
                rows = []
                for h in horizons:
                    r = h[1].iloc[[idx]].copy()
                    sell_p = float(r["sell_price_main"].values[0]) if "sell_price_main" in r.columns else 100.0
                    if is_discount:
                        new_p = sell_p * (1.0 - discount_ratio)
                        r["type_0_discount"] = np.float32(discount_ratio)
                        existing_m = float(r["max_discount"].values[0]) if "max_discount" in r.columns else 0.0
                        r["max_discount"] = np.float32(max(existing_m, discount_ratio))
                        r["discounted_price"] = np.float32(new_p)
                    elif is_price_increase:
                        new_p = sell_p * (1.0 + increase_ratio)
                        r["sell_price_main"] = np.float32(new_p)
                        r["discounted_price"] = np.float32(new_p)
                        r["type_0_discount"] = np.float32(0.0)
                        r["max_discount"] = np.float32(0.0)
                    rows.append(r)
                bdf = pd.concat(rows, ignore_index=True)
                pl = lgb.predict(bdf)
                px = xgb_m.predict(xgb.DMatrix(bdf, enable_categorical=True))
                pc = cat.predict(bdf)
                sim_f14 = float(np.square(np.clip(0.34 * pl + 0.30 * px + 0.36 * pc, 0, None)).sum())
            except Exception as e:
                logger.warning("ML multi-warehouse failed for %s (%s): %s", uid, wh, e)
                sim_f14 = 0.0

        if is_discount:
            new_p = sell_p * (1.0 - discount_ratio)
        elif is_price_increase:
            new_p = sell_p * (1.0 + increase_ratio)
        else:
            new_p = sell_p

        if sim_f14 <= 0.0:
            elasticity = -1.8
            if is_discount:
                sim_f14 = base_f14 * max(0.1, 1.0 + abs(elasticity) * discount_ratio)
            elif is_price_increase:
                sim_f14 = base_f14 * max(0.05, 1.0 + elasticity * increase_ratio)
            else:
                sim_f14 = base_f14

        delta = sim_f14 - base_f14
        pct = ((sim_f14 / base_f14) - 1.0) * 100.0 if base_f14 > 0.0 else 0.0
        remaining = max(0.0, stock - sim_f14)
        velocity = sim_f14 / 14.0
        dos = stock / velocity if velocity > 0.01 else 999.0
        depletion_days = round(stock / velocity, 1) if velocity > 0 else 14.0

        base_rev = base_f14 * sell_p
        sim_rev = sim_f14 * new_p
        rev_delta = sim_rev - base_rev
        rev_pct = (rev_delta / base_rev * 100.0) if base_rev > 0 else 0.0

        pct_p = (new_p - sell_p) / sell_p if sell_p > 0 else 0.0
        pct_q = delta / base_f14 if base_f14 > 0 else 0.0
        wh_ped = (pct_q / pct_p) if abs(pct_p) > 1e-4 else 0.0

        surplus = remaining if remaining > 0.0 else 0.0
        shortage = (sim_f14 - stock) if sim_f14 > stock else 0.0

        if shortage > 0.0:
            if depletion_days <= 1.0:
                outcome_label = f"🛑 CHÁY HÀNG (Cạn sau {round(depletion_days*24):,.0f}h)"
                action_tag = "stockout_risk"
            else:
                outcome_label = f"⚠️ ĐỨT HÀNG (Cạn sau {depletion_days:.1f} ngày)"
                action_tag = "stockout_risk"
        else:
            if status.lower() == "deadstock":
                outcome_label = f"⚠️ Vẫn dư Deadstock (+{surplus:,.0f} cái)"
                action_tag = "surplus_deadstock"
            else:
                outcome_label = f"✅ Dư dả (+{surplus:,.0f} cái)"
                action_tag = "surplus_safe"

        wh_results.append({
            "uid": uid,
            "sku": sku,
            "warehouse": wh,
            "sell_price": round(sell_p, 2),
            "new_price": round(new_p, 2),
            "current_stock": round(stock, 0),
            "baseline_forecast_14d": round(base_f14, 1),
            "simulated_forecast_14d": round(sim_f14, 1),
            "demand_delta": round(delta, 1),
            "pct_change": round(pct, 1),
            "baseline_revenue_14d": round(base_rev, 2),
            "simulated_revenue_14d": round(sim_rev, 2),
            "revenue_delta": round(rev_delta, 2),
            "revenue_pct_change": round(rev_pct, 1),
            "ped": round(wh_ped, 2),
            "remaining_stock": round(remaining, 0),
            "surplus": round(surplus, 0),
            "shortage": round(shortage, 0),
            "simulated_dos": round(dos, 1),
            "depletion_days": depletion_days,
            "outcome_label": outcome_label,
            "action_tag": action_tag,
            "current_status": status,
        })

    # Network Totals
    total_stock = sum(w["current_stock"] for w in wh_results)
    total_base = sum(w["baseline_forecast_14d"] for w in wh_results)
    total_sim = sum(w["simulated_forecast_14d"] for w in wh_results)
    total_delta = total_sim - total_base
    total_pct = ((total_sim / total_base) - 1.0) * 100.0 if total_base > 0.0 else 0.0

    total_base_rev = sum(w["baseline_revenue_14d"] for w in wh_results)
    total_sim_rev = sum(w["simulated_revenue_14d"] for w in wh_results)
    total_rev_delta = total_sim_rev - total_base_rev
    total_rev_pct = ((total_rev_delta / total_base_rev) * 100.0) if total_base_rev > 0.0 else 0.0

    total_remaining = sum(w["remaining_stock"] for w in wh_results)
    total_surplus = sum(w["surplus"] for w in wh_results)
    total_shortage = sum(w["shortage"] for w in wh_results)
    total_dos = total_stock / (total_sim / 14.0) if total_sim > 0.0 else 999.0

    # Total network PED
    p_pct_change = (price_change_pct / 100.0)
    q_pct_change = (total_delta / total_base) if total_base > 0 else 0.0
    total_ped = (q_pct_change / p_pct_change) if abs(p_pct_change) > 1e-4 else 0.0

    surplus_hubs = [w for w in wh_results if w["surplus"] > 50]
    shortage_hubs = [w for w in wh_results if w["shortage"] > 0]
    transferable_units = min(total_surplus, total_shortage)

    return {
        "success": True,
        "mode": "multi_warehouse",
        "action_type": "price_increase" if is_price_increase else "discount",
        "product_name": prod_name,
        "category": prod_cat,
        "price_change_percent": price_change_pct,
        "discount_percent": discount_pct,
        "increase_percent": increase_pct,
        "warehouses": wh_results,
        "total_stock": round(total_stock, 0),
        "total_baseline_demand": round(total_base, 1),
        "total_simulated_demand": round(total_sim, 1),
        "total_delta": round(total_delta, 1),
        "total_pct": round(total_pct, 1),
        "total_baseline_revenue": round(total_base_rev, 2),
        "total_simulated_revenue": round(total_sim_rev, 2),
        "total_revenue_delta": round(total_rev_delta, 2),
        "total_revenue_pct": round(total_rev_pct, 1),
        "total_ped": round(total_ped, 2),
        "total_remaining": round(total_remaining, 0),
        "total_surplus": round(total_surplus, 0),
        "total_shortage": round(total_shortage, 0),
        "total_dos": round(total_dos, 1),
        "has_asymmetry": len(surplus_hubs) > 0 and len(shortage_hubs) > 0,
        "surplus_hubs": surplus_hubs,
        "shortage_hubs": shortage_hubs,
        "transferable_units": round(transferable_units, 0),
    }


def simulate_sku_price_change(
    sku_or_id: str,
    price_change_percent: float | int,
    warehouse: str = "",
) -> dict[str, Any]:
    """Execute two-way price change simulation (discount for clearance or price increase for revenue elasticity).

    Automatically handles:
    1. Single-warehouse deep-dive when a warehouse is specified or SKU is unique to a warehouse.
    2. Multi-warehouse comparative network simulation when a product is sold across multiple hubs.
    """
    pct = float(price_change_percent)
    if pct < -90.0:
        pct = -90.0
    elif pct > 150.0:
        pct = 150.0

    import re
    raw_query = str(sku_or_id or "").strip()
    clean_lower = raw_query.lower()
    wh_clean = str(warehouse or "").strip().lower()
    is_all_warehouses = wh_clean in ("all", "tat ca", "tất cả", "toàn bộ", "toan bo")
    is_specific_warehouse = bool(wh_clean and not is_all_warehouses)
    is_explicit_sku = bool(re.search(r"^\s*sku[-_\s]?\d+\s*$", clean_lower) or clean_lower.isdigit())

    # Case 1: Specific warehouse explicitly requested
    if is_specific_warehouse:
        item = resolve_sku_item(sku_or_id, warehouse=warehouse)
        if item:
            return simulate_single_sku_price_change(item, pct)
        return {
            "success": False,
            "error": f"Product '{sku_or_id}' was not found in warehouse '{warehouse}'.",
        }

    # Case 2: Explicit SKU code without "all warehouses" request -> target that single SKU
    if is_explicit_sku and not is_all_warehouses:
        item = resolve_sku_item(sku_or_id)
        if item:
            return simulate_single_sku_price_change(item, pct)

    # Case 3: Product name query or explicit "all warehouses" -> check multi-warehouse
    all_wh_items = find_all_warehouse_items_for_product(sku_or_id)
    if len(all_wh_items) > 1:
        return simulate_multi_warehouse_price_change(all_wh_items, pct)
    elif len(all_wh_items) == 1:
        return simulate_single_sku_price_change(all_wh_items[0], pct)

    # Fallback to single item resolution
    item = resolve_sku_item(sku_or_id, warehouse=warehouse)
    if not item:
        run_id_cand = get_latest_valid_run_id()
        if run_id_cand:
            cand_horizons = get_run_horizons(run_id_cand)
            if cand_horizons:
                day_recs, pdf, _l, _x, _c, id_map = cand_horizons[0]
                target_clean = str(sku_or_id).strip().lower()
                matched_idx = None
                for uid_str, idx in id_map.items():
                    if target_clean in (f"sku-{uid_str}".lower(), uid_str.lower()):
                        matched_idx = idx
                        break
                    rec_name = str(day_recs[idx].get("name", "")).lower()
                    if target_clean == rec_name or target_clean in rec_name:
                        matched_idx = idx
                        break
                if matched_idx is not None:
                    rec = day_recs[matched_idx]
                    uid_val = str(rec.get("unique_id", ""))
                    f14_sum = sum(h[0][id_map[uid_val]].get("predicted_sales", 0.0) for h in cand_horizons)
                    item = {
                        "id": uid_val,
                        "unique_id": uid_val,
                        "sku": f"SKU-{uid_val}",
                        "name": rec.get("name", "Product"),
                        "warehouse": rec.get("warehouse", "Central Warehouse"),
                        "category": rec.get("category", "General"),
                        "forecast14d": f14_sum,
                        "onHandStock": 500,
                        "status": "In Stock",
                        "safetyStock": 50.0,
                        "reorderPoint": 150.0,
                        "leadTimeDays": 3,
                        "run_id": run_id_cand,
                    }

    if not item:
        return {
            "success": False,
            "error": f"SKU or item identifier '{sku_or_id}' was not found in inventory.",
        }

    return simulate_single_sku_price_change(item, pct)


def simulate_sku_discount(
    sku_or_id: str,
    price_discount_percent: float | int,
    warehouse: str = "",
) -> dict[str, Any]:
    """Backward-compatible entry point for discount simulations."""
    disc_val = max(0.0, min(90.0, float(price_discount_percent)))
    return simulate_sku_price_change(sku_or_id, -disc_val, warehouse=warehouse)


def format_multi_warehouse_markdown(sim: dict[str, Any]) -> str:
    """Format multi-warehouse comparative simulation results into an executive Markdown report."""
    prod = sim["product_name"]
    action = sim.get("action_type", "discount")
    pct_val = sim["price_change_percent"]
    wh_list = sim["warehouses"]

    if action == "price_increase":
        scenario_title = f"Áp dụng mức tăng giá **+{pct_val:.0f}%**"
    else:
        scenario_title = f"Áp dụng mức chiết khấu **-{abs(pct_val):.0f}%**"

    lines = [
        f"### 🏬 Multi-Warehouse What-If Simulation: {prod} ({len(wh_list)} Distribution Hubs)",
        f"• **Kịch bản mô phỏng:** {scenario_title} trong kỳ 14 ngày (ML Ensemble re-inference).",
        "",
        "#### 💡 Nhận định Điều hành Toàn Mạng Lưới (BLUF):",
    ]

    if action == "price_increase":
        if sim["total_revenue_delta"] >= 0:
            lines.extend([
                f"✅ **TĂNG GIÁ KHẢ THI TRÊN TOÀN MẠNG LƯỚI:**",
                f"Tổng nhu cầu toàn hệ thống ước tính đạt **{sim['total_simulated_demand']:,.0f} đơn** ({sim['total_delta']:+,.0f} đơn, {sim['total_pct']:+.1f}%). "
                f"Do độ co giãn cầu thấp (PED = {sim['total_ped']:.2f}), mức tăng giá **+{pct_val:.0f}%** giúp Doanh thu 14 ngày toàn mạng lưới tăng thêm "
                f"**+{sim['total_revenue_delta']:,.0f} {CURRENCY} (+{sim['total_revenue_pct']:+.1f}%)**, nâng tổng doanh thu lên **{sim['total_simulated_revenue']:,.0f} {CURRENCY}**.",
            ])
        else:
            lines.extend([
                f"⚠️ **CẢNH BÁO TỔN THẤT DOANH THU TOÀN MẠNG LƯỚI:**",
                f"Do độ co giãn cầu cao (PED = {sim['total_ped']:.2f}), tăng giá **+{pct_val:.0f}%** khiến nhu cầu giảm mạnh **{sim['total_delta']:,.0f} đơn ({sim['total_pct']:+.1f}%)**, "
                f"làm hụt mất **{sim['total_revenue_delta']:,.0f} {CURRENCY} ({sim['total_revenue_pct']:+.1f}%)** doanh thu 14 ngày. Cần cân nhắc lại biên độ tăng giá.",
            ])
    else:
        if sim["has_asymmetry"]:
            surplus_names = ", ".join(f"`{w['warehouse']}`" for w in sim["surplus_hubs"])
            shortage_names = ", ".join(f"`{w['warehouse']}`" for w in sim["shortage_hubs"])
            lines.extend([
                f"⚠️ **CẢNH BÁO BẤT CÂN ĐỐI TỒN KHO NGHIÊM TRỌNG:**",
                f"Tổng nhu cầu toàn mạng lưới dự kiến tăng từ **{sim['total_baseline_demand']:,.0f}** lên **{sim['total_simulated_demand']:,.0f} đơn** (+{sim['total_pct']:.1f}%). "
                f"Tuy nhiên, hiện trạng tồn kho phân bổ cực kỳ lệch lạc: trong khi cụm kho **{surplus_names}** vẫn dư thừa **+{sim['total_surplus']:,.0f} cái**, "
                f"thì cụm kho **{shortage_names}** sẽ **cháy hàng ngay sau 0.1 đến 1 ngày** (thiếu hụt **-{sim['total_shortage']:,.0f} cái**)! "
                f"**Tuyệt đối không áp dụng giảm giá đồng loạt trên toàn quốc.**",
            ])
        else:
            lines.extend([
                f"Tổng nhu cầu 14 ngày toàn mạng lưới dự kiến tăng từ **{sim['total_baseline_demand']:,.0f}** lên **{sim['total_simulated_demand']:,.0f} đơn** (+{sim['total_pct']:.1f}%). "
                f"Tồn kho toàn hệ thống đáp ứng tốt với tổng lượng còn dư **{sim['total_remaining']:,.0f} cái** (DOS = {sim['total_dos']:.1f} ngày). "
                f"Doanh thu dự kiến đạt **{sim['total_simulated_revenue']:,.0f} {CURRENCY}** ({sim['total_revenue_delta']:+,.0f} {CURRENCY}).",
            ])

    lines.extend([
        "",
        "#### 📊 Bảng So sánh & Đánh giá Tác động Theo Từng Kho:",
        f"| Kho lưu trữ | Mã SKU | Tồn kho thực | Dự báo gốc | Dự báo mới | Lượng đổi | Doanh thu 14d ({CURRENCY}) | Độ co giãn PED | Đánh giá Tồn kho |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for w in wh_list:
        lines.append(
            f"| **{w['warehouse']}** | `{w['sku']}` | {w['current_stock']:,.0f} | {w['baseline_forecast_14d']:,.0f} | **{w['simulated_forecast_14d']:,.0f}** | {w['demand_delta']:+,.0f} ({w['pct_change']:+.1f}%) | {w['simulated_revenue_14d']:,.0f} ({w['revenue_delta']:+,.0f}) | {w['ped']:.2f} | {w['outcome_label']} |"
        )

    lines.extend([
        f"| **TOÀN MẠNG LƯỚI** | **{len(wh_list)} Kho** | **{sim['total_stock']:,.0f}** | **{sim['total_baseline_demand']:,.0f}** | **{sim['total_simulated_demand']:,.0f}** | **{sim['total_delta']:+,.0f} ({sim['total_pct']:+.1f}%)** | **{sim['total_simulated_revenue']:,.0f} ({sim['total_revenue_delta']:+,.0f})** | **{sim['total_ped']:.2f}** | { '⚠️ Lệch pha cung - cầu vùng' if sim['has_asymmetry'] else '✅ Cân đối ổn định' } |",
        "",
        "#### 🎯 Khuyến nghị Vận hành & Phân bổ Chuỗi Cung ứng:",
    ])

    if action == "price_increase":
        lines.extend([
            f"1. **Tối ưu hóa giá theo kho (Regional Elasticity Pricing):** Ưu tiên tăng giá tại các kho có lượng cầu bất co giãn (|PED| thấp) và các kho đang có nguy cơ cạn kho để vừa tối đa hóa doanh thu vừa kéo dài thời gian cung ứng.",
            f"2. **Giám sát sức mua thực tế:** Theo dõi chặt chẽ doanh số 3 ngày đầu áp dụng giá mới tại các kho nhạy cảm giá để kịp thời điều chỉnh nếu nhu cầu tụt quá dự kiến.",
            f"3. **Xem chi tiết riêng từng kho:** Để chạy mô phỏng sâu cho riêng 1 kho, hãy gõ: `Mô phỏng {prod} ở kho {wh_list[0]['warehouse']}`.",
        ])
    else:
        if sim["has_asymmetry"]:
            lines.extend([
                f"1. **Khuyến mãi có chọn lọc theo vùng (Regional Pricing):** Chỉ kích hoạt giảm giá {abs(pct_val):.0f}% tại cụm kho thừa hàng ({', '.join(w['warehouse'] for w in sim['surplus_hubs'])}). Giữ nguyên giá niêm yết tại cụm kho đang thiếu hàng để bảo vệ biên lợi nhuận.",
                f"2. **Điều phối điều chuyển kho nội bộ (Inter-Warehouse Stock Transfer):** Khẩn trương phê duyệt lệnh chuyển khoảng **~{sim['transferable_units']:,.0f} cái** từ các kho dư dả sang chi viện cho các kho thiếu hụt trước ngày chạy chiến dịch.",
                f"3. **Xem chi tiết riêng từng kho:** Để chạy mô phỏng sâu cho riêng 1 kho, hãy gõ: `Mô phỏng {prod} ở kho {wh_list[0]['warehouse']}`.",
            ])
        else:
            lines.extend([
                f"1. **Đồng bộ khuyến mãi:** Có thể áp dụng mức chiết khấu {abs(pct_val):.0f}% trên toàn hệ thống mà không lo ngại nguy cơ đứt hàng.",
                f"2. **Kế hoạch bổ sung:** Đặt PO bổ sung định kỳ theo lead time từng kho để duy trì đà tăng trưởng.",
            ])

    return "\n".join(lines)


def format_simulation_markdown(sim: dict[str, Any]) -> str:
    """Format simulation results into an executive, presentation-ready Markdown report."""
    if not sim.get("success"):
        return f"❌ **Simulation Error:** {sim.get('error', 'Unknown simulation error.')}"

    if sim.get("mode") == "multi_warehouse":
        return format_multi_warehouse_markdown(sim)

    sku = sim["sku"]
    name = sim["name"]
    wh = sim["warehouse"]
    cat = sim["category"]
    action = sim.get("action_type", "discount")
    pct_val = sim["price_change_percent"]
    verdict = sim["deadstock_verdict"]

    if action == "price_increase":
        scenario_desc = f"Áp dụng mức tăng giá **+{pct_val:.0f}%**"
        scenario_col = "Kịch bản Tăng Giá"
    else:
        scenario_desc = f"Áp dụng mức giảm giá **-{abs(pct_val):.0f}%**"
        scenario_col = "Kịch bản Giảm Giá"

    lines = [
        f"### 🎯 What-If Demand & Price Simulation: {sku} — {name}",
        f"• **Phạm vi áp dụng:** Kho `{wh}` | Ngành hàng: `{cat}`",
        f"• **Kịch bản mô phỏng:** {scenario_desc} trong kỳ 14 ngày (ML Ensemble re-inference).",
        "",
        "#### 💡 Nhận định Điều hành & Quyết định Giá (BLUF):",
        f"{verdict}",
        "",
        "#### 📊 Bảng So sánh Kịch bản (Scenario Comparison):",
        f"| Chỉ số Hoạt động | Hiện tại (Baseline) | {scenario_col} | Chênh lệch (Impact) |",
        "| :--- | :---: | :---: | :---: |",
        f"| **Đơn giá sản phẩm** | {sim['sell_price']:,.2f} {CURRENCY} | **{sim['new_price']:,.2f} {CURRENCY}** | {sim['new_price'] - sim['sell_price']:+,.2f} {CURRENCY} ({pct_val:+.0f}%) |",
        f"| **Dự báo nhu cầu 14 ngày** | {sim['baseline_forecast_14d']:,.0f} đơn | **{sim['simulated_forecast_14d']:,.0f} đơn** | **{sim['demand_delta']:+,.0f} đơn ({sim['pct_change']:+.1f}%)** |",
        f"| **Doanh thu dự kiến 14 ngày** | {sim['baseline_revenue_14d']:,.2f} {CURRENCY} | **{sim['simulated_revenue_14d']:,.2f} {CURRENCY}** | **{sim['revenue_delta']:+,.2f} {CURRENCY} ({sim['revenue_pct_change']:+.1f}%)** |",
        #f"| **Độ co giãn của cầu (PED)** | — | **{sim['price_elasticity_demand']:.2f}** | {sim['elasticity_label']} |",
        f"| **Tốc độ bán TB (Daily Velocity)** | {sim['baseline_daily_velocity']:,.1f} cái/ngày | **{sim['simulated_daily_velocity']:,.1f} cái/ngày** | {sim['simulated_daily_velocity'] - sim['baseline_daily_velocity']:+,.1f} cái/ngày |",
        f"| **Tồn kho thực tế (On-Hand)** | {sim['current_stock']:,.0f} cái | {sim['current_stock']:,.0f} cái | — |",
        #f"| **Tồn kho dự kiến còn lại** | {max(0.0, sim['current_stock'] - sim['baseline_forecast_14d']):,.0f} cái | **{sim['remaining_stock']:,.0f} cái** | **{-sim['demand_delta']:,.0f} cái tồn** |",
        f"| **Số ngày cung ứng (DOS)** | {sim['baseline_dos']:,.1f} ngày | **{sim['simulated_dos']:,.1f} ngày** | {sim['simulated_dos'] - sim['baseline_dos']:+,.1f} ngày |",
        #f"| **Trạng thái kho vận** | `{sim['current_status']}` | `{ 'Đã xả hết' if sim['remaining_stock'] == 0 else ('An toàn' if sim['remaining_stock'] >= sim['safety_stock'] else 'Cảnh báo') }` | { 'Cứu thành công' if sim['remaining_stock'] == 0 else ('Tối ưu doanh thu' if action == 'price_increase' else 'Chưa dứt điểm') } |",
        "",
        "#### 🎯 Khuyến nghị Vận hành & Quyết định Giá:",
    ]

    if action == "price_increase":
        if sim["revenue_delta"] >= 0:
            lines.extend([
                f"1. **Triển khai tăng giá niêm yết:** Tăng giá +{pct_val:.0f}% mang lại thêm **+{sim['revenue_delta']:,.2f} {CURRENCY}** mà không ảnh hưởng tiêu cực đến sức mua.",
                f"2. **Kiểm soát biên lợi nhuận:** Phối hợp cùng phòng Tài chính để ghi nhận mức tăng biên lợi nhuận gộp từ chính sách giá mới.",
                f"3. **Tồn kho duy trì tốt:** Số ngày cung ứng đạt **{sim['simulated_dos']:.1f} ngày**, đảm bảo vận hành ổn định trong suốt chu kỳ.",
            ])
        else:
            lines.extend([
                f"1. **Hạn chế tăng giá mạnh:** Mức tăng +{pct_val:.0f}% làm sụt giảm nhu cầu quá sâu, gây thâm hụt doanh thu. Nên thử nghiệm mức tăng nhẹ dưới 5%.",
                "2. **Thêm giá trị gia tăng (Value-add):** Nếu bắt buộc phải tăng giá do chi phí đầu vào, hãy bổ sung dịch vụ (giao hàng ưu tiên, đóng gói cao cấp) để giảm độ nhạy cảm của khách hàng.",
            ])
    else:
        if sim["remaining_stock"] > 0 and sim["is_deadstock"]:
            rec_disc = sim["recommended_discount"]
            lines.extend([
                f"1. **Điều chỉnh mức giảm giá:** Mức giảm {abs(pct_val):.0f}% chưa đủ kích cầu để dứt điểm lượng tồn {sim['current_stock']:,.0f} cái. Nên nâng mức chiết khấu lên **~{rec_disc:.0f}%**.",
                "2. **Giải pháp thay thế (Bundling/Flash Sale):** Thay vì chỉ giảm giá đơn lẻ làm loãng biên lợi nhuận, hãy bán combo kèm sản phẩm Best-seller hoặc chạy Flash Sale cuối tuần.",
                "3. **Theo dõi tốc độ tiêu thụ:** Nếu sau 3 ngày tốc độ bán thực tế không đạt kỳ vọng, chuyển ngay sang kênh xả hàng thanh lý.",
            ])
        elif sim["remaining_stock"] == 0:
            lines.extend([
                "1. **Rủi ro đứt hàng (Stockout Risk):** Do lượng cầu mô phỏng vượt tồn kho, toàn bộ hàng sẽ bán hết sớm. Hãy đặt giới hạn số lượng mua (limit per order) nếu muốn kéo dài chương trình.",
                f"2. **Kế hoạch đặt hàng lại (PO):** Lead time của SKU này là **{sim['lead_time']} ngày**, cần kích hoạt PO mới ngay từ tuần sau nếu muốn duy trì doanh số.",
            ])
        else:
            lines.extend([
                f"1. **Duy trì mức giảm:** Mức giảm {abs(pct_val):.0f}% mang lại tăng trưởng nhu cầu +{sim['pct_change']:.1f}% mà không gây rủi ro đứt hàng.",
                f"2. **Tồn kho an toàn:** Lượng tồn kho còn lại ({sim['remaining_stock']:,.0f} cái) cao hơn tồn kho an toàn ({sim['safety_stock']:,.0f} cái), đảm bảo vận hành ổn định.",
            ])

    return "\n".join(lines)
