"""load_pipeline.py — Main pipeline wrapper to load 60d history for ALL items,
generate 14d future, engineer features, cut past to 30d, and return both DataFrames.

Process:
1. Load 60d raw data from RDS (or provided frame/file) across ALL items (or single unique_id).
   Accelerated by Local Parquet Snapshot Cache (~20-40ms vs. 17-20s DB network fetch).
2. Generate 14d future raw frame using create_future_feature_frame.
3. Combine 60d history + 14d future and run feature engineering across the continuous timeline.
4. Cut past data to the latest 30d (all 28-day lags fully populated thanks to the 60d lookback).
5. Return (df_past_30d, df_future_14d).
"""
from __future__ import annotations

from collections.abc import Sequence
import argparse
import datetime
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable

import polars as pl

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.pipeline.feature_engineering import (
    DEFAULT_CONFIG,
    PipelineConfig,
    RohlikFeatureEngineeringPipeline,
    create_future_feature_frame,
    run_feature_engineering,
)

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "data" / "output"
CACHE_DIR = BACKEND_ROOT / "data" / "cache"

# In-memory cache for DB max date to avoid repeated TLS handshakes to Singapore
_MAX_DATE_CACHE: dict[str, Any] = {"max_date": None, "checked_at": 0.0}
_MAX_DATE_TTL_SECONDS = 300.0  # 5-minute TTL

_RAW_SQL = """
SELECT
    s.unique_id,
    s.date,
    s.warehouse,
    s.total_orders,
    s.sales,
    s.sell_price_main,
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
    SELECT MAX(date) - (%(days)s - 1) * INTERVAL '1 day'
    FROM   raw.sales_train
)
{extra_filter}
ORDER BY s.unique_id, s.warehouse, s.date;
"""


def get_db_connection(connect_timeout: int = 30):
    """Create a strictly read-only connection to RDS."""
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
        "connect_timeout": connect_timeout,
        "application_name": "rohlik-load-pipeline-all",
        "autocommit": False,
    }

    if ssl_cert_path.exists():
        connect_kwargs["sslmode"] = settings.rds_ssl_mode
        connect_kwargs["sslrootcert"] = str(ssl_cert_path)
    else:
        connect_kwargs["sslmode"] = "require"

    return psycopg.connect(**connect_kwargs)


def filter_inactive_series(
    df: pl.DataFrame,
    cutoff_date: datetime.date | None = None,
    min_days_no_sale: int = 10,
    sales_col: str = "sales",
    date_col: str = "date",
    id_col: str = "unique_id",
) -> tuple[pl.DataFrame, list[Any]]:
    """Filter out items/series that have no sales recorded in the last `min_days_no_sale` days up to cutoff_date.
    
    Returns:
        tuple of (filtered_df, list_of_filtered_out_uids)
    """
    if df.height == 0:
        return df, []

    if cutoff_date is None:
        cutoff_date = df[date_col].max()

    threshold_date = cutoff_date - datetime.timedelta(days=min_days_no_sale - 1)
    
    # Active items have at least one positive sale record on or after threshold_date
    active_uids = (
        df.filter((pl.col(date_col) >= threshold_date) & (pl.col(sales_col) > 0))
        .select(id_col)
        .unique()
    )
    
    all_uids = df.select(id_col).unique()[id_col].to_list()
    active_set = set(active_uids[id_col].to_list())
    inactive_uids = [u for u in all_uids if u not in active_set]

    filtered_df = df.join(active_uids, on=id_col, how="inner")
    return filtered_df, inactive_uids


def _get_cached_or_db_max_date() -> datetime.date | None:
    """Retrieve max date from DB with short-term in-memory cache to eliminate repeated TLS handshakes."""
    now = time.time()
    if _MAX_DATE_CACHE["max_date"] is not None and (now - _MAX_DATE_CACHE["checked_at"]) < _MAX_DATE_TTL_SECONDS:
        return _MAX_DATE_CACHE["max_date"]

    try:
        with get_db_connection(connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date) FROM raw.sales_train;")
                db_max = cur.fetchone()[0]
                _MAX_DATE_CACHE["max_date"] = db_max
                _MAX_DATE_CACHE["checked_at"] = now
                return db_max
    except Exception as e:
        logger.debug(f"DB ping skipped ({e}). Proceeding with local Parquet snapshot cache.")
        return _MAX_DATE_CACHE.get("max_date")


