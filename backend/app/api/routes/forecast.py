"""forecast.py — Production forecast API endpoints for DemandAI.

Endpoints:
- GET /api/v1/forecast/forecast_status: Real-time SSE stream reporting pipeline progress.
- GET /api/v1/forecast/get_forecast_14d: Enriched 14-day forecasts with inventory status & grouped TreeSHAP drivers.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from app.core.config import BACKEND_ROOT
from pydantic import BaseModel, Field
from app.services.forecast_jobs import forecast_jobs
import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine, get_db
from app.services.forecast_persistence import (
    compute_dynamic_status,
    get_forecast_runs_from_db,
    get_inactive_uids,
    get_latest_forecast_from_db,
    prune_old_forecast_runs,
    save_forecast_run,
    delete_forecast_session,
    get_price_map,
)
from app.pipeline.recursive_ensemble import RecursiveEnsemblePredictor

logger = logging.getLogger(__name__)
router = APIRouter()

# High-level business feature group mapping
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

# GROUP_COLORS = {
#     "Sales Lags & Momentum": "#106ef0",     # Primary Blue
#     "Pricing": "#8b5cf6",                   # Purple
#     "Promotion": "#f59e0b",                 # Amber
#     "Calendar & Seasonality": "#10b981",    # Emerald
#     "Order Context": "#94a3b8",             # Muted Slate
# }

# In-memory singletons to prevent repeated 39MB parquet re-reads and full table scans
_STATIC_MODEL_CACHE: dict[str, Any] = {}
_ALL_FORECAST_ITEMS_CACHE: list[dict[str, Any]] = []


@lru_cache(maxsize=1)
def _get_predictor() -> RecursiveEnsemblePredictor:
    return RecursiveEnsemblePredictor()


def _ensure_static_models_loaded() -> None:
    """Pre-aggregate parquet forecasts once into memory."""
    if _STATIC_MODEL_CACHE:
        return

    backend_dir = Path(__file__).resolve().parents[3]
    preds_path = backend_dir / "models" / "final_predictions.parquet"

    pred_map: dict[str, float] = {}
    daily_points_map: dict[str, list[dict[str, Any]]] = {}

    if preds_path.exists():
        preds_df = pl.read_parquet(preds_path)
        sums = preds_df.group_by("unique_id").agg(pl.col("predicted_sales").ceil().sum().alias("f14d"))
        for r in sums.iter_rows(named=True):
            pred_map[str(r["unique_id"])] = float(r["f14d"])

        pts = preds_df.sort(["unique_id", "horizon"]).select(["unique_id", "horizon", "date", "predicted_sales"])
        pts_agg = pts.group_by("unique_id", maintain_order=True).agg([
            pl.col("horizon").alias("day"),
            pl.col("date").dt.strftime("%Y-%m-%d").alias("date_str"),
            pl.col("predicted_sales").ceil().alias("pred"),
        ])
        for r in pts_agg.iter_rows(named=True):
            daily_points_map[str(r["unique_id"])] = [
                {"day": int(d), "date": str(dt), "predicted": float(p)}
                for d, dt, p in zip(r["day"], r["date_str"], r["pred"])
            ]

    # Driver SHAP is computed on-demand or loaded from active run (never load outdated static parquet)
    drivers_map: dict[str, list[dict[str, Any]]] = {}

    _STATIC_MODEL_CACHE["pred_map"] = pred_map
    _STATIC_MODEL_CACHE["daily_points_map"] = daily_points_map
    _STATIC_MODEL_CACHE["drivers_map"] = drivers_map


def _load_all_inventory_items(use_inactive_items: bool = False) -> list[dict[str, Any]]:
    """Fetch real items from core.inventory & core.inventory_snapshot once and cache."""
    global _ALL_FORECAST_ITEMS_CACHE
    if not _ALL_FORECAST_ITEMS_CACHE:
        _ensure_static_models_loaded()
        pred_map = _STATIC_MODEL_CACHE.get("pred_map", {})
        daily_points_map = _STATIC_MODEL_CACHE.get("daily_points_map", {})
        drivers_map = _STATIC_MODEL_CACHE.get("drivers_map", {})

        active_run_id = None
        computed_shap_map: dict[str, list[dict[str, Any]]] = {}
        try:
            with SessionLocal() as db:
                from app.models.core.forecast import CoreForecastItemSummary, CoreForecastRun
                from sqlalchemy import select
                r = db.execute(select(CoreForecastRun.run_id).where(CoreForecastRun.is_latest == True).order_by(CoreForecastRun.created_at.desc())).scalar_one_or_none()
                if not r:
                    r = db.execute(select(CoreForecastRun.run_id).order_by(CoreForecastRun.created_at.desc())).scalar_one_or_none()
                if r:
                    active_run_id = str(r)
                    sums = db.execute(
                        select(CoreForecastItemSummary.unique_id, CoreForecastItemSummary.drivers_breakdown)
                        .where(
                            CoreForecastItemSummary.run_id == UUID(active_run_id),
                            CoreForecastItemSummary.drivers_breakdown.is_not(None),
                        )
                    ).all()
                    for u_id, db_breakdown in sums:
                        if db_breakdown and any(d.get("score", 0) > 0 for d in db_breakdown):
                            computed_shap_map[str(u_id)] = db_breakdown
        except Exception as exc:
            logger.debug("Could not pre-load item summaries for run: %s", exc)

        items: list[dict[str, Any]] = []
        price_map = get_price_map(str(active_run_id) if active_run_id else None)
        try:
            with engine.connect() as conn:
                if active_run_id:
                    summary_query = """
                        SELECT 
                            s.unique_id, 
                            inv.name, 
                            s.warehouse, 
                            inv.l1_category_name_en as category,
                            s.current_stock, 
                            s.safety_stock, 
                            s.baseline_reorder_point, 
                            s.lead_time_days, 
                            s.scenario_group,
                            s.forecast_14d,
                            s.days_of_supply
                        FROM core.forecast_item_summary s
                        JOIN core.inventory inv ON s.unique_id = inv.unique_id
                        WHERE s.run_id = :run_id
                        ORDER BY s.unique_id
                    """
                    summary_rows = conn.execute(text(summary_query), {"run_id": active_run_id}).mappings().fetchall()
                    if summary_rows:
                        for r in summary_rows:
                            uid = str(r["unique_id"])
                            f14 = float(math.ceil(float(r["forecast_14d"] or 0.0)))
                            raw_pts = daily_points_map.get(uid)
                            if not raw_pts:
                                avg_d = round(f14 / 14.0, 2)
                                raw_pts = [
                                    {"day": i, "date": f"2024-05-{19+i:02d}" if i <= 12 else f"2024-06-{i-12:02d}", "predicted": avg_d}
                                    for i in range(1, 15)
                                ]
                            items.append({
                                "id": uid,
                                "sku": f"SKU-{uid}",
                                "run_id": active_run_id,
                                "shap_status": "not_calculated",
                                "name": r["name"],
                                "category": r["category"] or "General",
                                "warehouse": r["warehouse"] or "Central",
                                "price": price_map.get(uid, 50.0),
                                "forecast14d": f14,
                                "onHandStock": int(r["current_stock"]),
                                "status": str(r["scenario_group"]),
                                "reorderPoint": float(math.ceil(float(r["baseline_reorder_point"] or 0.0))),
                                "safetyStock": float(math.ceil(float(r["safety_stock"] or 0.0))),
                                "leadTimeDays": int(r["lead_time_days"]),
                                "daily_points": raw_pts,
                                "grouped_drivers": drivers_map.get(uid, []),
                            })
                        _ALL_FORECAST_ITEMS_CACHE = items
                        if use_inactive_items:
                            return _ALL_FORECAST_ITEMS_CACHE
                        inactive_uids = get_inactive_uids()
                        return [item for item in _ALL_FORECAST_ITEMS_CACHE if item["id"] not in inactive_uids]

                query = """
                    SELECT 
                        inv.unique_id, 
                        inv.name, 
                        inv.warehouse, 
                        inv.l1_category_name_en as category,
                        snap.current_stock, 
                        snap.safety_stock, 
                        snap.baseline_reorder_point, 
                        snap.lead_time_days, 
                        snap.scenario_group,
                        snap.baseline_avg_daily_sales
                    FROM core.inventory inv
                    JOIN core.inventory_snapshot snap ON inv.unique_id = snap.unique_id
                    ORDER BY inv.unique_id
                """
                snap_rows = conn.execute(text(query)).mappings().fetchall()

            for r in snap_rows:
                uid = str(r["unique_id"])
                f14 = pred_map.get(uid)
                if f14 is None:
                    base_avg = float(r["baseline_avg_daily_sales"] or 0.0)
                    f14 = float(math.ceil(base_avg * 14.0))
                else:
                    f14 = float(math.ceil(f14))

                raw_pts = daily_points_map.get(uid)
                if not raw_pts:
                    avg_d = round(f14 / 14.0, 2)
                    raw_pts = [
                        {"day": i, "date": f"2024-05-{19+i:02d}" if i <= 12 else f"2024-06-{i-12:02d}", "predicted": avg_d}
                        for i in range(1, 15)
                    ]

                stock = int(r["current_stock"])
                lead_time = int(r["lead_time_days"])
                safety_stock = float(r["safety_stock"])
                baseline_rop = float(r["baseline_reorder_point"])
                f14_float = float(f14)

                item_status, dynamic_rop = compute_dynamic_status(
                    stock=stock,
                    f14d=f14_float,
                    safety_stock=safety_stock,
                    baseline_rop=baseline_rop,
                    lead_time=lead_time,
                )

                db_drivers = computed_shap_map.get(uid)
                items.append({
                    "id": uid,
                    "sku": f"SKU-{uid}",
                    "run_id": active_run_id,
                    "shap_status": "completed" if db_drivers else "not_calculated",
                    "name": r["name"],
                    "category": r["category"] or "General",
                    "warehouse": r["warehouse"] or "Central",
                    "price": price_map.get(uid, 50.0),
                    "forecast14d": f14_float,
                    "onHandStock": stock,
                    "status": item_status,
                    "reorderPoint": float(math.ceil(float(dynamic_rop))),
                    "safetyStock": float(math.ceil(float(safety_stock))),
                    "leadTimeDays": lead_time,
                    "daily_points": raw_pts,
                    "grouped_drivers": db_drivers or drivers_map.get(uid, []),
                })
            _ALL_FORECAST_ITEMS_CACHE = items
        except Exception as exc:
            logger.warning("Failed loading inventory from database: %s", exc)
            return []

    if use_inactive_items:
        return _ALL_FORECAST_ITEMS_CACHE

    inactive_uids = get_inactive_uids()
    return [item for item in _ALL_FORECAST_ITEMS_CACHE if item["id"] not in inactive_uids]


def _get_single_item_shap(uid: str) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """Load on-demand TreeSHAP features for a single unique_id if calculated in active run."""
    try:
        from app.models.core.forecast import CoreForecastRun
        from app.services.item_shap import cache_path
        from sqlalchemy import select

        with SessionLocal() as db:
            run = db.execute(
                select(CoreForecastRun)
                .where(CoreForecastRun.is_latest == True)  # noqa: E712
                .order_by(CoreForecastRun.created_at.desc())
            ).scalar_one_or_none()
            if not run:
                run = db.execute(
                    select(CoreForecastRun).order_by(CoreForecastRun.created_at.desc())
                ).scalar_one_or_none()

            if run:
                c_path = cache_path(str(run.run_id), str(uid))
                if c_path.is_file():
                    cached = json.loads(c_path.read_text(encoding="utf-8"))
                    item_data = cached.get("item", {})
                    out: dict[int, dict[str, Any]] = {}
                    for pt in item_data.get("daily_points", []):
                        h = pt.get("day") or pt.get("horizon")
                        if h is not None:
                            out[int(h)] = {
                                "top_positive_features": pt.get("top_positive_features", []),
                                "top_negative_features": pt.get("top_negative_features", []),
                                "other_positive_shap": pt.get("other_positive_shap", 0.0),
                                "other_negative_shap": pt.get("other_negative_shap", 0.0),
                            }
                    return out
    except Exception as exc:
        logger.debug("No active SHAP cache found for item %s: %s", uid, exc)

    return {}


def _get_cached_forecast_payload(
    unique_id: str = "all",
    limit: int = 50,
    offset: int = 0,
    use_inactive_items: bool = False,
) -> dict[str, Any]:
    """Return cached forecast payload with fast single-item lookup or pagination."""
    if unique_id != "all" and not use_inactive_items:
        inactive_uids = get_inactive_uids()
        if str(unique_id) in inactive_uids:
            return {
                "status": "error",
                "message": f"Item unique_id '{unique_id}' is inactive (10+ days without sales) and use_inactive_items is False.",
                "forecast_horizon_days": 14,
                "total_items": 0,
                "count": 0,
                "items": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

    all_items = _load_all_inventory_items(use_inactive_items=use_inactive_items)

    if unique_id != "all":
        target = next((item for item in all_items if str(item["id"]) == str(unique_id)), None)
        if target is None:
            return {
                "status": "error",
                "message": f"Item unique_id '{unique_id}' not found.",
                "forecast_horizon_days": 14,
                "total_items": 0,
                "count": 0,
                "items": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        single_shap = _get_single_item_shap(str(unique_id))
        enriched_item = dict(target)
        if single_shap:
            enriched_pts = []
            for pt in target.get("daily_points", []):
                p_copy = dict(pt)
                h = p_copy.get("day")
                if h in single_shap:
                    p_copy["top_positive_features"] = single_shap[h]["top_positive_features"]
                    p_copy["top_negative_features"] = single_shap[h]["top_negative_features"]
                    p_copy["other_positive_shap"] = single_shap[h].get("other_positive_shap", 0.0)
                    p_copy["other_negative_shap"] = single_shap[h].get("other_negative_shap", 0.0)
                enriched_pts.append(p_copy)
            enriched_item["daily_points"] = enriched_pts

        return {
            "status": "success",
            "forecast_horizon_days": 14,
            "total_items": 1,
            "count": 1,
            "limit": limit,
            "offset": offset,
            "items": [enriched_item],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # Slice items for pagination (ensures fast payload transfer and instant Swagger UI rendering)
    sliced = all_items[offset : offset + limit]
    return {
        "status": "success",
        "forecast_horizon_days": 14,
        "total_items": len(all_items),
        "count": len(sliced),
        "limit": limit,
        "offset": offset,
        "items": sliced,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class StartForecastRequest(BaseModel):
    request_id: UUID


@router.post("/runs", status_code=202, summary="Start a real forecast job")
def start_forecast_job(request: StartForecastRequest) -> dict[str, Any]:
    return forecast_jobs.start(str(request.request_id))


def _job_snapshot(job_id: UUID) -> dict[str, Any]:
    try:
        return forecast_jobs.get(str(job_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Forecast job not found. The backend may have restarted; start a new forecast.")


@router.get("/runs/{job_id}", summary="Read forecast job status")
def forecast_job_status(job_id: UUID) -> dict[str, Any]:
    return _job_snapshot(job_id)


@router.get("/runs/{job_id}/events", summary="Watch a forecast job without starting it")
async def forecast_job_events(job_id: UUID) -> StreamingResponse:
    _job_snapshot(job_id)

    async def events():
        sequence = -1
        heartbeat_ticks = 0
        while True:
            snapshot = _job_snapshot(job_id)
            if snapshot["sequence"] != sequence:
                sequence = snapshot["sequence"]
                yield f"id: {sequence}\ndata: {json.dumps(snapshot)}\n\n"
                heartbeat_ticks = 0
            if snapshot["status"] in {"completed", "failed"}:
                return
            heartbeat_ticks += 1
            if heartbeat_ticks >= 60:
                yield ": heartbeat\n\n"
                heartbeat_ticks = 0
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.post(
    "/runs/{run_id}/items/{item_id}/shap",
    status_code=202,
    summary="Compute On-Demand TreeSHAP for SKU Item",
    description="Dispatches asynchronous on-demand TreeSHAP calculation for a specific item within an active forecast run.",
    response_description="Accepted job status with item and run identifiers.",
)
def start_item_shap(run_id: UUID, item_id: str) -> dict[str, Any]:
    from app.services.item_shap import item_shap_jobs
    try:
        return item_shap_jobs.start(str(run_id), item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get(
    "/runs/{run_id}/items/{item_id}/shap",
    summary="Get On-Demand TreeSHAP Status & Attributions",
    description="Polls computation status and retrieves calculated TreeSHAP feature attributions for a specific SKU item in a forecast run.",
    response_description="TreeSHAP attributions breakdown or current calculation status.",
)
def item_shap_status(run_id: UUID, item_id: str) -> dict[str, Any]:
    from app.services.item_shap import item_shap_jobs
    return item_shap_jobs.status(str(run_id), item_id)


@router.get(
    "/forecast_status",
    deprecated=True,
    summary="Legacy Forecast Progress Stream (Deprecated)",
    description="Deprecated legacy SSE endpoint. Please use POST /api/v1/forecast/runs and subscribe to /runs/{job_id}/events instead.",
)
def forecast_status():
    raise HTTPException(status_code=410, detail="Start a forecast with POST /api/v1/forecast/runs, then subscribe to /runs/{job_id}/events.")


class ExpireSessionRequest(BaseModel):
    session_id: str | None = None


@router.post("/sessions/expire", summary="Expire a forecast session and prune old local files")
def expire_session(req: ExpireSessionRequest | None = None) -> dict[str, Any]:
    from app.services.forecast_artifacts import prune_old_sessions, prune_old_exports
    removed = prune_old_sessions(keep_n=4)
    removed_exports = prune_old_exports(keep_n=5)
    db_pruned = 0
    if req and req.session_id:
        try:
            with SessionLocal() as db:
                db_pruned = delete_forecast_session(db, req.session_id)
        except Exception as exc:
            logger.warning("Failed pruning DB records for expired session %s: %s", req.session_id, exc)

    return {
        "status": "success",
        "expired_session_id": req.session_id if req else None,
        "db_pruned_runs": db_pruned,
        "removed_sessions": removed,
        "removed_exports": removed_exports,
        "kept_limit": 4,
    }


def _query_db_worker(
    uid: str,
    lim: int,
    off: int,
    tk: int,
    run_id: UUID | None = None,
    use_inactive: bool = False,
) -> dict[str, Any] | None:
    """Synchronous worker function to query RDS in a separate thread."""
    with SessionLocal() as session:
        return get_latest_forecast_from_db(
            session,
            unique_id=uid,
            limit=lim,
            offset=off,
            top_k=tk,
            use_inactive_items=use_inactive,
            requested_run_id=run_id,
        )


@router.get(
    "/get_forecast_14d",
    summary="Get 14-Day Recursive Ensemble Forecast",
    description="Returns 14-day predictions, dynamic inventory status, and TreeSHAP drivers. Supports limit & offset for fast Swagger UI testing, and top_k for feature driver aggregation.",
)
async def get_forecast_14d(
    unique_id: str = Query(default="all", description="Item unique_id or 'all'"),
    limit: int = Query(default=50, ge=1, le=6000, description="Max items to return (default 50 for responsive UI/Swagger, up to 6000)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    top_k: int = Query(default=5, ge=0, le=150, description="Number of top SHAP features to return. Remaining features are aggregated into 'Other Features'. Set 0 for 100% full features."),
    use_inactive_items: bool = Query(default=False, description="Whether to include items with 10+ days no sales (default False filters them out immediately)"),
    source: Literal["auto", "database", "cache"] = Query(default="auto", description="Keep the same data source across paginated requests"),
    run_id: UUID | None = Query(default=None, description="Pin database pages to a forecast run"),
) -> dict[str, Any]:
    """Return forecasts; pinned database pages never silently switch to cache."""
    if source == "cache":
        return _get_cached_forecast_payload(unique_id=unique_id, limit=limit, offset=offset)

    pinned_database = source == "database" or run_id is not None
    try:
        try:
            db_res = await asyncio.wait_for(
                asyncio.to_thread(_query_db_worker, unique_id, limit, offset, top_k, run_id, use_inactive_items),
                timeout=25.0 if pinned_database else 2.5,
            )
        except TypeError:
            db_res = await asyncio.wait_for(
                asyncio.to_thread(_query_db_worker, unique_id, limit, offset, top_k, run_id),
                timeout=25.0 if pinned_database else 2.5,
            )
    except asyncio.TimeoutError:
        if pinned_database:
            raise HTTPException(status_code=504, detail="Forecast database query timed out after 25 seconds.")
        logger.warning("RDS query timed out (2.5s), serving cached payload.")
    except Exception as exc:
        logger.warning("Failed querying forecast from RDS: %s", exc)
        if pinned_database:
            raise HTTPException(status_code=503, detail="Forecast database is unavailable. Please try again.") from exc
    else:
        if db_res is not None:
            return db_res
        if pinned_database:
            raise HTTPException(status_code=404, detail="Forecast run is no longer available. Please run the forecast again.")

    return _get_cached_forecast_payload(
        unique_id=unique_id,
        limit=limit,
        offset=offset,
        use_inactive_items=use_inactive_items,
    )


@router.get(
    "/runs",
    summary="List Historical & Active Forecast Runs",
    description="Returns historical and active forecast simulation runs stored in PostgreSQL RDS.",
)
async def list_forecast_runs(
    limit: int = Query(default=20, ge=1, le=100, description="Max runs to return"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return list of historical and active forecast simulation runs."""
    try:
        runs = get_forecast_runs_from_db(db, limit=limit)
        return {
            "status": "success",
            "count": len(runs),
            "runs": runs,
        }
    except Exception as exc:
        logger.error("Failed querying forecast runs: %s", exc)
        return {"status": "error", "message": str(exc), "count": 0, "runs": []}


