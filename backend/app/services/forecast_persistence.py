"""forecast_persistence.py — Production forecast persistence service for PostgreSQL RDS.

Handles:
- Bulk persistence of 14-day forecasts and 100% TreeSHAP attributions to core schema.
- Dynamic Top-K + Other features aggregation (lossless presentation).
- Multi-run version management (is_latest flags).
- Fast queries from RDS with fallback support.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
import logging
import math
from pathlib import Path
import pickle
from typing import Any
import uuid

import numpy as np
import polars as pl
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT
from app.models.core.forecast import (
    CoreForecastDailyPoint,
    CoreForecastItemSummary,
    CoreForecastRun,
)

logger = logging.getLogger(__name__)

GROUP_MAPPING = {
    "promotion": "Promotion",
    "sales_lag": "Sales Lags & Momentum",
    "sales_history": "Sales Lags & Momentum",
    "sales_summary": "Sales Lags & Momentum",
    "order_adjusted_lag": "Sales Lags & Momentum",
    "price": "Pricing",
    "price_adjusted_lag": "Pricing",
    "calendar": "Calendar & Seasonality",
    "order_context": "Order Context",
    "identity": "Order Context",
    "other": "Order Context",
}

GROUP_COLORS = {
    "Sales Lags & Momentum": "#106ef0",
    "Pricing": "#8b5cf6",
    "Promotion": "#f59e0b",
    "Calendar & Seasonality": "#4da20c",
    "Order Context": "#94a3b8",
}

DEFAULT_DRIVERS = [
    {"id": "sales_lags_and_momentum", "name": "Sales Lags & Momentum", "score": 60, "color": "#106ef0"},
    {"id": "pricing", "name": "Pricing", "score": 25, "color": "#8b5cf6"},
    {"id": "promotion", "name": "Promotion", "score": 10, "color": "#f59e0b"},
    {"id": "calendar_and_seasonality", "name": "Calendar & Seasonality", "score": 3, "color": "#4da20c"},
    {"id": "order_context", "name": "Order Context", "score": 2, "color": "#94a3b8"},
]


@lru_cache(maxsize=4)
def get_price_map(run_id: str | None = None) -> dict[str, float]:
    """Retrieve item baseline price (sell_price_main in K VND) matching model horizon."""
    price_map: dict[str, float] = {}
    backend_dir = Path(__file__).resolve().parents[2]

    # 1. Prioritize horizon-1.pickle from active run or latest forecast artifact (matching simulation baseline)
    try:
        artifacts_dir = backend_dir / "data" / "forecast_artifacts"
        target_pickle = None
        if run_id:
            cand = artifacts_dir / str(run_id) / "horizon-1.pickle"
            if cand.is_file():
                target_pickle = cand
        if not target_pickle and artifacts_dir.is_dir():
            pickles = sorted(artifacts_dir.glob("*/horizon-1.pickle"), key=lambda p: p.stat().st_mtime, reverse=True)
            if pickles:
                target_pickle = pickles[0]

        if target_pickle and target_pickle.is_file():
            with target_pickle.open("rb") as f:
                day_records, pdf, _l, _x, _c = pickle.load(f)
            if "sell_price_main" in pdf.columns:
                for idx, row in enumerate(day_records):
                    uid = str(row["unique_id"])
                    val = pdf.iloc[idx]["sell_price_main"]
                    if val is not None and not np.isnan(val):
                        price_map[uid] = round(float(val), 2)
            if price_map:
                return price_map
    except Exception as e:
        logger.warning(f"Could not load prices from horizon pickle: {e}")

    # 2. Fallback to raw_snapshot_60d_active.parquet
    cache_path = backend_dir / "data" / "cache" / "raw_snapshot_60d_active.parquet"
    if cache_path.exists():
        try:
            cache_df = pl.read_parquet(cache_path)
            if "sell_price_main" in cache_df.columns:
                p_df = cache_df.sort("date").group_by("unique_id").last().select(["unique_id", "sell_price_main"])
                for r in p_df.iter_rows(named=True):
                    if r["sell_price_main"] is not None:
                        price_map[str(r["unique_id"])] = round(float(r["sell_price_main"]), 2)
        except Exception as e:
            logger.warning(f"Could not load prices from {cache_path}: {e}")
    return price_map


def format_topk_with_others(features_list: list[dict[str, Any]], k: int = 5) -> list[dict[str, Any]]:
    """Tách Top K features có tác động lớn nhất (theo abs_shap giảm dần)
    và tự động gom toàn bộ các features còn lại thành 1 dòng đại diện duy nhất 'Other Features'.
    Nếu k <= 0, trả về toàn bộ 100% features (không gom nhóm).
    """
    if not features_list:
        return []
    if k <= 0 or len(features_list) <= k:
        return [dict(f) for f in features_list]

    top_k = [dict(f) for f in features_list[:k]]
    remaining = features_list[k:]

    other_shap = sum(float(f.get("shap", 0.0)) for f in remaining)
    other_abs_shap = sum(float(f.get("abs_shap", 0.0)) for f in remaining)

    top_k.append({
        "feature": "other_features",
        "label": f"Other Features ({len(remaining)} features)",
        "group": "Other",
        "shap": round(other_shap, 4),
        "abs_shap": round(other_abs_shap, 4),
        "direction": "increase" if other_shap >= 0 else "decrease",
        "is_aggregated": True,
        "features_count": len(remaining),
    })
    return top_k


_INACTIVE_UIDS_CACHE: set[str] | None = None


def get_inactive_uids() -> set[str]:
    """Return set of unique_ids with 10+ days of no sales up to cutoff."""
    global _INACTIVE_UIDS_CACHE
    if _INACTIVE_UIDS_CACHE is not None:
        return _INACTIVE_UIDS_CACHE

    candidate_paths = [
        BACKEND_ROOT / "data" / "output" / "skus_no_sales_10plus_days.csv",
        BACKEND_ROOT.parent / "docs" / "archive" / "data_analysis" / "skus_no_sales_10plus_days.csv",
        Path("docs/archive/data_analysis/skus_no_sales_10plus_days.csv"),
    ]
    for csv_path in candidate_paths:
        if csv_path.exists():
            try:
                df = pl.read_csv(csv_path)
                col = "sku_id" if "sku_id" in df.columns else "unique_id"
                _INACTIVE_UIDS_CACHE = set(str(x) for x in df[col].to_list())
                return _INACTIVE_UIDS_CACHE
            except Exception as exc:
                logger.warning("Failed reading inactive SKUs CSV from %s: %s", csv_path, exc)

    active_parquet = BACKEND_ROOT / "data" / "cache" / "raw_snapshot_60d_active.parquet"
    if active_parquet.exists():
        try:
            active_df = pl.read_parquet(active_parquet)
            active_uids = set(str(x) for x in active_df["unique_id"].unique().to_list())
            from app.db.session import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                all_uids = set(str(x) for x in conn.execute(text("SELECT unique_id FROM core.inventory")).scalars().all())
            _INACTIVE_UIDS_CACHE = all_uids - active_uids
            return _INACTIVE_UIDS_CACHE
        except Exception as exc:
            logger.warning("Failed computing inactive SKUs from active parquet: %s", exc)

    _INACTIVE_UIDS_CACHE = set()
    return _INACTIVE_UIDS_CACHE


def compute_dynamic_status(
    stock: int,
    f14d: float,
    safety_stock: float,
    baseline_rop: float,
    lead_time: int,
) -> tuple[str, float]:
    """Compute dynamic inventory status and Reorder Point strictly from actual sales velocity.
    
    Prevents the synthetic status column bug where high-selling items were misclassified as Deadstock.
    """
    daily_velocity = max(f14d / 14.0, 0.0)
    dynamic_rop = float(round((lead_time * daily_velocity) + safety_stock, 2))
    if dynamic_rop <= 0 and baseline_rop > 0:
        dynamic_rop = baseline_rop

    days_of_supply = (stock / daily_velocity) if daily_velocity > 0 else 999.0
    # 1. Deadstock: Stock exists on-hand, but sales velocity is low (< 1.0 unit/day) or severe excess supply (> 365 days)
    if stock > 0 and (daily_velocity < 1.0 or days_of_supply > 365):
        item_status = "Deadstock"
    # 2. Critical: Current stock is at or below safety stock reserve
    elif stock <= safety_stock:
        item_status = "Critical"
    # 3. Reorder: Current stock is below or equal to Reorder Point
    elif stock <= dynamic_rop:
        item_status = "Reorder"
    # 4. Monitor: Approaching reorder threshold (within 20% or projected breach during lead time)
    elif stock <= dynamic_rop * 1.2 or (stock - (lead_time * daily_velocity)) <= dynamic_rop:
        item_status = "Monitor"
    # 5. In Stock: Sufficient stock above ROP buffer
    else:
        item_status = "In Stock"

    return item_status, dynamic_rop


def extract_model_parquet_data(
    preds_path: Path | None = None,
    shap_path: Path | None = None,
    include_shap: bool = True,
) -> dict[str, Any]:
    """Read prediction and TreeSHAP parquet files and build fast lookup structures."""
    if preds_path is None:
        preds_path = BACKEND_ROOT / "models" / "final_predictions.parquet"
    if shap_path is None:
        shap_path = BACKEND_ROOT / "models" / "ensemble_local_shap_union.parquet"

    pred_totals: dict[str, float] = {}
    daily_predictions: dict[str, list[dict[str, Any]]] = {}
    start_date: date = date(2024, 5, 20)
    end_date: date = date(2024, 6, 2)

    if preds_path.exists():
        preds_df = pl.read_parquet(preds_path)
        min_dt = preds_df["date"].min()
        max_dt = preds_df["date"].max()
        if min_dt is not None:
            start_date = min_dt.date() if isinstance(min_dt, datetime) else min_dt
        if max_dt is not None:
            end_date = max_dt.date() if isinstance(max_dt, datetime) else max_dt

        sums = preds_df.group_by("unique_id").agg(
            pl.col("predicted_sales").ceil().sum().alias("f14d")
        )
        for r in sums.iter_rows(named=True):
            pred_totals[str(r["unique_id"])] = float(r["f14d"])

        pts = preds_df.sort(["unique_id", "horizon"]).select([
            "unique_id", "horizon", "date", "predicted_sales"
        ])
        pts_agg = pts.group_by("unique_id", maintain_order=True).agg([
            pl.col("horizon").alias("day"),
            pl.col("date").dt.strftime("%Y-%m-%d").alias("date_str"),
            pl.col("predicted_sales").ceil().alias("pred"),
        ])
        for r in pts_agg.iter_rows(named=True):
            daily_predictions[str(r["unique_id"])] = [
                {"day": int(d), "date": str(dt), "predicted": float(p)}
                for d, dt, p in zip(r["day"], r["date_str"], r["pred"])
            ]

    drivers_breakdown_map: dict[str, list[dict[str, Any]]] = {}
    summary_features_map: dict[str, list[dict[str, Any]]] = {}
    daily_features_map: dict[tuple[str, int], list[dict[str, Any]]] = {}

    if include_shap and shap_path.exists():
        shap_df = pl.read_parquet(shap_path)

        # 1. 5 Business groups percentage breakdown
        shap_mapped = shap_df.with_columns(
            pl.col("feature_group").replace(GROUP_MAPPING).alias("business_group")
        )
        grp_agg = shap_mapped.group_by(["unique_id", "business_group"]).agg(
            pl.col("abs_ensemble_shap").sum().alias("group_impact")
        )
        raw_grp: dict[str, dict[str, float]] = {}
        for r in grp_agg.iter_rows(named=True):
            raw_grp.setdefault(str(r["unique_id"]), {})[r["business_group"]] = float(r["group_impact"])

        for uid, g_map in raw_grp.items():
            tot = sum(g_map.values()) or 1.0
            drvs = [
                {
                    "id": k.lower().replace(" ", "_").replace("&", "and"),
                    "name": k,
                    "score": int(round((v / tot) * 100)),
                    "color": GROUP_COLORS.get(k, "#94a3b8"),
                }
                for k, v in g_map.items()
            ]
            diff = 100 - sum(d["score"] for d in drvs)
            if drvs:
                drvs[0]["score"] += diff
            drivers_breakdown_map[uid] = sorted(drvs, key=lambda x: x["score"], reverse=True)

        # 2. 100% features for 14-day summary
        summary_shap = (
            shap_df.group_by(["unique_id", "feature", "feature_label", "feature_group"])
            .agg([
                pl.col("ensemble_shap").sum().round(4).alias("shap"),
                pl.col("abs_ensemble_shap").sum().round(4).alias("abs_shap"),
            ])
            .with_columns(
                pl.when(pl.col("shap") >= 0).then(pl.lit("increase")).otherwise(pl.lit("decrease")).alias("direction")
            )
            .sort(["unique_id", "abs_shap"], descending=[False, True])
        )

        item_features = (
            summary_shap.select([
                "unique_id",
                pl.struct([
                    pl.col("feature"),
                    pl.col("feature_label").alias("label"),
                    pl.col("feature_group").alias("group"),
                    pl.col("shap"),
                    pl.col("abs_shap"),
                    pl.col("direction"),
                ]).alias("feature_info"),
            ])
            .group_by("unique_id")
            .agg(pl.col("feature_info").alias("all_features_shap"))
        )
        for r in item_features.iter_rows(named=True):
            summary_features_map[str(r["unique_id"])] = r["all_features_shap"]

        # 3. 100% features for daily points
        daily_shap = (
            shap_df.group_by(["unique_id", "horizon", "feature", "feature_label", "feature_group"])
            .agg([
                pl.col("ensemble_shap").sum().round(4).alias("shap"),
                pl.col("abs_ensemble_shap").sum().round(4).alias("abs_shap"),
            ])
            .with_columns(
                pl.when(pl.col("shap") >= 0).then(pl.lit("increase")).otherwise(pl.lit("decrease")).alias("direction")
            )
            .sort(["unique_id", "horizon", "abs_shap"], descending=[False, False, True])
        )

        daily_features = (
            daily_shap.select([
                "unique_id",
                "horizon",
                pl.struct([
                    pl.col("feature"),
                    pl.col("feature_label").alias("label"),
                    pl.col("feature_group").alias("group"),
                    pl.col("shap"),
                    pl.col("abs_shap"),
                    pl.col("direction"),
                ]).alias("feature_info"),
            ])
            .group_by(["unique_id", "horizon"])
            .agg(pl.col("feature_info").alias("all_features_shap"))
        )
        for r in daily_features.iter_rows(named=True):
            daily_features_map[(str(r["unique_id"]), int(r["horizon"]))] = r["all_features_shap"]

    return {
        "pred_totals": pred_totals,
        "daily_predictions": daily_predictions,
        "drivers_breakdown_map": drivers_breakdown_map,
        "summary_features_map": summary_features_map,
        "daily_features_map": daily_features_map,
        "start_date": start_date,
        "end_date": end_date,
    }



def prune_old_forecast_runs(db: Session, max_runs_to_keep: int = 10) -> int:
    """Prune older forecast runs beyond max_runs_to_keep (default 10).

    Foreign key cascades automatically delete matching records in
    core.forecast_item_summary and core.forecast_daily_points.
    Returns the number of pruned runs.
    """
    if max_runs_to_keep <= 0:
        return 0

    all_run_ids = db.execute(
        select(CoreForecastRun.run_id)
        .order_by(CoreForecastRun.created_at.desc())
    ).scalars().all()

    if len(all_run_ids) <= max_runs_to_keep:
        return 0

    run_ids_to_delete = all_run_ids[max_runs_to_keep:]
    if run_ids_to_delete:
        stmt = delete(CoreForecastRun).where(CoreForecastRun.run_id.in_(run_ids_to_delete))
        db.execute(stmt)
        logger.info(
            "Pruned %d old forecast runs to keep only the %d most recent runs.",
            len(run_ids_to_delete),
            max_runs_to_keep,
        )
        return len(run_ids_to_delete)
    return 0


def delete_forecast_session(db: Session, session_key: str) -> int:
    """Delete a forecast run and all cascading records from DB by session_key or run_id."""
    if not session_key:
        return 0
    run_ids: list[uuid.UUID] = []
    try:
        u = uuid.UUID(str(session_key).strip())
        run_ids.append(u)
    except ValueError:
        pass

    matched = db.execute(
        select(CoreForecastRun.run_id).where(
            CoreForecastRun.model_version.like(f"%session:{session_key}%")
        )
    ).scalars().all()
    for m in matched:
        if m not in run_ids:
            run_ids.append(m)

    if not run_ids:
        return 0

    was_latest = db.execute(
        select(CoreForecastRun.run_id).where(
            CoreForecastRun.run_id.in_(run_ids),
            CoreForecastRun.is_latest == True,  # noqa: E712
        )
    ).scalar_one_or_none()

    db.execute(delete(CoreForecastRun).where(CoreForecastRun.run_id.in_(run_ids)))

    if was_latest:
        newest = db.execute(
            select(CoreForecastRun.run_id).order_by(CoreForecastRun.created_at.desc())
        ).scalar_one_or_none()
        if newest:
            db.execute(
                update(CoreForecastRun)
                .where(CoreForecastRun.run_id == newest)
                .values(is_latest=True)
            )

    db.commit()
    logger.info("Deleted %d forecast run(s) for session '%s' from database.", len(run_ids), session_key)
    return len(run_ids)


def save_forecast_run(
    db: Session,
    model_version: str = "recursive-ensemble-v1.0",
    is_latest: bool = True,
    max_runs_to_keep: int = 10,
    preds_path: Path | None = None,
    shap_path: Path | None = None,
    strict: bool = False,
    include_shap: bool = True,
    run_id: uuid.UUID | None = None,
    session_key: str | None = None,
    allow_overwrite: bool = True,
) -> CoreForecastRun:
    """Persist a complete 14-day recursive ensemble forecast run into PostgreSQL RDS."""
    if session_key:
        if not run_id:
            try:
                run_id = uuid.UUID(str(session_key).strip())
            except ValueError:
                pass
        if f"session:{session_key}" not in model_version:
            model_version = f"{model_version} [session:{session_key}]"

    if run_id:
        existing = db.execute(
            select(CoreForecastRun).where(CoreForecastRun.run_id == run_id)
        ).scalar_one_or_none()
        if existing:
            if not allow_overwrite:
                logger.info("Forecast run %s already exists and allow_overwrite is False; preserving existing.", run_id)
                return existing
            logger.info("Forecast run %s already exists and allow_overwrite is True; replacing existing run.", run_id)
            db.execute(delete(CoreForecastRun).where(CoreForecastRun.run_id == run_id))
            db.flush()

    logger.info(
        "Starting save_forecast_run (model_version=%s, is_latest=%s, session_key=%s)...",
        model_version,
        is_latest,
        session_key,
    )

    # 1. Load model outputs
    data = extract_model_parquet_data(preds_path=preds_path, shap_path=shap_path, include_shap=include_shap)
    pred_totals = data["pred_totals"]
    daily_predictions = data["daily_predictions"]
    drivers_breakdown_map = data["drivers_breakdown_map"]
    summary_features_map = data["summary_features_map"]
    daily_features_map = data["daily_features_map"]
    start_date: date = data["start_date"]
    end_date: date = data["end_date"]

    # 2. Fetch inventory and snapshot records from RDS
    inv_query = text("""
        SELECT 
            inv.unique_id, 
            inv.warehouse, 
            snap.current_stock, 
            snap.safety_stock, 
            snap.baseline_reorder_point, 
            snap.lead_time_days, 
            snap.scenario_group,
            snap.baseline_avg_daily_sales
        FROM core.inventory inv
        JOIN core.inventory_snapshot snap ON inv.unique_id = snap.unique_id
        ORDER BY inv.unique_id
    """)
    snap_rows = db.execute(inv_query).mappings().fetchall()

    if strict:
        if (not pred_totals or set(pred_totals) != set(daily_predictions)
                or (end_date - start_date).days != 13
                or any(len(points) != 14 or {p["day"] for p in points} != set(range(1, 15))
                       for points in daily_predictions.values())):
            raise ValueError("Live forecast must contain 14 predictions per item.")
        snap_rows = [r for r in snap_rows if str(r["unique_id"]) in pred_totals]
        if len(snap_rows) != len(pred_totals) or len({str(r["unique_id"]) for r in snap_rows}) != len(pred_totals):
            raise ValueError("Forecast items do not match inventory snapshots uniquely.")

    run_id = run_id or uuid.uuid4()
    item_summaries: list[dict[str, Any]] = []
    daily_points: list[dict[str, Any]] = []
    total_predicted_demand = 0.0

    date_range = [
        start_date.fromordinal(start_date.toordinal() + i)
        for i in range(14)
    ]

    for r in snap_rows:
        uid = str(r["unique_id"])
        f14 = pred_totals.get(uid)
        if f14 is None:
            base_avg = float(r["baseline_avg_daily_sales"] or 0.0)
            f14 = float(math.ceil(base_avg * 14.0))
        else:
            f14 = float(math.ceil(f14))

        total_predicted_demand += f14

        current_stock = int(r["current_stock"])
        days_of_supply = round(current_stock / (f14 / 14.0), 2) if f14 > 0 else 999.0
        item_status, dynamic_rop = compute_dynamic_status(
            stock=current_stock,
            f14d=f14,
            safety_stock=float(r["safety_stock"]),
            baseline_rop=float(r["baseline_reorder_point"]),
            lead_time=int(r["lead_time_days"]),
        )

        reorder_point = dynamic_rop
        status = item_status
        if strict:
            velocity = f14 / 14.0
            safety = float(r["safety_stock"])
            reorder_point = round(float(r["lead_time_days"]) * velocity + safety, 2)
            if current_stock > 0 and (velocity < 1.0 or days_of_supply > 365):
                status = "Deadstock"
            elif current_stock <= safety:
                status = "Critical"
            elif current_stock <= reorder_point:
                status = "Reorder"
            elif current_stock <= reorder_point * 1.2 or current_stock - float(r["lead_time_days"]) * velocity <= reorder_point:
                status = "Monitor"
            else:
                status = "In Stock"

        item_summaries.append({
            "run_id": run_id,
            "unique_id": uid,
            "warehouse": r["warehouse"],
            "forecast_14d": f14,
            "current_stock": current_stock,
            "baseline_reorder_point": float(math.ceil(float(reorder_point))),
            "safety_stock": float(math.ceil(float(r["safety_stock"]))),
            "lead_time_days": int(r["lead_time_days"]),
            "days_of_supply": days_of_supply,
            "scenario_group": status,
            "drivers_breakdown": drivers_breakdown_map.get(uid, [] if strict else DEFAULT_DRIVERS),
            "all_features_shap": summary_features_map.get(uid, []),
        })

        raw_pts = daily_predictions.get(uid)
        if raw_pts:
            for pt in raw_pts:
                h = int(pt["day"])
                pt_date = datetime.strptime(pt["date"], "%Y-%m-%d").date()
                d_shap = daily_features_map.get((uid, h), [])
                daily_points.append({
                    "run_id": run_id,
                    "unique_id": uid,
                    "date": pt_date,
                    "horizon_day": h,
                    "predicted_sales": float(math.ceil(float(pt["predicted"]))),
                    "all_features_shap": d_shap,
                })
        else:
            avg_d = round(f14 / 14.0, 2)
            for i, d in enumerate(date_range, start=1):
                daily_points.append({
                    "run_id": run_id,
                    "unique_id": uid,
                    "date": d,
                    "horizon_day": i,
                    "predicted_sales": avg_d,
                    "all_features_shap": [],
                })

    # 3. Handle is_latest transition atomically
    if is_latest:
        db.execute(
            update(CoreForecastRun)
            .where(CoreForecastRun.is_latest == True)
            .values(is_latest=False)
        )

    # 4. Insert forecast_runs header
    forecast_run = CoreForecastRun(
        run_id=run_id,
        model_version=model_version,
        horizon_days=14,
        forecast_start_date=start_date,
        forecast_end_date=end_date,
        total_items=len(item_summaries),
        total_predicted_demand=round(total_predicted_demand, 2),
        is_latest=is_latest,
    )
    db.add(forecast_run)
    db.flush()

    # 5. Bulk insert item summaries in chunks
    chunk_size = 1500
    for i in range(0, len(item_summaries), chunk_size):
        chunk = item_summaries[i : i + chunk_size]
        db.execute(insert(CoreForecastItemSummary), chunk)

    # 6. Bulk insert daily points in chunks
    chunk_size_pts = 2500
    for i in range(0, len(daily_points), chunk_size_pts):
        chunk = daily_points[i : i + chunk_size_pts]
        db.execute(insert(CoreForecastDailyPoint), chunk)

    # 7. Enforce retention limit: prune older runs beyond max_runs_to_keep
    pruned_count = prune_old_forecast_runs(db, max_runs_to_keep=max_runs_to_keep)
    if pruned_count > 0:
        logger.info("Automatically pruned %d old runs during save_forecast_run.", pruned_count)

    db.commit()
    logger.info(
        "Successfully persisted forecast run %s (%s items, %s daily points, total demand %.2f)",
        run_id,
        len(item_summaries),
        len(daily_points),
        total_predicted_demand,
    )
    return forecast_run


def get_latest_forecast_from_db(
    db: Session,
    unique_id: str = "all",
    limit: int = 50,
    offset: int = 0,
    top_k: int = 5,
    use_inactive_items: bool = False,
    requested_run_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Query the latest active forecast run from RDS.

    Formats all_features_shap into Top-K + Other features (or full 100% if top_k <= 0).
    Filters out inactive items (10+ days with no sales) unless use_inactive_items is True.
    Computes dynamic inventory statuses (In Stock, Monitor, Reorder, Critical, Deadstock)
    strictly from actual sales velocity and ROP, preventing synthetic status column bugs.
    """
    run_query = select(CoreForecastRun)
    if requested_run_id is not None:
        run_query = run_query.where(CoreForecastRun.run_id == requested_run_id)
    else:
        run_query = run_query.where(CoreForecastRun.is_latest == True)
    latest_run = db.execute(run_query).scalar_one_or_none()

    if not latest_run:
        return None

    run_id = latest_run.run_id
    inactive_uids = list(get_inactive_uids())

    # Handle single item query
    if unique_id != "all":
        if not use_inactive_items and str(unique_id) in inactive_uids:
            return {
                "status": "error",
                "message": f"Item unique_id '{unique_id}' is inactive (10+ days without sales) and use_inactive_items is False.",
                "forecast_horizon_days": 14,
                "run_id": str(run_id),
                "total_items": 0,
                "count": 0,
                "items": [],
                "generated_at": latest_run.created_at.isoformat(),
            }

        stmt = text("""
            SELECT 
                s.unique_id,
                inv.name,
                inv.l1_category_name_en as category,
                s.warehouse,
                s.forecast_14d,
                s.current_stock,
                s.scenario_group,
                s.baseline_reorder_point,
                s.safety_stock,
                s.lead_time_days,
                s.days_of_supply,
                s.drivers_breakdown,
                s.all_features_shap
            FROM core.forecast_item_summary s
            JOIN core.inventory inv ON s.unique_id = inv.unique_id
            WHERE s.run_id = :run_id AND s.unique_id = :unique_id
        """)
        row = db.execute(stmt, {"run_id": run_id, "unique_id": str(unique_id)}).mappings().first()
        if not row:
            return {
                "status": "error",
                "message": f"Item unique_id '{unique_id}' not found in active forecast run.",
                "forecast_horizon_days": 14,
                "run_id": str(run_id),
                "total_items": 0,
                "count": 0,
                "items": [],
                "generated_at": latest_run.created_at.isoformat(),
            }

        pts_stmt = text("""
            SELECT 
                horizon_day as day,
                to_char(date, 'YYYY-MM-DD') as date,
                predicted_sales as predicted,
                all_features_shap
            FROM core.forecast_daily_points
            WHERE run_id = :run_id AND unique_id = :unique_id
            ORDER BY horizon_day
        """)
        pts_rows = db.execute(pts_stmt, {"run_id": run_id, "unique_id": str(unique_id)}).mappings().fetchall()

        daily_pts = []
        for p in pts_rows:
            raw_shap = p["all_features_shap"] or []
            
            # Split positive and negative features first so both columns in mirror grid get Top 5
            all_pos = [f for f in raw_shap if float(f.get("shap", 0.0)) > 0 or f.get("direction") == "increase"]
            all_pos.sort(key=lambda x: abs(float(x.get("shap", 0.0))), reverse=True)
            
            all_neg = [f for f in raw_shap if float(f.get("shap", 0.0)) < 0 or f.get("direction") == "decrease"]
            all_neg.sort(key=lambda x: abs(float(x.get("shap", 0.0))), reverse=True)

            k_val = top_k if top_k > 0 else 5
            top_pos = all_pos[:k_val]
            rem_pos = all_pos[k_val:]
            other_pos_shap = round(sum(float(f.get("shap", 0.0)) for f in rem_pos), 4)

            top_neg = all_neg[:k_val]
            rem_neg = all_neg[k_val:]
            other_neg_shap = round(sum(abs(float(f.get("shap", 0.0))) for f in rem_neg), 4)

            daily_pts.append({
                "day": int(p["day"]),
                "date": p["date"],
                "predicted": float(math.ceil(float(p["predicted"]))),
                "top_positive_features": [
                    {
                        "feature": f["feature"],
                        "feature_label": f.get("label", f["feature"]),
                        "feature_group": f.get("group", "Other"),
                        "shap_value": float(f["shap"]),
                        "direction": "increase",
                    }
                    for f in top_pos
                ],
                "top_negative_features": [
                    {
                        "feature": f["feature"],
                        "feature_label": f.get("label", f["feature"]),
                        "feature_group": f.get("group", "Other"),
                        "shap_value": float(f["shap"]),
                        "direction": "decrease",
                    }
                    for f in top_neg
                ],
                "other_positive_shap": other_pos_shap,
                "other_negative_shap": other_neg_shap,
                "all_features_shap": raw_shap,
            })

        summary_shap = format_topk_with_others(row["all_features_shap"] or [], k=top_k)
        item_status, dynamic_rop = compute_dynamic_status(
            stock=int(row["current_stock"]),
            f14d=float(math.ceil(float(row["forecast_14d"]))),
            safety_stock=float(row["safety_stock"]),
            baseline_rop=float(row["baseline_reorder_point"]),
            lead_time=int(row["lead_time_days"]),
        )
        item_obj = {
            "id": str(row["unique_id"]),
            "sku": f"SKU-{row['unique_id']}",
            "name": row["name"],
            "category": row["category"] or "General",
            "warehouse": row["warehouse"],
            "price": get_price_map(str(run_id)).get(str(row["unique_id"]), 50.0),
            "forecast14d": float(math.ceil(float(row["forecast_14d"]))),
            "onHandStock": int(row["current_stock"]),
            "status": item_status,
            "reorderPoint": float(math.ceil(float(dynamic_rop))),
            "safetyStock": float(math.ceil(float(row["safety_stock"]))),
            "leadTimeDays": int(row["lead_time_days"]),
            "daysOfSupply": float(row["days_of_supply"]) if row["days_of_supply"] is not None else None,
            "run_id": str(run_id),
            "shap_status": "completed" if (row["drivers_breakdown"] and len(row["drivers_breakdown"]) > 0) else "not_requested",
            "grouped_drivers": row["drivers_breakdown"] or [],
            "all_features_shap": summary_shap,
            "daily_points": daily_pts,
        }

        return {
            "status": "success",
            "forecast_horizon_days": 14,
            "run_id": str(run_id),
            "model_version": latest_run.model_version,
            "total_items": 1,
            "count": 1,
            "limit": limit,
            "offset": offset,
            "items": [item_obj],
            "generated_at": latest_run.created_at.isoformat(),
        }

    # Multiple items (paginated)
    if not use_inactive_items and inactive_uids:
        count_stmt = text("""
            SELECT COUNT(*) 
            FROM core.forecast_item_summary s 
            WHERE s.run_id = :run_id AND NOT (s.unique_id = ANY(:inactive_uids))
        """)
        total_count = db.execute(count_stmt, {"run_id": run_id, "inactive_uids": inactive_uids}).scalar() or 0

        items_stmt = text("""
            SELECT 
                s.unique_id,
                inv.name,
                inv.l1_category_name_en as category,
                s.warehouse,
                s.forecast_14d,
                s.current_stock,
                s.scenario_group,
                s.baseline_reorder_point,
                s.safety_stock,
                s.lead_time_days,
                s.days_of_supply,
                s.drivers_breakdown,
                s.all_features_shap
            FROM core.forecast_item_summary s
            JOIN core.inventory inv ON s.unique_id = inv.unique_id
            WHERE s.run_id = :run_id AND NOT (s.unique_id = ANY(:inactive_uids))
            ORDER BY s.unique_id
            LIMIT :limit OFFSET :offset
        """)
        rows = db.execute(items_stmt, {"run_id": run_id, "limit": limit, "offset": offset, "inactive_uids": inactive_uids}).mappings().fetchall()
    else:
        count_stmt = text("SELECT COUNT(*) FROM core.forecast_item_summary WHERE run_id = :run_id")
        total_count = db.execute(count_stmt, {"run_id": run_id}).scalar() or 0

        items_stmt = text("""
            SELECT 
                s.unique_id,
                inv.name,
                inv.l1_category_name_en as category,
                s.warehouse,
                s.forecast_14d,
                s.current_stock,
                s.scenario_group,
                s.baseline_reorder_point,
                s.safety_stock,
                s.lead_time_days,
                s.days_of_supply,
                s.drivers_breakdown,
                s.all_features_shap
            FROM core.forecast_item_summary s
            JOIN core.inventory inv ON s.unique_id = inv.unique_id
            WHERE s.run_id = :run_id
            ORDER BY s.unique_id
            LIMIT :limit OFFSET :offset
        """)
        rows = db.execute(items_stmt, {"run_id": run_id, "limit": limit, "offset": offset}).mappings().fetchall()

    uids = [str(r["unique_id"]) for r in rows]

    daily_map: dict[str, list[dict[str, Any]]] = {}
    if uids:
        pts_stmt = text("""
            SELECT 
                unique_id,
                horizon_day as day,
                to_char(date, 'YYYY-MM-DD') as date,
                predicted_sales as predicted
            FROM core.forecast_daily_points
            WHERE run_id = :run_id AND unique_id = ANY(:uids)
            ORDER BY unique_id, horizon_day
        """)
        pts_rows = db.execute(pts_stmt, {"run_id": run_id, "uids": uids}).mappings().fetchall()
        for p in pts_rows:
            uid = str(p["unique_id"])
            daily_map.setdefault(uid, []).append({
                "day": int(p["day"]),
                "date": p["date"],
                "predicted": float(math.ceil(float(p["predicted"]))),
            })

    items = []
    price_map = get_price_map(str(run_id))
    for r in rows:
        uid = str(r["unique_id"])
        summary_shap = format_topk_with_others(r["all_features_shap"] or [], k=top_k)
        status, dynamic_rop = compute_dynamic_status(
            stock=int(r["current_stock"]),
            f14d=float(math.ceil(float(r["forecast_14d"]))),
            safety_stock=float(r["safety_stock"]),
            baseline_rop=float(r["baseline_reorder_point"]),
            lead_time=int(r["lead_time_days"]),
        )
        items.append({
            "id": uid,
            "sku": f"SKU-{uid}",
            "name": r["name"],
            "category": r["category"] or "General",
            "warehouse": r["warehouse"],
            "price": price_map.get(uid, 50.0),
            "forecast14d": float(math.ceil(float(r["forecast_14d"]))),
            "onHandStock": int(r["current_stock"]),
            "status": status,
            "reorderPoint": float(math.ceil(float(dynamic_rop))),
            "safetyStock": float(math.ceil(float(r["safety_stock"]))),
            "leadTimeDays": int(r["lead_time_days"]),
            "daysOfSupply": float(r["days_of_supply"]) if r["days_of_supply"] is not None else None,
            "run_id": str(run_id),
            "shap_status": "completed" if (r["drivers_breakdown"] and len(r["drivers_breakdown"]) > 0) else "not_requested",
            "grouped_drivers": r["drivers_breakdown"] or [],
            "all_features_shap": summary_shap,
            "daily_points": daily_map.get(uid, []),
        })

    return {
        "status": "success",
        "forecast_horizon_days": 14,
        "run_id": str(run_id),
        "model_version": latest_run.model_version,
        "total_items": total_count,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "items": items,
        "generated_at": latest_run.created_at.isoformat(),
    }


def get_forecast_runs_from_db(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    """Return list of historical and current forecast runs."""
    stmt = (
        select(CoreForecastRun)
        .order_by(CoreForecastRun.created_at.desc())
        .limit(limit)
    )
    runs = db.execute(stmt).scalars().all()
    return [
        {
            "run_id": str(r.run_id),
            "model_version": r.model_version,
            "horizon_days": r.horizon_days,
            "forecast_start_date": r.forecast_start_date.isoformat(),
            "forecast_end_date": r.forecast_end_date.isoformat(),
            "total_items": r.total_items,
            "total_predicted_demand": r.total_predicted_demand,
            "is_latest": r.is_latest,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]
