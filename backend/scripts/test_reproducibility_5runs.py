"""test_reproducibility_5runs.py — Rigorous 5-run forecast reproducibility & variance test on a fixed data split.

Executes 5 consecutive forecast iterations on the exact same (past, future) feature-engineered split,
tracking determinism, floating-point divergence, per-horizon error accumulation, and model stability.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np
import polars as pl

from app.pipeline.load_pipeline import load_and_engineer_splits
from app.pipeline.recursive_ensemble import RecursiveEnsemblePredictor

BACKEND_DIR = Path(__file__).resolve().parents[1]
CACHE_FILE = BACKEND_DIR / "data" / "cache" / "raw_snapshot_60d_active.parquet"
OUTPUT_REPORT = BACKEND_DIR / "data" / "output" / "reproducibility_5runs_report.json"


def main():
    print("=" * 80)
    print("DEMAND AI FORECAST REPRODUCIBILITY EXPERIMENT: 5 RUNS ON IDENTICAL DATA SPLIT")
    print("=" * 80)

    # 1. Prepare Fixed Data Split
    print("\n[Step 1/3] Loading raw data & constructing fixed feature engineering split...")
    if CACHE_FILE.exists():
        raw_df = pl.read_parquet(CACHE_FILE)
        print(f"Loaded raw cached snapshot: {raw_df.height:,} rows for {raw_df['unique_id'].n_unique():,} SKUs.")
    else:
        from app.pipeline.load_pipeline import fetch_raw_data
        raw_df = fetch_raw_data(days=60, use_inactive_items=False, min_days_no_sale=10)
        print(f"Fetched raw data from DB: {raw_df.height:,} rows.")

    t_split_start = time.time()
    past_split, future_split = load_and_engineer_splits(
        source_data=raw_df,
        use_inactive_items=False,
        save=False,
    )
    t_split = time.time() - t_split_start
    print(f"Feature engineering complete in {t_split:.2f}s:")
    print(f"  • Past lookback split:   {past_split.height:,} rows ({past_split.width} features)")
    print(f"  • Future 14-day horizon: {future_split.height:,} rows ({future_split.width} features)")
    print(f"  • Distinct items:        {future_split['unique_id'].n_unique():,} SKUs across {future_split['warehouse'].n_unique():,} warehouses")

    # 2. Load Predictor
    print("\n[Step 2/3] Loading RecursiveEnsemblePredictor (LightGBM + XGBoost + CatBoost)...")
    t_pred_load = time.time()
    predictor = RecursiveEnsemblePredictor()
    print(f"Predictor initialized in {time.time() - t_pred_load:.2f}s.")
    print(f"  • Ensemble weights: LightGBM={predictor.w_lgb:.2f}, XGBoost={predictor.w_xgb:.2f}, CatBoost={predictor.w_cat:.2f}")

    # 3. Run Forecast 5 Times
    print("\n[Step 3/3] Executing 5 sequential forecast runs on the EXACT same split...")
    runs_results: list[dict] = []
    preds_arrays: list[np.ndarray] = []
    run_dfs: list[pl.DataFrame] = []

    for r in range(1, 6):
        print(f"  --> Executing Run #{r}/5...", end="", flush=True)
        t_start = time.time()
        # Clone frames to guarantee 100% pristine input immutability
        df_pred = predictor.predict(past_split.clone(), future_split.clone())
        elapsed = time.time() - t_start

        # Sort canonically by (unique_id, warehouse, date) to ensure 1-to-1 array alignment
        df_pred_sorted = df_pred.sort(["unique_id", "warehouse", "date"])
        sales_arr = df_pred_sorted["predicted_sales"].to_numpy().astype(np.float64)

        preds_arrays.append(sales_arr)
        run_dfs.append(df_pred_sorted)

        total_sales = float(sales_arr.sum())
        mean_sales = float(sales_arr.mean())
        max_sales = float(sales_arr.max())
        min_sales = float(sales_arr.min())

        runs_results.append({
            "run_index": r,
            "latency_seconds": round(elapsed, 2),
            "row_count": len(sales_arr),
            "total_predicted_units": round(total_sales, 4),
            "mean_predicted_units": round(mean_sales, 4),
            "min_predicted_units": round(min_sales, 4),
            "max_predicted_units": round(max_sales, 4),
        })
        print(f" Done in {elapsed:.2f}s | Total predicted demand: {total_sales:,.2f} units")

    # 4. Statistical Analysis Across the 5 Runs
    print("\n" + "=" * 80)
    print("COMPREHENSIVE STATISTICAL ANALYSIS ACROSS 5 RUNS")
    print("=" * 80)

    # Stack into 2D matrix: shape = (5, 50428)
    all_preds_matrix = np.stack(preds_arrays, axis=0)
    n_points = all_preds_matrix.shape[1]

    # Calculate per-point standard deviation & variance across the 5 runs
    pointwise_std = np.std(all_preds_matrix, axis=0)
    pointwise_max = np.max(all_preds_matrix, axis=0)
    pointwise_min = np.min(all_preds_matrix, axis=0)
    pointwise_range = pointwise_max - pointwise_min

    # Pairwise comparison against Baseline (Run 1)
    pairwise_stats = []
    base_arr = preds_arrays[0]

    for r in range(1, 5):
        comp_arr = preds_arrays[r]
        diff = np.abs(comp_arr - base_arr)
        max_diff = float(np.max(diff))
        mean_diff = float(np.mean(diff))
        median_diff = float(np.median(diff))
        exact_equal_cnt = int(np.sum(diff == 0.0))
        exact_equal_pct = (exact_equal_cnt / n_points) * 100.0
        within_1e6_cnt = int(np.sum(diff < 1e-6))
        within_1e6_pct = (within_1e6_cnt / n_points) * 100.0
        within_1e4_cnt = int(np.sum(diff < 1e-4))
        within_1e4_pct = (within_1e4_cnt / n_points) * 100.0
        within_001_cnt = int(np.sum(diff < 0.01))
        within_001_pct = (within_001_cnt / n_points) * 100.0

        pairwise_stats.append({
            "pair": f"Run #1 vs Run #{r+1}",
            "max_abs_diff": max_diff,
            "mean_abs_diff": mean_diff,
            "median_abs_diff": median_diff,
            "exact_match_pct": round(exact_equal_pct, 4),
            "match_within_1e6_pct": round(within_1e6_pct, 4),
            "match_within_1e4_pct": round(within_1e4_pct, 4),
            "match_within_001_pct": round(within_001_pct, 4),
        })

    # Horizon-by-Horizon Drift Analysis (Does recursive feedback accumulate variance?)
    horizon_analysis = []
    ref_df = run_dfs[0]
    horizons = ref_df["horizon"].to_numpy()

    for h in range(1, 15):
        mask = (horizons == h)
        h_matrix = all_preds_matrix[:, mask]
        h_std = np.std(h_matrix, axis=0)
        h_range = np.max(h_matrix, axis=0) - np.min(h_matrix, axis=0)
        h_mean_sales = np.mean(h_matrix)

        horizon_analysis.append({
            "horizon_day": h,
            "count_predictions": int(np.sum(mask)),
            "mean_sales": round(float(h_mean_sales), 2),
            "max_pointwise_diff": float(np.max(h_range)),
            "mean_pointwise_diff": float(np.mean(h_range)),
            "max_std": float(np.max(h_std)),
            "mean_std": float(np.mean(h_std)),
        })

    # Summary Assessment
    max_overall_diff = float(np.max(pointwise_range))
    mean_overall_diff = float(np.mean(pointwise_range))
    max_overall_std = float(np.max(pointwise_std))
    mean_overall_std = float(np.mean(pointwise_std))
    is_strictly_identical = (max_overall_diff == 0.0)
    is_numerically_deterministic = (max_overall_diff < 1e-4)

    verdict = {
        "is_strictly_identical": is_strictly_identical,
        "is_numerically_deterministic": is_numerically_deterministic,
        "max_overall_diff": max_overall_diff,
        "mean_overall_diff": mean_overall_diff,
        "max_overall_std": max_overall_std,
        "mean_overall_std": mean_overall_std,
    }

    report_payload = {
        "summary": verdict,
        "runs": runs_results,
        "pairwise_vs_run1": pairwise_stats,
        "horizon_analysis": horizon_analysis,
    }

    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print("\n--- KẾT QUẢ TỔNG QUAN 5 LẦN CHẠY ---")
    for r in runs_results:
        print(f"  • Lần {r['run_index']}: Tổng = {r['total_predicted_units']:,.2f} | Trung bình = {r['mean_predicted_units']:.4f} | Max = {r['max_predicted_units']:.2f} | Thời gian = {r['latency_seconds']}s")

    print("\n--- SO SÁNH CẶP ĐỐI CHIẾU VỚI LẦN 1 ---")
    for p in pairwise_stats:
        print(f"  • {p['pair']}:")
        print(f"      - Max Absolute Diff:    {p['max_abs_diff']:.8f}")
        print(f"      - Mean Absolute Diff:   {p['mean_abs_diff']:.8f}")
        print(f"      - Tỷ lệ trùng khớp 100%: {p['exact_match_pct']}%")
        print(f"      - Trùng khớp (< 1e-6):  {p['match_within_1e6_pct']}%")

    print("\n--- ĐỘ LỆCH THEO HORIZON (NGÀY 1 ĐẾN NGÀY 14) ---")
    for h in horizon_analysis:
        print(f"  • Day {h['horizon_day']:02d}: Max Diff = {h['max_pointwise_diff']:.8f} | Mean Diff = {h['mean_pointwise_diff']:.8f} | Mean Std = {h['mean_std']:.8f}")

    print("\n" + "=" * 80)
    print("KẾT LUẬN CUỐI CÙNG (DETERMINISM VERDICT):")
    if is_strictly_identical:
        print("✅ TUYỆT ĐỐI KHÔNG CÓ SỰ KHÁC BIỆT (STRICT DETERMINISM): Cả 5 lần dự báo cho kết quả trùng khớp 100% bit-for-bit!")
    elif is_numerically_deterministic:
        print(f"✅ ĐỒNG NHẤT TUYỆT ĐỐI VỀ MẶT SỐ HỌC (NUMERIC DETERMINISM): Độ lệch tối đa cực vi mô ({max_overall_diff:.2e}), hoàn toàn do thứ tự làm tròn floating-point đa luồng.")
    else:
        print(f"⚠️ CÓ ĐỘ LỆCH SỐ HỌC: Max Diff = {max_overall_diff:.4f}, Mean Diff = {mean_overall_diff:.4f}")
    print("=" * 80)
    print(f"Báo cáo chi tiết đã lưu vào: {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