@router.post(
    "/save_current_forecast",
    summary="Persist Active Forecast to RDS",
    description="Saves current ensemble predictions and 100% TreeSHAP attributions into a new versioned run on PostgreSQL RDS with 10-run retention limit.",
)
async def save_current_forecast(
    model_version: str = Query(default="recursive-ensemble-v1.0", description="Model version identifier"),
    is_latest: bool = Query(default=True, description="Mark this run as active latest forecast"),
    max_runs_to_keep: int = Query(default=10, ge=1, le=50, description="Max recent runs to keep in RDS (retention policy)"),
    session_key: str | None = Query(default=None, description="Optional session identifier to tie this run to a user session"),
    allow_overwrite: bool = Query(default=True, description="Whether to allow overwriting an existing run with same session_key"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Save active forecast run into PostgreSQL RDS and prune older runs."""
    try:
        run = await asyncio.to_thread(
            save_forecast_run,
            db,
            model_version=model_version,
            is_latest=is_latest,
            max_runs_to_keep=max_runs_to_keep,
            session_key=session_key,
            allow_overwrite=allow_overwrite,
        )
        return {
            "status": "success",
            "message": f"Successfully persisted forecast run {run.run_id}",
            "run_id": str(run.run_id),
            "model_version": run.model_version,
            "total_items": run.total_items,
            "total_predicted_demand": run.total_predicted_demand,
            "is_latest": run.is_latest,
            "created_at": run.created_at.isoformat(),
        }
    except Exception as exc:
        logger.error("Failed saving forecast run: %s", exc)
        return {"status": "error", "message": str(exc)}



@router.post(
    "/prune_runs",
    summary="Prune Historical Forecast Runs",
    description="Enforces retention limit by pruning older forecast runs beyond max_runs_to_keep (default 10).",
)
async def prune_forecast_runs(
    max_runs_to_keep: int = Query(default=10, ge=1, le=50, description="Number of most recent runs to retain"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Enforce retention policy by pruning older forecast runs and cascading child records."""
    try:
        pruned_count = await asyncio.to_thread(prune_old_forecast_runs, db, max_runs_to_keep=max_runs_to_keep)
        db.commit()
        return {
            "status": "success",
            "message": f"Successfully pruned {pruned_count} old forecast runs (retaining up to {max_runs_to_keep}).",
            "pruned_count": pruned_count,
            "max_runs_retained": max_runs_to_keep,
        }
    except Exception as exc:
        logger.error("Failed pruning forecast runs: %s", exc)
        return {"status": "error", "message": str(exc)}


class SimulationRequest(BaseModel):
    """Payload for What-If demand and two-way price elasticity simulation."""

    sku_code: str = Field(
        ...,
        description="SKU code (e.g. 'SKU-4471', '4471') or product name (e.g. 'Baguette_40').",
        examples=["Baguette_40"],
    )
    price_change_percent: float = Field(
        default=-20.0,
        ge=-90.0,
        le=150.0,
        description="Percentage change in price. Use NEGATIVE for discounts (e.g. -20 for 20% clearance discount) or POSITIVE for price increase (e.g. +15 for 15% markup).",
        examples=[15.0],
    )
    warehouse: str = Field(
        default="",
        description="Target warehouse distribution hub (e.g. 'Prague_1'). If omitted and product is multi-warehouse, automatically evaluates all distribution hubs.",
        examples=[""],
    )


class ExportPdfRequest(BaseModel):
    """Payload for generating executive multi-page PDF management reports."""

    focus_area: Literal["overview", "critical", "deadstock", "best_seller"] = Field(
        default="overview",
        description="Report topic: 'overview' (Portfolio health), 'critical' (Stockout triage), 'deadstock' (Slow-moving capital traps), or 'best_seller' (High-demand volume drivers).",
        examples=["deadstock"],
    )
    warehouse: str = Field(
        default="all",
        description="Target warehouse distribution hub (e.g. 'Prague_1', 'Brno_1') or 'all' for network-wide synthesis.",
        examples=["Prague_1"],
    )


class ExportReplenishmentRequest(BaseModel):
    """Payload for generating purchase order (PO) replenishment CSV file."""

    warehouse: str = Field(
        default="all",
        description="Target warehouse distribution hub (e.g. 'Prague_1', 'Brno_1') or 'all' for network-wide replenishment orders.",
        examples=["Prague_1"],
    )


@router.post(
    "/simulate",
    summary="Run What-If Demand & Two-Way Price Simulation",
    description=(
        "Executes 14-day ML ensemble re-inference under two-way price changes (discounts: -1% to -90%, "
        "or price increases: +1% to +150%). Calculates 14-day revenue impact (P x Q), Price Elasticity of Demand (PED), "
        "Days of Supply (DOS), and deadstock clearance feasibility. Automatically performs multi-warehouse network "
        "rebalancing and inter-warehouse stock transfer triage."
    ),
    response_description="Simulation metrics including baseline vs simulated demand, revenue delta, PED classification, and markdown report.",
)
def run_demand_simulation(req: SimulationRequest) -> dict[str, Any]:
    """Run two-way price elasticity and demand clearance simulation."""
    from app.services.simulation_service import simulate_sku_price_change, format_simulation_markdown
    result = simulate_sku_price_change(
        sku_or_id=req.sku_code,
        price_change_percent=req.price_change_percent,
        warehouse=req.warehouse,
    )
    if result.get("success"):
        result["markdown_report"] = format_simulation_markdown(result)
    return result


@router.post(
    "/export/pdf",
    summary="Generate Executive Multi-Page PDF Report",
    description=(
        "Generates an executive-grade, presentation-ready multi-page PDF report with embedded vector charts "
        "(Category Donut chart, Top SKU bar charts, and paginated inventory data tables). "
        "Saves the PDF to the exports repository and returns download URL and file metadata."
    ),
    response_description="Report metadata including download URL, filename, and markdown summary.",
)
def generate_pdf_management_report(req: ExportPdfRequest) -> dict[str, Any]:
    """Generate multi-page executive PDF report with embedded charts."""
    import re
    from app.agent.tools import generate_pdf_report
    markdown_output = generate_pdf_report.func(
        focus_area=req.focus_area,
        warehouse=req.warehouse,
    )
    m = re.search(r"(/api/v1/forecast/export/download/[a-zA-Z0-9_\.\-]+)", markdown_output)
    download_url = m.group(1) if m else None
    return {
        "success": bool(download_url),
        "download_url": download_url,
        "message": markdown_output,
    }


@router.post(
    "/export/replenishment",
    summary="Generate PO Replenishment Orders CSV",
    description=(
        "Calculates recommended purchase order (PO) replenishment quantities with safety stock buffers "
        "for a specific warehouse or network-wide, exporting to a CSV file ready for procurement ingestion."
    ),
    response_description="Export metadata including download link, filename, and markdown summary.",
)
def generate_replenishment_orders_csv(req: ExportReplenishmentRequest) -> dict[str, Any]:
    """Generate replenishment orders CSV file ready for ERP ingestion."""
    import re
    from app.agent.tools import export_replenishment_csv
    markdown_output = export_replenishment_csv.func(warehouse=req.warehouse)
    m = re.search(r"(/api/v1/forecast/export/download/[a-zA-Z0-9_\.\-]+)", markdown_output)
    download_url = m.group(1) if m else None
    return {
        "success": bool(download_url),
        "download_url": download_url,
        "message": markdown_output,
    }


@router.get(
    "/export/download/{filename}",
    summary="Download Generated Export File (PDF or CSV)",
    description="Download an executive PDF management report or replenishment CSV file from the exports storage.",
)
def download_export_file(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename parameter")
    export_dir = BACKEND_ROOT / "data" / "exports"
    file_path = export_dir / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Requested export file does not exist")
    media_type = "application/pdf" if filename.lower().endswith(".pdf") else "text/csv; charset=utf-8"
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )
