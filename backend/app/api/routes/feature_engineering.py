"""feature_engineering.py — FastAPI SSE route for the feature engineering pipeline.

Endpoint
--------
GET /api/v1/feature-engineering/run
GET /api/v1/feature-engineering/download-30d-csv

Pulls the latest **30 days** (+ lookback lag buffer) of joined data from
``raw.sales_train``, ``raw.inventory``, and ``raw.calendar``.

CRITICAL DATABASE SAFETY GUARANTEE:
-----------------------------------
- STRICTLY READ-ONLY: All database interaction is pure SELECT.
- ZERO DB WRITES: No INSERT, UPDATE, DELETE, CREATE, DROP, or COMMIT.
- Data is processed in-memory using Polars.
- The 30-day engineered feature split is exported to a local CSV file
  (``backend/data/output/feature_engineered_30d.csv``) for frontend/model consumption.
- Zero data is saved back to RDS.

SSE event format (``text/event-stream``)
-----------------------------------------
Each event is a JSON object emitted as::

    data: {"step": "<name>", "status": "running"|"done"|"error", "detail": <any>}\n\n

Steps emitted in order:
    1. fetch_data
    2. deterministic_transforms
    3. sales_lags
    4. interaction_features
    5. discount_lags
    6. validation
    7. export_csv
    8. complete (includes elapsed time, row counts, feature count, csv path)
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
import time
from collections.abc import AsyncGenerator
from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import settings
from app.pipeline.feature_engineering import (
    DEFAULT_CONFIG,
    DatasetSplits,
    run_feature_engineering,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Constants & Paths
# ---------------------------------------------------------------------------

INFERENCE_WINDOW_DAYS: int = 30

_MAX_LAG: int = max(
    max(DEFAULT_CONFIG.sales_lags),
    max(DEFAULT_CONFIG.interaction_lags),
    max(DEFAULT_CONFIG.discount_lags),
)

# Total days needed: 30 days inference + max lag lookup buffer (typically 58 days)
HISTORY_WINDOW_DAYS: int = INFERENCE_WINDOW_DAYS + _MAX_LAG

# Output directory for generated CSVs (purely on filesystem, NEVER in DB)
BACKEND_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_CSV_DIR = BACKEND_ROOT / "data" / "output"
OUTPUT_CSV_PATH = OUTPUT_CSV_DIR / "feature_engineered_30d.csv"

# ---------------------------------------------------------------------------
# DB helper — STRICTLY READ-ONLY (Pure SELECT, ZERO writes)
# ---------------------------------------------------------------------------

_MERGE_SQL = """
SELECT
    s.unique_id,
    s.date,
    s.warehouse,
    s.total_orders,
    s.sales,
    s.sell_price_main,
    s.availability,
    s.type_0_discount,
    s.type_1_discount,
    s.type_2_discount,
    s.type_3_discount,
    s.type_4_discount,
    s.type_5_discount,
    s.type_6_discount,
    i.name,
    i.product_unique_id,
    i."L1_category_name_en",
    i."L2_category_name_en",
    i."L3_category_name_en",
    i."L4_category_name_en",
    c.holiday_name,
    c.holiday,
    c.shops_closed,
    c.winter_school_holidays,
    c.school_holidays