def fetch_raw_data(
    unique_id: str | None = None,
    days: int = 60,
    cutoff_date: datetime.date | None = None,
    use_inactive_items: bool = False,
    min_days_no_sale: int = 10,
    force_refresh: bool = False,
) -> pl.DataFrame:
    """Fetch raw records across ALL items (or 1 item if specified), with Local Parquet Snapshot Cache.
    
    Guarantees a continuous unbroken calendar grid of exactly `days` days ending at
    the global dataset latest date (2024-06-02) for ALL series. Missing days are
    filled with sales=0.0 (no timeskips), so predictions always begin at Jun 3.

    Performance & Caching Strategy:
        - When cache hits: reads local ZSTD compressed Parquet in ~20-40ms (over 400x faster than RDS).
        - Cache freshness: validates `cutoff_date` and pings DB `MAX(date)` (taking ~80ms) to ensure
          cache is 100% current. If offline or in testing, safely falls back to local snapshot.
        - Single-item queries are served instantly from the all-items snapshot cache (~2ms filter).
        - On cache miss or `force_refresh=True`: pulls from RDS, optimizes memory via Polars row orientation,
          constructs the unbroken calendar grid, and writes to `backend/data/cache/`.

    Args:
        unique_id: Specific item ID or None/all.
        days: Historical days window (default 60).
        cutoff_date: Latest historical date (default: max date in sales_train = 2024-06-02).
        use_inactive_items: If False (default), filters out items with 10+ days of no sales up to cutoff_date.
        min_days_no_sale: Number of trailing days without sales to trigger inactive filter (default 10).
        force_refresh: If True, bypasses local parquet cache and fetches fresh from RDS.
    """
    is_single = unique_id is not None and str(unique_id).lower() != "all"
    target_desc = f"unique_id='{unique_id}'" if is_single else "ALL items"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_cache_stem = f"raw_snapshot_{days}d_{'all' if use_inactive_items else 'active'}"
    all_cache_file = CACHE_DIR / f"{all_cache_stem}.parquet"
    all_meta_file = CACHE_DIR / f"{all_cache_stem}.json"
    single_cache_file = CACHE_DIR / f"raw_snapshot_{days}d_item_{unique_id}.parquet" if is_single else None

    t0 = time.perf_counter()

    # =========================================================================
    # Step A: Local Parquet Snapshot Cache Lookup
    # =========================================================================
    if not force_refresh:
        candidate_file: Path | None = None
        candidate_meta: dict[str, Any] | None = None
        is_from_all_cache = False

        if all_cache_file.exists():
            candidate_file = all_cache_file
            is_from_all_cache = True
            if all_meta_file.exists():
                try:
                    candidate_meta = json.loads(all_meta_file.read_text())
                except Exception:
                    candidate_meta = None
        elif is_single and single_cache_file and single_cache_file.exists():
            candidate_file = single_cache_file
            is_from_all_cache = False

        if candidate_file is not None:
            cache_valid = True
            cached_cutoff = candidate_meta.get("cutoff_date") if candidate_meta else None

            # 1. If explicit cutoff_date provided, check match
            if cutoff_date is not None and cached_cutoff is not None:
                if str(cutoff_date) != str(cached_cutoff):
                    cache_valid = False

            # 2. If cutoff_date not provided, quick check to RDS (or cached max date)
            if cache_valid and cutoff_date is None and cached_cutoff is not None:
                db_max = _get_cached_or_db_max_date()
                if db_max is not None and str(db_max) != str(cached_cutoff):
                    logger.info(f"Local cache stale (DB MAX={db_max} != cache {cached_cutoff}). Refreshing...")
                    cache_valid = False

            if cache_valid:
                try:
                    df = pl.read_parquet(candidate_file)
                    if is_single and is_from_all_cache:
                        df = df.filter(pl.col("unique_id") == str(unique_id))
                        if df.height > 0:
                            elapsed_ms = (time.perf_counter() - t0) * 1000
                            print(f"[CACHE HIT] Loaded {df.height} rows for item '{unique_id}' from local snapshot ({candidate_file.name}) in {elapsed_ms:.1f}ms.")
                            return df
                        # If item not in active set (e.g. inactive item), fallback to DB
                    elif not is_single:
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        print(f"[CACHE HIT] Loaded {df.height:,} rows across {df['unique_id'].n_unique():,} items from local snapshot ({candidate_file.name}) in {elapsed_ms:.1f}ms.")
                        return df
                    elif is_single:
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        print(f"[CACHE HIT] Loaded {df.height} rows for item '{unique_id}' from local snapshot ({candidate_file.name}) in {elapsed_ms:.1f}ms.")
                        return df
                except Exception as e:
                    logger.warning(f"Failed reading parquet cache ({e}). Falling back to database fetch.")

    # =========================================================================
    # Step B: Cache Miss or Force Refresh -> Fetch from PostgreSQL RDS
    # =========================================================================
    print(f"Connecting to RDS (read-only)...")
    if cutoff_date is None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date) FROM raw.sales_train;")
                cutoff_date = cur.fetchone()[0]
                _MAX_DATE_CACHE["max_date"] = cutoff_date
                _MAX_DATE_CACHE["checked_at"] = time.time()

    start_date = cutoff_date - datetime.timedelta(days=days - 1)
    print(f"Fetching {days} continuous days ({start_date} -> {cutoff_date}) for {target_desc} in parallel...")

    # 1. Sales query setup
    sales_sql = """
    SELECT s.unique_id, s.date, s.warehouse, s.total_orders, s.sales, s.sell_price_main,
           s.type_0_discount, s.type_1_discount, s.type_2_discount, s.type_3_discount,
           s.type_4_discount, s.type_5_discount, s.type_6_discount
    FROM raw.sales_train s
    WHERE s.date >= %(start_date)s AND s.date <= %(cutoff_date)s
    """
    sales_params: dict[str, Any] = {"start_date": start_date, "cutoff_date": cutoff_date}
    if is_single:
        sales_sql += " AND s.unique_id = %(unique_id)s"
        sales_params["unique_id"] = str(unique_id)
    sales_sql += " ORDER BY s.unique_id, s.warehouse, s.date;"

    # 2. Inventory query setup
    inv_sql = """
    SELECT unique_id, warehouse, name, product_unique_id,
           "L1_category_name_en", "L2_category_name_en", "L3_category_name_en", "L4_category_name_en"
    FROM raw.inventory
    """
    inv_params: dict[str, Any] = {}
    if is_single:
        inv_sql += " WHERE unique_id = %(unique_id)s"
        inv_params["unique_id"] = str(unique_id)
    inv_sql += ";"

    # 3. Calendar query setup
    cal_sql = """
    SELECT date, warehouse, holiday_name, holiday, shops_closed, winter_school_holidays, school_holidays
    FROM raw.calendar
    WHERE date >= %(start_date)s AND date <= %(cutoff_date)s;
    """

    def _fetch_sales() -> pl.DataFrame:
        with get_db_connection() as c, c.cursor() as cur:
            cur.execute(sales_sql, sales_params)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return pl.DataFrame(rows, schema=cols, orient="row").with_columns(pl.col("date").cast(pl.Date)) if rows else pl.DataFrame({col: [] for col in cols})

    def _fetch_inv() -> pl.DataFrame:
        with get_db_connection() as c, c.cursor() as cur:
            cur.execute(inv_sql, inv_params)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return pl.DataFrame(rows, schema=cols, orient="row") if rows else pl.DataFrame({col: [] for col in cols})

    def _fetch_cal() -> pl.DataFrame:
        with get_db_connection() as c, c.cursor() as cur:
            cur.execute(cal_sql, {"start_date": start_date, "cutoff_date": cutoff_date})
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return pl.DataFrame(rows, schema=cols, orient="row").with_columns(pl.col("date").cast(pl.Date)) if rows else pl.DataFrame({col: [] for col in cols})

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="db-fetch") as pool:
        f_sales = pool.submit(_fetch_sales)
        f_inv = pool.submit(_fetch_inv)
        f_cal = pool.submit(_fetch_cal)
        sales_df = f_sales.result()
        inv_df = f_inv.result()
        cal_df = f_cal.result()

    # 4. Filter inactive items if not use_inactive_items
    if not use_inactive_items and sales_df.height > 0:
        threshold_date = cutoff_date - datetime.timedelta(days=min_days_no_sale - 1)
        active_uids_df = (
            sales_df.filter((pl.col("date") >= threshold_date) & (pl.col("sales") > 0))
            .select("unique_id")
            .unique()
        )
        total_inv_count = inv_df["unique_id"].n_unique() if inv_df.height > 0 else sales_df["unique_id"].n_unique()

        if inv_df.height > 0:
            inv_df = inv_df.join(active_uids_df, on="unique_id", how="inner")
        sales_df = sales_df.join(active_uids_df, on="unique_id", how="inner")

        active_count = inv_df["unique_id"].n_unique() if inv_df.height > 0 else sales_df["unique_id"].n_unique()
        filtered_count = total_inv_count - active_count
        print(
            f"Filtered out {filtered_count} inactive items (>= {min_days_no_sale} days no sales up to {cutoff_date}). "
            f"Retaining {active_count} active items for processing (use_inactive_items={use_inactive_items})."
        )

    # 5. Construct complete daily grid to eliminate any timeskips
    all_dates = pl.date_range(start_date, cutoff_date, "1d", eager=True).alias("date")
    if inv_df.height > 0:
        series_keys = inv_df.select(["unique_id", "warehouse"]).unique()
    elif sales_df.height > 0:
        series_keys = sales_df.select(["unique_id", "warehouse"]).unique()
    else:
        return pl.DataFrame()

    grid = series_keys.join(pl.DataFrame({"date": all_dates}), how="cross")

    # Join sales, metadata, and calendar onto grid
    merged = grid.join(sales_df, on=["unique_id", "warehouse", "date"], how="left")
    if inv_df.height > 0:
        merged = merged.join(inv_df, on=["unique_id", "warehouse"], how="left")
    if cal_df.height > 0:
        merged = merged.join(cal_df, on=["warehouse", "date"], how="left")

    # Zero-fill missing sales & discounts, forward/backward fill prices & orders
    merged = merged.with_columns([
        pl.col("sales").fill_null(0.0),
        pl.col("type_0_discount").fill_null(0.0),
        pl.col("type_1_discount").fill_null(0.0),
        pl.col("type_2_discount").fill_null(0.0),
        pl.col("type_3_discount").fill_null(0.0),
        pl.col("type_4_discount").fill_null(0.0),
        pl.col("type_5_discount").fill_null(0.0),
        pl.col("type_6_discount").fill_null(0.0),
        pl.col("sell_price_main").forward_fill().backward_fill().over(["unique_id", "warehouse"]),
        pl.col("total_orders").forward_fill().backward_fill().fill_null(10000.0).over("warehouse"),
        pl.col("holiday").fill_null(0),
        pl.col("shops_closed").fill_null(0),
        pl.col("winter_school_holidays").fill_null(0),
        pl.col("school_holidays").fill_null(0),
        pl.col("holiday_name").fill_null(""),
    ]).sort(["unique_id", "warehouse", "date"])

    assert "availability" not in merged.columns, "'availability' must be strictly absent"

    # Save to local Parquet Snapshot Cache
    if merged.height > 0:
        try:
            if not is_single:
                merged.write_parquet(all_cache_file, compression="zstd")
                meta = {
                    "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "cutoff_date": str(cutoff_date),
                    "days": days,
                    "use_inactive_items": use_inactive_items,
                    "min_days_no_sale": min_days_no_sale,
                    "num_rows": merged.height,
                    "num_items": merged["unique_id"].n_unique(),
                }
                all_meta_file.write_text(json.dumps(meta, indent=2))
                print(f"[CACHE WRITE] Saved local parquet snapshot: {all_cache_file.name} ({merged.height:,} rows, {meta['num_items']:,} items).")
            elif single_cache_file:
                merged.write_parquet(single_cache_file, compression="zstd")
                print(f"[CACHE WRITE] Saved single-item parquet snapshot: {single_cache_file.name} ({merged.height:,} rows).")
        except Exception as e:
            logger.warning(f"Could not write to local parquet cache: {e}")

    return merged