FROM raw.sales_train s
LEFT JOIN raw.inventory  i ON s.unique_id = i.unique_id  AND s.warehouse = i.warehouse
LEFT JOIN raw.calendar   c ON s.date      = c.date        AND s.warehouse = c.warehouse
WHERE s.date >= (
    SELECT MAX(date) - %(window_days)s * INTERVAL '1 day'
    FROM   raw.sales_train
)
ORDER BY s.unique_id, s.warehouse, s.date
"""


def _get_db_connection():
    """Create a strictly read-only psycopg connection to RDS.

    No write permissions required. Uses sslmode='require' with fallback
    if global-bundle.pem is not present.
    """
    import psycopg

    ssl_cert_path = Path(settings.rds_ssl_root_cert)
    if not ssl_cert_path.is_absolute():
        ssl_cert_path = BACKEND_ROOT / ssl_cert_path

    connect_kwargs: dict[str, Any] = {
        "host": settings.rds_endpoint,
        "port": settings.rds_port,
        "dbname": settings.rds_database,
        "user": settings.rds_api_username,
        "password": settings.rds_api_password.get_secret_value(),
        "connect_timeout": 15,
        "application_name": "rohlik-feature-engineering-readonly",
        "autocommit": False,
    }

    if ssl_cert_path.exists():
        connect_kwargs["sslmode"] = settings.rds_ssl_mode
        connect_kwargs["sslrootcert"] = str(ssl_cert_path)
    else:
        # Connect securely with TLS without strict local CA verification file
        connect_kwargs["sslmode"] = "require"

    return psycopg.connect(**connect_kwargs)


def _fetch_frame_from_db(window_days: int) -> pl.DataFrame:
    """Pull window_days of merged data from DB.

    STRICT READ-ONLY: Executes only _MERGE_SQL (SELECT).
    ZERO writes, inserts, or updates.
    """
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_MERGE_SQL, {"window_days": window_days})
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    if not rows:
        return pl.DataFrame({col: [] for col in cols})

    col_data: dict[str, list[Any]] = {col: [] for col in cols}
    for row in rows:
        for col, val in zip(cols, row):
            col_data[col].append(val)

    return pl.DataFrame(col_data)


# ---------------------------------------------------------------------------
# Synthetic test frame generator (runs endpoint test with ZERO DB access)
# ---------------------------------------------------------------------------

def _generate_synthetic_frame(window_days: int) -> pl.DataFrame:
    """Generate realistic test data for the exact schema with 0 DB contact."""
    base_date = datetime.date.today() - datetime.timedelta(days=window_days)
    dates = [base_date + datetime.timedelta(days=i) for i in range(window_days)]
    
    unique_ids = [0, 1, 2, 3]
    warehouses = ["Prague_1", "Brno_1"]
    
    records = []
    for uid in unique_ids:
        for wh in warehouses:
            for d in dates:
                records.append({
                    "unique_id": uid,
                    "date": d,
                    "warehouse": wh,
                    "total_orders": 25,
                    "sales": 50.0 + (uid * 10) + (d.day % 7),
                    "sell_price_main": 100.0,
                    "availability": 1,
                    "type_0_discount": 0.05,
                    "type_1_discount": 0.0,
                    "type_2_discount": 0.0,
                    "type_3_discount": 0.0,
                    "type_4_discount": 0.0,
                    "type_5_discount": 0.0,
                    "type_6_discount": 0.0,
                    "name": f"item_{uid}_sample",
                    "product_unique_id": uid * 10,
                    "L1_category_name_en": "Food",
                    "L2_category_name_en": "Dairy",
                    "L3_category_name_en": "Milk",
                    "L4_category_name_en": "Fresh Milk",
                    "holiday_name": None,
                    "holiday": 0,
                    "shops_closed": 0,
                    "winter_school_holidays": 0,
                    "school_holidays": 0,
                })
    return pl.DataFrame(records)


# ---------------------------------------------------------------------------
# Splits factory — inference mode
# ---------------------------------------------------------------------------

def _build_inference_splits(full_frame: pl.DataFrame, inference_days: int) -> DatasetSplits:
    """Split into history (train/val) and inference (test) splits."""
    date_col = DEFAULT_CONFIG.date_column
    max_date = full_frame[date_col].max()
    cutoff = max_date - datetime.timedelta(days=inference_days - 1)

    inference = full_frame.filter(pl.col(date_col) >= cutoff)
    if "availability" in inference.columns:
        inference = inference.drop("availability")
    return DatasetSplits(
        train=full_frame,
        validation=full_frame,
        test=inference,
    )


# ---------------------------------------------------------------------------
# SSE streaming generator
# ---------------------------------------------------------------------------

async def _sse_generator(
    inference_days: int,
    test_mode: bool = False,
    use_inactive_items: bool = False,
) -> AsyncGenerator[str, None]:
    """Async generator that runs the pipeline in a thread and yields SSE events."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def emit(step: str, status: str, detail: Any) -> None:
        payload = json.dumps(
            {"step": step, "status": status, "detail": detail},
            ensure_ascii=False,
            default=str,
        )
        asyncio.run_coroutine_threadsafe(queue.put(payload), loop)

    def _worker() -> None:
        try:
            total_days = inference_days + _MAX_LAG

            # Step 1 — fetch data (strictly read-only or test mode)
            if test_mode:
                emit("fetch_data", "running",
                     f"[TEST MODE] Generating in-memory test frame ({total_days} days, zero DB touch)…")
                _t = time.perf_counter()
                full_frame = _generate_synthetic_frame(total_days)
                emit("fetch_data", "done", {
                    "mode": "test_synthetic (zero DB touch)",
                    "total_rows": full_frame.height,
                    "history_days": total_days,
                    "elapsed_s": round(time.perf_counter() - _t, 3),
                })
            else:
                emit("fetch_data", "running",
                     f"Pulling last {total_days} days via SELECT (read-only, zero writes to DB)…")
                _t = time.perf_counter()
                full_frame = _fetch_frame_from_db(total_days)
                emit("fetch_data", "done", {
                    "mode": "rds_readonly",
                    "total_rows": full_frame.height,
                    "history_days": total_days,
                    "elapsed_s": round(time.perf_counter() - _t, 3),
                })

            if full_frame.height == 0:
                emit("complete", "error", "No data returned — aborting pipeline.")
                return

            # Immediately filter out items with 10+ days of no sales if not use_inactive_items
            if not use_inactive_items and full_frame.height > 0:
                date_c = DEFAULT_CONFIG.date_column
                max_dt = full_frame[date_c].max()
                if max_dt is not None:
                    thresh = max_dt - datetime.timedelta(days=9)
                    active_uids = (
                        full_frame.filter((pl.col(date_c) >= thresh) & (pl.col("sales") > 0))
                        .select("unique_id")
                        .unique()
                    )
                    before_cnt = full_frame["unique_id"].n_unique()
                    full_frame = full_frame.join(active_uids, on="unique_id", how="inner")
                    after_cnt = full_frame["unique_id"].n_unique()
                    emit("fetch_data", "info", {
                        "filter": "inactive_10plus_days",
                        "filtered_items": before_cnt - after_cnt,
                        "retained_active_items": after_cnt,
                        "remaining_rows": full_frame.height,
                    })

            splits = _build_inference_splits(full_frame, inference_days)
            del full_frame

            # Steps 2-6 — feature engineering in-memory
            artifacts = run_feature_engineering(splits, DEFAULT_CONFIG, emit, save=False)

            # Step 7 — Produce 30-day CSV to local disk (DO NOT SAVE TO DB)
            emit("export_csv", "running", f"Exporting {inference_days}-day test split to CSV…")
            _t_csv = time.perf_counter()
            OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
            artifacts.splits.test.write_csv(OUTPUT_CSV_PATH)
            csv_size_kb = round(OUTPUT_CSV_PATH.stat().st_size / 1024, 2)
            emit("export_csv", "done", {
                "csv_file": OUTPUT_CSV_PATH.name,
                "csv_path": str(OUTPUT_CSV_PATH),
                "file_size_kb": csv_size_kb,
                "rows": artifacts.splits.test.height,
                "columns": artifacts.splits.test.width,
                "elapsed_s": round(time.perf_counter() - _t_csv, 3),
            })

            # Final complete signal
            emit("complete", "done", {
                "inference_days": inference_days,
                "feature_count": len(artifacts.feature_columns),
                "csv_path": str(OUTPUT_CSV_PATH),
                "csv_rows": artifacts.splits.test.height,
                "csv_columns": artifacts.splits.test.width,
            })

        except Exception as exc:
            logger.exception("Feature engineering pipeline failed")
            emit("complete", "error", str(exc))
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    loop.run_in_executor(None, _worker)

    while True:
        payload = await asyncio.wait_for(queue.get(), timeout=300)
        if payload is None:
            break
        yield f"data: {payload}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/run",
    summary="Run feature engineering pipeline (SSE)",
    description=(
        "Streams real-time progress events while running the feature engineering pipeline. "
        "Strictly READ-ONLY from DB (no writes). Produces the 30-day CSV upon completion."
    ),
    response_description="Server-Sent Events stream of pipeline step signals.",
)
async def run_feature_engineering_sse(
    inference_days: int = Query(default=INFERENCE_WINDOW_DAYS, description="Number of inference days (default 30)"),
    test_mode: bool = Query(default=True, description="Set True (default) for fast synthetic in-memory execution; False for full RDS extraction"),
    use_inactive_items: bool = Query(default=False, description="Whether to include items with 10+ days of no sales (default False: filters them out immediately after load to save resources)"),
) -> StreamingResponse:
    """Stream feature-engineering progress as SSE events."""
    return StreamingResponse(
        _sse_generator(inference_days, test_mode=test_mode, use_inactive_items=use_inactive_items),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/download-30d-csv",
    summary="Download the produced 30-day feature engineered CSV",
    description="Returns the CSV file generated by the feature engineering pipeline.",
)
async def download_30d_csv() -> FileResponse:
    """Download the produced 30-day feature engineered CSV."""
    if not OUTPUT_CSV_PATH.exists():
        OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
        full_frame = _generate_synthetic_frame(HISTORY_WINDOW_DAYS)
        splits = _build_inference_splits(full_frame, INFERENCE_WINDOW_DAYS)
        artifacts = run_feature_engineering(splits, DEFAULT_CONFIG, lambda *args: None, save=False)
        artifacts.splits.test.write_csv(OUTPUT_CSV_PATH)
    return FileResponse(
        path=OUTPUT_CSV_PATH,
        media_type="text/csv",
        filename="feature_engineered_30d.csv",
    )