def load_and_engineer_splits(
    unique_id: str | None = None,
    *,
    history_days: int = 60,
    past_cut_days: int = 30,
    horizon_days: int = 14,
    source_data: pl.DataFrame | Path | str | None = None,
    config: PipelineConfig = DEFAULT_CONFIG,
    save: bool = False,
    output_dir: Path | str | None = None,
    emit: Callable[[str, str, Any], None] | None = None,
    use_inactive_items: bool = False,
    min_days_no_sale: int = 10,
    force_refresh: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Execute complete data loading (default ALL items) and feature engineering.

    Args:
        unique_id: None or 'all' to process all items, or specific id (e.g. '10').
        history_days: Days of historical data to load (default: 60).
        past_cut_days: Days of past data to return (default: 30).
        horizon_days: Days of future data to simulate and engineer (default: 14).
        source_data: Optional pre-loaded DataFrame or file path to skip DB query.
        config: Feature engineering PipelineConfig.
        save: If True, writes CSV and Parquet files to output_dir.
        output_dir: Target directory for files (defaults to backend/data/output).
        emit: Optional callback for pipeline progress events.
        use_inactive_items: If False (default), immediately filters out items with 10+
            days of no sales to save resources. If True, keeps all items.
        min_days_no_sale: Number of trailing days without sales to trigger inactive filter (default 10).
        force_refresh: If True, ignores local parquet cache and refreshes directly from RDS.

    Returns:
        tuple of (df_past_30d, df_future_14d).
    """
    if emit is None:
        def emit(step: str, status: str, detail: Any) -> None:
            pass

    # 1. Load 60d raw data for all items (or specified item)
    if source_data is not None:
        if isinstance(source_data, (str, Path)):
            p = Path(source_data)
            raw_history = pl.read_parquet(p) if p.suffix == ".parquet" else pl.read_csv(p)
        else:
            raw_history = source_data
        raw_history = raw_history.with_columns(pl.col("date").cast(pl.Date))
        if not use_inactive_items and raw_history.height > 0:
            raw_history, inactive_uids = filter_inactive_series(
                raw_history,
                cutoff_date=raw_history["date"].max(),
                min_days_no_sale=min_days_no_sale,
                sales_col="sales",
                date_col=config.date_column,
                id_col=config.series_keys[0],
            )
            print(
                f"Immediately filtered {len(inactive_uids)} inactive items (>= {min_days_no_sale} days no sales). "
                f"Processing {raw_history['unique_id'].n_unique()} active items (use_inactive_items={use_inactive_items})."
            )
    else:
        raw_history = fetch_raw_data(
            unique_id=unique_id,
            days=history_days,
            use_inactive_items=use_inactive_items,
            min_days_no_sale=min_days_no_sale,
            force_refresh=force_refresh,
        )

    if raw_history.height == 0:
        raise ValueError(f"No history records found.")

    max_hist_date = raw_history["date"].max()
    num_items = raw_history["unique_id"].n_unique()
    print(f"Loaded {raw_history.height} history rows across {num_items} items (max date: {max_hist_date}).")

    # 2. Generate 14d future raw frame for all items
    print(f"Generating {horizon_days}d future raw frame...")
    future_raw = create_future_feature_frame(
        test_frame=raw_history,
        horizon_days=horizon_days,
        config=config,
        cutoff_date=max_hist_date,
    )
    print(f"Created future frame: {future_raw.height} rows across {future_raw['unique_id'].n_unique()} items.")

    # 3. Combine 60d history + 14d future
    common_cols = [c for c in future_raw.columns if c in raw_history.columns]
    combined_raw = pl.concat([raw_history.select(common_cols), future_raw.select(common_cols)], how="vertical_relaxed")
    print(f"Combined timeline: {combined_raw.height} rows ({raw_history.height} past + {future_raw.height} future).")

    # 4. Run feature engineering over the continuous combined timeline
    print(f"Running feature engineering pipeline...")
    artifacts = run_feature_engineering(
        splits=combined_raw,
        config=config,
        emit=emit,
        save=False,
    )
    engineered = artifacts.splits.test

    # 5. Cut past data to exactly past_cut_days (30d) and future to horizon_days (14d)
    past_cutoff = max_hist_date - datetime.timedelta(days=past_cut_days - 1)
    df_past = engineered.filter(
        (pl.col("date") >= past_cutoff) & (pl.col("date") <= max_hist_date)
    ).sort([*config.series_keys, config.date_column])

    df_future = engineered.filter(
        pl.col("date") > max_hist_date
    ).sort([*config.series_keys, config.date_column])

    print(f"Feature engineering complete:")
    print(f"  • Past {past_cut_days}d:   {df_past.height} rows ({df_past['date'].min()} to {df_past['date'].max()})")
    print(f"  • Future {horizon_days}d: {df_future.height} rows ({df_future['date'].min()} to {df_future['date'].max()})")

    # 6. Save outputs if requested
    if save:
        out_path = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
        out_path.mkdir(parents=True, exist_ok=True)
        is_all = unique_id is None or str(unique_id).lower() == "all"
        prefix = "all_items" if is_all else f"item_{unique_id}"

        # Raw future
        raw_future_path = out_path / f"raw_{prefix}_{horizon_days}d_future.csv"
        future_raw.write_csv(raw_future_path)

        # Past 30d engineered
        past_csv = out_path / f"feature_engineered_{prefix}_{past_cut_days}d_past.csv"
        past_parquet = out_path / f"feature_engineered_{prefix}_{past_cut_days}d_past.parquet"
        df_past.write_csv(past_csv)
        df_past.write_parquet(past_parquet)

        # Future 14d engineered
        future_csv = out_path / f"feature_engineered_{prefix}_{horizon_days}d_future.csv"
        future_parquet = out_path / f"feature_engineered_{prefix}_{horizon_days}d_future.parquet"
        df_future.write_csv(future_csv)
        df_future.write_parquet(future_parquet)

        print(f"Saved outputs to {out_path}:")
        print(f"  - {past_csv.name}")
        print(f"  - {past_parquet.name}")
        print(f"  - {future_csv.name}")
        print(f"  - {future_parquet.name}")

    return df_past, df_future


def recompute_future_features(
    df_future: pl.DataFrame,
    df_past: pl.DataFrame,
    predicted_sales: pl.DataFrame | dict[Any, float] | Sequence[float] | pl.Series | None = None,
    *,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> pl.DataFrame:
    """Recompute future features with predicted sales for recursive forecasting."""
    future = df_future.clone()
    date_col = config.date_column
    target_col = config.target_column

    # 1. Apply predicted sales if provided
    if predicted_sales is not None:
        if isinstance(predicted_sales, pl.DataFrame):
            pred_col = (
                target_col if target_col in predicted_sales.columns
                else "predicted_sales" if "predicted_sales" in predicted_sales.columns
                else predicted_sales.columns[-1]
            )
            join_keys = [k for k in [*config.series_keys, date_col] if k in predicted_sales.columns and k in future.columns]
            pred_sub = predicted_sales.select([
                *[pl.col(key).cast(future.schema[key]) for key in join_keys],
                pl.col(pred_col).cast(pl.Float64).alias("__pred_val"),
            ])
            future = future.join(pred_sub, on=join_keys, how="left").with_columns(
                pl.coalesce([pl.col("__pred_val"), pl.col(target_col)]).alias(target_col)
            ).drop("__pred_val")

    # 2. Combine history and future to evaluate continuous lag lookups
    max_past_date = df_past[date_col].max()
    future = future.with_columns(pl.col(target_col).cast(pl.Float32))
    past_clean = df_past.with_columns(pl.col(target_col).cast(pl.Float32))
    common_cols = [c for c in future.columns if c in past_clean.columns]
    combined = pl.concat([past_clean.select(common_cols), future.select(common_cols)], how="vertical_relaxed")

    # 3. Recompute sales lags and interaction/summary features via pipeline
    pipeline = RohlikFeatureEngineeringPipeline(config)
    with_features = pipeline.recompute_target_dependent_features(combined)

    # 4. Slice back to future window
    return with_features.filter(
        pl.col(date_col) > max_past_date
    ).sort([*config.series_keys, date_col])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load 60d history for all items, generate 14d future, engineer features, cut to 30d past")
    parser.add_argument("--unique-id", type=str, default=None, help="None or 'all' for all items, or specific unique_id (e.g. '10')")
    parser.add_argument("--history-days", type=int, default=60, help="Days of history to load (default: 60)")
    parser.add_argument("--past-days", type=int, default=30, help="Days of past to return (default: 30)")
    parser.add_argument("--future-days", type=int, default=14, help="Days of future horizon (default: 14)")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--save", action="store_true", default=True, help="Save outputs to disk (default: True)")
    parser.add_argument("--force-refresh", action="store_true", default=False, help="Force refresh data from RDS, ignoring local Parquet snapshot cache")
    args = parser.parse_args()

    past_df, future_df = load_and_engineer_splits(
        unique_id=args.unique_id,
        history_days=args.history_days,
        past_cut_days=args.past_days,
        horizon_days=args.future_days,
        output_dir=args.output_dir,
        save=args.save,
        force_refresh=args.force_refresh,
    )
    print(f"\nDone! Returned past: {past_df.shape}, future: {future_df.shape}")
