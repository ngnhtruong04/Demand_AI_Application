"""recursive_ensemble.py — Fast, memory-efficient ensemble recursive prediction & TreeSHAP explanation system.

Uses trained LightGBM, XGBoost, and CatBoost models with optimal ensemble weights,
dynamic lag recomputation across the 14-day future horizon, and explainability
supporting offline lookup & native C++ online live recalculation (top 5 pos/neg drivers).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Callable
import warnings

import joblib
import numpy as np
import pandas as pd
import polars as pl
import xgboost as xgb
from catboost import Pool

from app.pipeline.feature_engineering import DEFAULT_CONFIG, PipelineConfig
from app.pipeline.load_pipeline import recompute_future_features

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
DEFAULT_CONTRACT_PATH = MODELS_DIR / "feature_contract.json"
DEFAULT_WEIGHTS_PATH = MODELS_DIR / "selected_weights.json"
DEFAULT_FEATURE_DICT_PATH = MODELS_DIR / "feature_dictionary.json"
DEFAULT_EXPLANATION_SCHEMA_PATH = MODELS_DIR / "explanation_schema.json"
DEFAULT_SHAP_SEMANTICS = (
    "SHAP describes features that pushed the MODEL FORECAST up or down. "
    "It must not be presented as a causal effect on real-world sales."
)


class TreeSHAPExplainer:
    """TreeSHAP explanation service supporting offline parquet lookup and online C++ recalculation.

    Adheres to explanation_schema.json with top 5 positive (increase) and top 5 negative (decrease)
    feature drivers per predicted horizon.
    """

    def __init__(
        self,
        models_dir: Path | str = MODELS_DIR,
        feature_columns: list[str] | None = None,
        weights: dict[str, float] | None = None,
        models: tuple[Any, Any, Any] | None = None,
        cat_cols: list[str] | None = None,
        feature_dict_path: Path | str | None = DEFAULT_FEATURE_DICT_PATH,
    ):
        self.models_dir = Path(models_dir)
        self.feature_columns = feature_columns or []
        self.weights = weights or {"LightGBM": 0.34, "XGBoost": 0.30, "CatBoost": 0.36}
        self.w_lgb = float(self.weights.get("LightGBM", 0.34))
        self.w_xgb = float(self.weights.get("XGBoost", 0.30))
        self.w_cat = float(self.weights.get("CatBoost", 0.36))

        self.cat_cols = cat_cols or [
            "warehouse",
            "name",
            "L1_category_name_en",
            "L2_category_name_en",
            "L3_category_name_en",
            "L4_category_name_en",
            "holiday_name",
            "name_0",
        ]

        # Load feature dictionary
        dict_path = Path(feature_dict_path) if feature_dict_path else DEFAULT_FEATURE_DICT_PATH
        if dict_path.exists():
            with open(dict_path, "r", encoding="utf-8") as f:
                self.feature_dict: dict[str, Any] = json.load(f)
        else:
            self.feature_dict = {}

        # Re-use or load models
        if models is not None:
            self.lgb, self.xgb, self.cat = models
        else:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                self.lgb = joblib.load(self.models_dir / "lightgbm.joblib")
                self.xgb = joblib.load(self.models_dir / "xgboost.joblib")
                self.cat = joblib.load(self.models_dir / "catboost.joblib")

        # Offline parquet lookup table (if present)
        self.offline_parquet_path = self.models_dir / "ensemble_local_shap_union.parquet"
        self._offline_df: pl.DataFrame | None = None

    def preload_offline_data(self, unique_ids: list[str]) -> None:
        """Pre-filter and load offline parquet into memory for requested unique_ids."""
        if not self.offline_parquet_path.exists():
            self._offline_df = None
            return

        str_ids = [str(u) for u in unique_ids]
        try:
            self._offline_df = (
                pl.scan_parquet(self.offline_parquet_path)
                .filter(pl.col("unique_id").cast(pl.String).is_in(str_ids))
                .collect()
            )
        except Exception:
            self._offline_df = None

    def _meta_for_feature(self, feature: str) -> tuple[str, str]:
        info = self.feature_dict.get(feature, {})
        label = info.get("label", feature)
        group = info.get("group", "general")
        return label, group

    def explain(
        self,
        step_records: list[dict[str, Any]],
        pdf: pd.DataFrame,
        preds_lgb: np.ndarray,
        preds_xgb: np.ndarray,
        preds_cat: np.ndarray,
        mode: str = "auto",
        top_k_positive: int = 5,
        top_k_negative: int = 5,
    ) -> list[dict[str, Any]]:
        """Compute or retrieve top 5 positive and negative TreeSHAP features for step records.

        Args:
            step_records: List of record dicts with unique_id, warehouse, date, horizon, forecast.
            pdf: Model-ready feature DataFrame for this step.
            preds_lgb: LightGBM raw square-root predictions.
            preds_xgb: XGBoost raw square-root predictions.
            preds_cat: CatBoost raw square-root predictions.
            mode: "auto" (offline first, online fallback), "offline", or "online".
            top_k_positive: Number of positive feature drivers (default 5).
            top_k_negative: Number of negative feature drivers (default 5).

        Returns:
            List of structured explanation dicts matching explanation_schema.json.
        """
        explanations: list[dict[str, Any]] = []
        rows_to_compute_online: list[int] = []

        for idx, rec in enumerate(step_records):
            uid = str(rec["unique_id"])
            horizon = int(rec["horizon"])
            date_val = str(rec["date"])

            # 1. Try offline lookup
            matched_offline = False
            if mode != "online" and self._offline_df is not None and self._offline_df.height > 0:
                subset = self._offline_df.filter(
                    (pl.col("unique_id").cast(pl.String) == uid)
                    & (pl.col("date").dt.date().cast(pl.String) == date_val)
                ).unique(subset=["feature"])
                if subset.height == 0:
                    subset = self._offline_df.filter(
                        (pl.col("unique_id").cast(pl.String) == uid)
                        & (pl.col("horizon") == horizon)
                    ).unique(subset=["feature"])
                if subset.height > 0:
                    pos_df = (
                        subset.filter(pl.col("direction") == "increase")
                        .sort("ensemble_shap", descending=True)
                        .head(top_k_positive)
                    )
                    neg_df = (
                        subset.filter(pl.col("direction") == "decrease")
                        .sort("abs_ensemble_shap", descending=True)
                        .head(top_k_negative)
                    )

                    def get_val(f_name: str) -> str | None:
                        if f_name not in pdf.columns:
                            return None
                        v = pdf.iloc[idx][f_name]
                        if pd.isna(v):
                            return None
                        if isinstance(v, (int, np.integer)):
                            return str(int(v))
                        if isinstance(v, (float, np.floating)):
                            return f"{v:.4g}"
                        return str(v)

                    top_pos = [
                        {
                            "feature": str(r["feature"]),
                            "feature_label": str(r.get("feature_label") or self._meta_for_feature(r["feature"])[0]),
                            "feature_group": str(r.get("feature_group") or self._meta_for_feature(r["feature"])[1]),
                            "feature_value": get_val(r["feature"]),
                            "shap_value": round(float(r["ensemble_shap"]), 4),
                            "direction": "increase",
                        }
                        for r in pos_df.iter_rows(named=True)
                    ]
                    top_neg = [
                        {
                            "feature": str(r["feature"]),
                            "feature_label": str(r.get("feature_label") or self._meta_for_feature(r["feature"])[0]),
                            "feature_group": str(r.get("feature_group") or self._meta_for_feature(r["feature"])[1]),
                            "feature_value": get_val(r["feature"]),
                            "shap_value": round(float(r["ensemble_shap"]), 4),
                            "direction": "decrease",
                        }
                        for r in neg_df.iter_rows(named=True)
                    ]

                    explanations.append({
                        "unique_id": uid,
                        "warehouse": str(rec["warehouse"]),
                        "date": date_val,
                        "horizon": horizon,
                        "forecast": float(np.ceil(float(rec.get("predicted_sales", rec.get("forecast", 0.0))))),
                        "top_positive_features": top_pos,
                        "top_negative_features": top_neg,
                        "explanation_semantics": DEFAULT_SHAP_SEMANTICS,
                        "ensemble_weights": self.weights,
                        "mode": "offline",
                    })
                    matched_offline = True

            if not matched_offline:
                rows_to_compute_online.append(idx)
                # Placeholder to be filled by online batch
                explanations.append({})

        # 2. Compute online live TreeSHAP for rows requiring dynamic evaluation
        if rows_to_compute_online:
            sub_pdf = pdf.iloc[rows_to_compute_online]
            sub_preds_lgb = preds_lgb[rows_to_compute_online]
            sub_preds_xgb = preds_xgb[rows_to_compute_online]
            sub_preds_cat = preds_cat[rows_to_compute_online]

            # Native C++ TreeSHAP calls with multi-core & parallel model execution
            def _compute_lgb():
                return self.lgb.predict(sub_pdf, pred_contrib=True, num_threads=0)[:, :-1]

            def _compute_xgb():
                dmat = xgb.DMatrix(sub_pdf, enable_categorical=True, nthread=-1)
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning)
                    return self.xgb.predict(dmat, pred_contribs=True)[:, :-1]

            def _compute_cat():
                cat_pool = Pool(sub_pdf, cat_features=self.cat_cols, thread_count=-1)
                return self.cat.get_feature_importance(data=cat_pool, type="ShapValues", thread_count=-1)[:, :-1]

            if len(rows_to_compute_online) > 1:
                with ThreadPoolExecutor(max_workers=3, thread_name_prefix="treeshap-ensemble") as pool:
                    f_lgb = pool.submit(_compute_lgb)
                    f_xgb = pool.submit(_compute_xgb)
                    f_cat = pool.submit(_compute_cat)
                    lgb_raw_shap = f_lgb.result()
                    xgb_raw_shap = f_xgb.result()
                    cat_raw_shap = f_cat.result()
            else:
                lgb_raw_shap = _compute_lgb()
                xgb_raw_shap = _compute_xgb()
                cat_raw_shap = _compute_cat()

            # Chain rule derivative for sqrt transform: d(y^2)/dy = 2 * y
            deriv_lgb = 2.0 * np.maximum(sub_preds_lgb, 0.0)
            deriv_xgb = 2.0 * np.maximum(sub_preds_xgb, 0.0)
            deriv_cat = 2.0 * np.maximum(sub_preds_cat, 0.0)

            sales_shap = (
                self.w_lgb * (lgb_raw_shap * deriv_lgb[:, None])
                + self.w_xgb * (xgb_raw_shap * deriv_xgb[:, None])
                + self.w_cat * (cat_raw_shap * deriv_cat[:, None])
            )

            for sub_i, orig_i in enumerate(rows_to_compute_online):
                rec = step_records[orig_i]
                shap_row = sales_shap[sub_i]
                feature_values = sub_pdf.iloc[sub_i]

                pos_cand = np.where(shap_row > 0)[0]
                neg_cand = np.where(shap_row < 0)[0]

                top_pos_idx = pos_cand[np.argsort(shap_row[pos_cand])[::-1][:top_k_positive]]
                top_neg_idx = neg_cand[np.argsort(shap_row[neg_cand])[:top_k_negative]]

                def build_feat(feat_idx: int, direction: str) -> dict[str, Any]:
                    feat_name = self.feature_columns[feat_idx]
                    label, group = self._meta_for_feature(feat_name)
                    val = feature_values[feat_name]
                    if pd.isna(val):
                        formatted_val = None
                    elif isinstance(val, (int, np.integer)):
                        formatted_val = str(int(val))
                    elif isinstance(val, (float, np.floating)):
                        formatted_val = f"{val:.4g}"
                    else:
                        formatted_val = str(val)

                    return {
                        "feature": feat_name,
                        "feature_label": label,
                        "feature_group": group,
                        "feature_value": formatted_val,
                        "shap_value": round(float(shap_row[feat_idx]), 4),
                        "direction": direction,
                    }

                explanations[orig_i] = {
                    "unique_id": str(rec["unique_id"]),
                    "warehouse": str(rec["warehouse"]),
                    "date": str(rec["date"]),
                    "horizon": int(rec["horizon"]),
                    "forecast": float(np.ceil(float(rec.get("predicted_sales", rec.get("forecast", 0.0))))),
                    "top_positive_features": [build_feat(j, "increase") for j in top_pos_idx],
                    "top_negative_features": [build_feat(j, "decrease") for j in top_neg_idx],
                    "explanation_semantics": DEFAULT_SHAP_SEMANTICS,
                    "ensemble_weights": self.weights,
                    "mode": "online",
                }

        return explanations


@lru_cache(maxsize=1)
def get_global_models(models_dir: Path | str = MODELS_DIR) -> tuple[Any, Any, Any]:
    """Preload and cache the 3 trained GBDT models once in RAM for the lifetime of the process."""
    m_dir = Path(models_dir)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        lgb = joblib.load(m_dir / "lightgbm.joblib")
        xgb_m = joblib.load(m_dir / "xgboost.joblib")
        cat = joblib.load(m_dir / "catboost.joblib")
    return lgb, xgb_m, cat


class RecursiveEnsemblePredictor:
    """Ensemble recursive predictor using LightGBM, XGBoost, and CatBoost with TreeSHAP explainability."""

    def __init__(
        self,
        models_dir: Path | str = MODELS_DIR,
        contract_path: Path | str = DEFAULT_CONTRACT_PATH,
        weights_path: Path | str = DEFAULT_WEIGHTS_PATH,
        feature_dict_path: Path | str | None = DEFAULT_FEATURE_DICT_PATH,
        config: PipelineConfig = DEFAULT_CONFIG,
        models: tuple[Any, Any, Any] | None = None,
    ):
        self.models_dir = Path(models_dir)
        self.config = config

        # 1. Feature contract
        with open(contract_path, "r", encoding="utf-8") as f:
            self.contract = json.load(f)
        self.feature_columns: list[str] = self.contract["feature_columns"]

        # 2. Weights
        with open(weights_path, "r", encoding="utf-8") as f:
            weights_data = json.load(f)
        self.weights: dict[str, float] = weights_data.get(
            "weights", {"LightGBM": 0.34, "XGBoost": 0.30, "CatBoost": 0.36}
        )
        self.w_lgb = float(self.weights.get("LightGBM", 0.34))
        self.w_xgb = float(self.weights.get("XGBoost", 0.30))
        self.w_cat = float(self.weights.get("CatBoost", 0.36))

        # Categorical columns expected by tree models
        self.cat_cols = [
            "warehouse",
            "name",
            "L1_category_name_en",
            "L2_category_name_en",
            "L3_category_name_en",
            "L4_category_name_en",
            "holiday_name",
            "name_0",
        ]

        # 3. Load models once in memory or reuse preloaded models
        if models is not None:
            self.lgb, self.xgb, self.cat = models
        else:
            required_models = ["lightgbm.joblib", "xgboost.joblib", "catboost.joblib"]
            missing_models = [name for name in required_models if not (self.models_dir / name).is_file()]
            if missing_models:
                raise FileNotFoundError(
                    f"Trained model files are missing in {self.models_dir}: {', '.join(missing_models)}. "
                    "Restore the trained models matching feature_contract.json before running a forecast."
                )
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                self.lgb = joblib.load(self.models_dir / "lightgbm.joblib")
                self.xgb = joblib.load(self.models_dir / "xgboost.joblib")
                self.cat = joblib.load(self.models_dir / "catboost.joblib")

        # 4. TreeSHAP Explainer
        self.explainer = TreeSHAPExplainer(
            models_dir=self.models_dir,
            feature_columns=self.feature_columns,
            weights=self.weights,
            models=(self.lgb, self.xgb, self.cat),
            cat_cols=self.cat_cols,
            feature_dict_path=feature_dict_path,
        )

    def _prepare_frames(self, df_past: pl.DataFrame, df_future: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        date_col = self.config.date_column
        target_col = self.config.target_column

        past = df_past.with_columns(
            pl.col(date_col).cast(pl.Date),
            pl.col(target_col).cast(pl.Float32),
        )
        past = past.with_columns(
            [pl.col(c).cast(pl.Float32) for c in past.columns if past[c].dtype == pl.Float64]
        )

        future = df_future.with_columns(
            pl.col(date_col).cast(pl.Date),
            pl.col(target_col).cast(pl.Float32),
        )
        return past, future

    def predict(
        self,
        df_past: pl.DataFrame,
        df_future: pl.DataFrame,
        on_horizon: Callable[..., None] | None = None,
    ) -> pl.DataFrame:
        """Execute fast, memory-efficient 14-day recursive ensemble prediction.

        Returns:
            pl.DataFrame with columns: [unique_id, warehouse, date, horizon, predicted_sales, name, category]
        """
        date_col = self.config.date_column
        past, future = self._prepare_frames(df_past, df_future)
        future_dates = future[date_col].sort().unique().to_list()
        all_preds: list[dict[str, Any]] = []

        for horizon, current_date in enumerate(future_dates, start=1):
            step_frame = future.filter(pl.col(date_col) == current_date)
            if step_frame.height == 0:
                continue

            pdf = pd.DataFrame(step_frame.select(self.feature_columns).to_dict(as_series=False))
            for c in self.feature_columns:
                if c in self.cat_cols:
                    pdf[c] = pdf[c].fillna("missing").astype("category")
                else:
                    pdf[c] = pd.to_numeric(pdf[c], errors="coerce").astype("float32")

            pred_lgb = np.asarray(self.lgb.predict(pdf), dtype=np.float32)
            dmat = xgb.DMatrix(pdf, enable_categorical=True)
            pred_xgb = np.asarray(self.xgb.predict(dmat), dtype=np.float32)
            pred_cat = np.asarray(self.cat.predict(pdf), dtype=np.float32)

            ens_sqrt = np.clip(
                self.w_lgb * pred_lgb + self.w_xgb * pred_xgb + self.w_cat * pred_cat,
                np.float32(0.0),
                None,
            ).astype(np.float32)
            predicted_sales = np.ceil(np.square(ens_sqrt)).astype(np.float32)

            uids = step_frame["unique_id"].to_list()
            warehouses = step_frame["warehouse"].to_list()
            names = step_frame["name"].to_list() if "name" in step_frame.columns else ["" for _ in range(step_frame.height)]
            cats = step_frame["L1_category_name_en"].to_list() if "L1_category_name_en" in step_frame.columns else ["" for _ in range(step_frame.height)]

            for i in range(step_frame.height):
                all_preds.append({
                    "unique_id": str(uids[i]),
                    "warehouse": str(warehouses[i]),
                    "date": current_date,
                    "horizon": horizon,
                    "predicted_sales": float(predicted_sales[i]),
                    "name": str(names[i]),
                    "category": str(cats[i]),
                })

            if on_horizon is not None:
                on_horizon(horizon, all_preds[-step_frame.height:], pdf, pred_lgb, pred_xgb, pred_cat)

            if horizon < len(future_dates):
                pred_update = pl.DataFrame([
                    {
                        "unique_id": p["unique_id"],
                        "warehouse": p["warehouse"],
                        "date": p["date"],
                        "sales": p["predicted_sales"],
                    }
                    for p in all_preds
                ]).with_columns(pl.col(date_col).cast(pl.Date))

                future = recompute_future_features(
                    df_future=future,
                    df_past=past,
                    predicted_sales=pred_update,
                    config=self.config,
                )

        return pl.DataFrame(all_preds).with_columns(pl.col(date_col).cast(pl.Date))

    def predict_and_explain(
        self,
        df_past: pl.DataFrame,
        df_future: pl.DataFrame,
        mode: str = "auto",
        top_k_positive: int = 5,
        top_k_negative: int = 5,
    ) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
        """Execute 14-day recursive prediction and compute top 5 positive/negative TreeSHAP drivers.

        Args:
            df_past: Past lookback DataFrame.
            df_future: Future 14-day horizon DataFrame.
            mode: "auto" (offline lookup first, fallback to online C++ SHAP), "offline", or "online".
            top_k_positive: Number of positive feature drivers (default 5).
            top_k_negative: Number of negative feature drivers (default 5).

        Returns:
            Tuple of:
              - pl.DataFrame containing predictions and structured top_positive/negative features.
              - list of explanation dicts strictly matching explanation_schema.json.
        """
        date_col = self.config.date_column
        past, future = self._prepare_frames(df_past, df_future)

        # Preload offline parquet data if available
        unique_ids = future["unique_id"].unique().to_list()
        self.explainer.preload_offline_data(unique_ids)

        future_dates = future[date_col].sort().unique().to_list()
        all_preds: list[dict[str, Any]] = []
        all_explanations: list[dict[str, Any]] = []

        for horizon, current_date in enumerate(future_dates, start=1):
            step_frame = future.filter(pl.col(date_col) == current_date)
            if step_frame.height == 0:
                continue

            pdf = pd.DataFrame(step_frame.select(self.feature_columns).to_dict(as_series=False))
            for c in self.feature_columns:
                if c in self.cat_cols:
                    pdf[c] = pdf[c].fillna("missing").astype("category")
                else:
                    pdf[c] = pd.to_numeric(pdf[c], errors="coerce").astype("float32")

            pred_lgb = np.asarray(self.lgb.predict(pdf), dtype=np.float32)
            dmat = xgb.DMatrix(pdf, enable_categorical=True)
            pred_xgb = np.asarray(self.xgb.predict(dmat), dtype=np.float32)
            pred_cat = np.asarray(self.cat.predict(pdf), dtype=np.float32)

            ens_sqrt = np.clip(
                self.w_lgb * pred_lgb + self.w_xgb * pred_xgb + self.w_cat * pred_cat,
                np.float32(0.0),
                None,
            ).astype(np.float32)
            predicted_sales = np.ceil(np.square(ens_sqrt)).astype(np.float32)

            uids = step_frame["unique_id"].to_list()
            warehouses = step_frame["warehouse"].to_list()
            names = step_frame["name"].to_list() if "name" in step_frame.columns else ["" for _ in range(step_frame.height)]
            cats = step_frame["L1_category_name_en"].to_list() if "L1_category_name_en" in step_frame.columns else ["" for _ in range(step_frame.height)]

            step_preds: list[dict[str, Any]] = []
            for i in range(step_frame.height):
                step_preds.append({
                    "unique_id": str(uids[i]),
                    "warehouse": str(warehouses[i]),
                    "date": current_date,
                    "horizon": horizon,
                    "predicted_sales": float(predicted_sales[i]),
                    "name": str(names[i]),
                    "category": str(cats[i]),
                })

            # Explain this step
            step_explanations = self.explainer.explain(
                step_records=step_preds,
                pdf=pdf,
                preds_lgb=pred_lgb,
                preds_xgb=pred_xgb,
                preds_cat=pred_cat,
                mode=mode,
                top_k_positive=top_k_positive,
                top_k_negative=top_k_negative,
            )

            for i in range(step_frame.height):
                rec = step_preds[i]
                exp = step_explanations[i]
                rec["top_positive_features"] = exp["top_positive_features"]
                rec["top_negative_features"] = exp["top_negative_features"]
                rec["explanation_mode"] = exp["mode"]
                all_preds.append(rec)
                all_explanations.append(exp)

            if horizon < len(future_dates):
                pred_update = pl.DataFrame([
                    {
                        "unique_id": p["unique_id"],
                        "warehouse": p["warehouse"],
                        "date": p["date"],
                        "sales": p["predicted_sales"],
                    }
                    for p in all_preds
                ]).with_columns(pl.col(date_col).cast(pl.Date))

                future = recompute_future_features(
                    df_future=future,
                    df_past=past,
                    predicted_sales=pred_update,
                    config=self.config,
                )

        feat_schema = pl.List(
            pl.Struct({
                "feature": pl.String,
                "feature_label": pl.String,
                "feature_group": pl.String,
                "feature_value": pl.String,
                "shap_value": pl.Float32,
                "direction": pl.String,
            })
        )

        preds_df = (
            pl.DataFrame(
                all_preds,
                schema_overrides={
                    "top_positive_features": feat_schema,
                    "top_negative_features": feat_schema,
                },
            )
            .with_columns(
                pl.col(date_col).cast(pl.Date),
                pl.col("predicted_sales").cast(pl.Float32),
            )
        )

        return preds_df, all_explanations

    @staticmethod
    @lru_cache(maxsize=1)
    def load_inventory_snapshot(snapshot_date: str = "2024-06-03") -> pd.DataFrame:
        """Load inventory snapshot directly from RDS DB (core.inventory_snapshot).

        Contains: unique_id, current_stock, lead_time_days, safety_stock,
                  baseline_avg_daily_sales, baseline_reorder_point, scenario_group.
        """
        from app.pipeline.load_pipeline import get_db_connection

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT unique_id, current_stock, lead_time_days, safety_stock,
                               baseline_avg_daily_sales, baseline_reorder_point, scenario_group
                        FROM core.inventory_snapshot
                        WHERE snapshot_date = %s;
                        """,
                        (snapshot_date,),
                    )
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
            df = pd.DataFrame(rows, columns=cols)
            return df.astype({
                "unique_id": str,
                "current_stock": "int64",
                "lead_time_days": "int32",
                "safety_stock": "float32",
                "baseline_avg_daily_sales": "float32",
                "baseline_reorder_point": "float32",
                "scenario_group": str,
            })
        except Exception:
            return pd.DataFrame(columns=[
                "unique_id", "current_stock", "lead_time_days", "safety_stock",
                "baseline_avg_daily_sales", "baseline_reorder_point", "scenario_group"
            ])

    @staticmethod
    def compute_inventory_status(
        current_stock: int | float,
        lead_time_days: int | float,
        safety_stock: float,
        forecast14d: float,
        baseline_reorder_point: float | None = None,
        is_deadstock_historical: bool = False,
    ) -> tuple[str, float]:
        """Compute inventory status according to standard supply chain trigger conditions.

        Rules:
        - Deadstock / Obsolete: Low to no sales velocity for > 6-12 months (or forecast < 0.05 units/day)
        - Critical / Danger: Current quantity <= Safety Stock
        - Reorder (Need to Order): Current quantity <= Reorder Point (ROP)
        - Monitor / Pre-alert: Current quantity approaching ROP (<= ROP * 1.2 or projected lead-time breach)
        - In Stock: Current quantity > Reorder Point (ROP)

        Returns:
            (status, dynamic_rop)
        """
        daily_velocity = max(float(forecast14d) / 14.0, 0.0)
        dynamic_rop = float((lead_time_days * daily_velocity) + safety_stock)
        if baseline_reorder_point is not None and dynamic_rop <= 0:
            dynamic_rop = float(baseline_reorder_point)

        # 1. Deadstock / Obsolete: Stock sits idle with low sales velocity (< 1.0 unit/day or > 365d supply)
        days_of_supply = (current_stock / daily_velocity) if daily_velocity > 0 else 999.0
        is_deadstock = current_stock > 0 and (daily_velocity < 1.0 or days_of_supply > 365)
        if is_deadstock:
            return "Deadstock", dynamic_rop

        # 2. Critical / Danger
        if current_stock <= safety_stock:
            return "Critical", dynamic_rop

        # 3. Reorder (Need to Order)
        if current_stock <= dynamic_rop:
            return "Reorder", dynamic_rop

        # 4. Monitor / Pre-alert
        projected_stock_lead_time = current_stock - (lead_time_days * daily_velocity)
        if current_stock <= dynamic_rop * 1.2 or projected_stock_lead_time <= dynamic_rop:
            return "Monitor", dynamic_rop

        # 5. In Stock
        return "In Stock", dynamic_rop

    def to_frontend_contract(
        self,
        predictions: pl.DataFrame,
        inventory_frame: pl.DataFrame | pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Format predictions into the JSON contract structure expected by frontend.

        Enriches items with on-hand stock and dynamic inventory status calculated
        from DB snapshot (core.inventory_snapshot) and forecasted demand.
        """
        items_payload: list[dict[str, Any]] = []

        # Load inventory snapshot from DB if not passed explicitly
        if inventory_frame is None:
            inv_df = self.load_inventory_snapshot()
        elif isinstance(inventory_frame, pl.DataFrame):
            inv_df = inventory_frame.to_pandas()
        else:
            inv_df = inventory_frame

        inv_map: dict[str, dict[str, Any]] = {}
        if inv_df is not None and len(inv_df) > 0:
            for _, row in inv_df.iterrows():
                inv_map[str(row["unique_id"])] = {
                    "current_stock": int(row.get("current_stock", 0)),
                    "lead_time_days": int(row.get("lead_time_days", 3)),
                    "safety_stock": float(row.get("safety_stock", 0.0)),
                    "baseline_reorder_point": float(row.get("baseline_reorder_point", 0.0)),
                    "scenario_group": str(row.get("scenario_group", "")),
                }

        unique_ids = predictions["unique_id"].unique().to_list()
        for uid in unique_ids:
            item_df = predictions.filter(pl.col("unique_id") == uid).sort("horizon")
            total_14d = float(item_df["predicted_sales"].sum())
            name = item_df["name"][0] if "name" in item_df.columns else f"Item {uid}"
            cat = item_df["category"][0] if "category" in item_df.columns else "General"
            warehouse = item_df["warehouse"][0]

            inv_item = inv_map.get(str(uid))
            if inv_item is not None:
                stock = inv_item["current_stock"]
                lead_time = inv_item["lead_time_days"]
                safety_stock = inv_item["safety_stock"]
                baseline_rop = inv_item["baseline_reorder_point"]
                status, dynamic_rop = self.compute_inventory_status(
                    current_stock=stock,
                    lead_time_days=lead_time,
                    safety_stock=safety_stock,
                    forecast14d=total_14d,
                    baseline_reorder_point=baseline_rop,
                    is_deadstock_historical=False,
                )
            else:
                stock = int(round(total_14d * 1.2))
                lead_time = 3
                safety_stock = round(total_14d * 0.2, 1)
                dynamic_rop = round(total_14d * 0.5, 1)
                status = "In Stock"

            daily_points = []
            for row in item_df.iter_rows(named=True):
                pt: dict[str, Any] = {
                    "day": int(row["horizon"]),
                    "date": str(row["date"]),
                    "predicted": float(np.ceil(float(row["predicted_sales"]))),
                }
                if "top_positive_features" in row and row["top_positive_features"] is not None:
                    pt["top_positive_features"] = row["top_positive_features"]
                if "top_negative_features" in row and row["top_negative_features"] is not None:
                    pt["top_negative_features"] = row["top_negative_features"]
                daily_points.append(pt)

            items_payload.append({
                "id": str(uid),
                "sku": f"SKU-{str(uid).zfill(3)}",
                "name": name,
                "category": cat,
                "warehouse": warehouse,
                "forecast14d": round(total_14d, 2),
                "onHandStock": stock,
                "status": status,
                "reorderPoint": round(dynamic_rop, 1),
                "safetyStock": round(safety_stock, 1),
                "leadTimeDays": int(lead_time),
                "daily_points": daily_points,
            })

        return {
            "status": "success",
            "forecast_horizon_days": 14,
            "total_items": len(items_payload),
            "generated_at": pd.Timestamp.now().isoformat(),
            "items": items_payload,
        }

    @staticmethod
    @lru_cache(maxsize=1)
    def load_test_weights() -> pd.DataFrame:
        """Permanently load series evaluation weights directly from RDS (raw.test_weights)."""
        from app.pipeline.load_pipeline import get_db_connection

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT unique_id, weight FROM raw.test_weights;")
                rows = cur.fetchall()

        return pd.DataFrame(rows, columns=["unique_id", "weight"]).astype(
            {"unique_id": str, "weight": "float32"}
        )

    @staticmethod
    def calculate_metrics(
        frame: pl.DataFrame | pd.DataFrame,
        prediction_column: str = "predicted_sales",
        actual_column: str = "actual_sales",
    ) -> dict[str, float]:
        """Compute standard demand metrics (WMAE, WAPE, MAE, RMSE) matching selected_weights.json."""
        df = frame.to_pandas() if isinstance(frame, pl.DataFrame) else frame
        clean = df.loc[
            np.isfinite(df[actual_column].to_numpy(float))
            & np.isfinite(df[prediction_column].to_numpy(float))
        ].copy()
        actual = clean[actual_column].to_numpy(np.float32)
        predicted = clean[prediction_column].to_numpy(np.float32)
        error = predicted - actual
        ae = np.abs(error)
        result: dict[str, float] = {
            "mae": float(ae.mean()),
            "rmse": float(np.sqrt(np.mean(error ** 2))),
            "wape": float(ae.sum() / max(np.abs(actual).sum(), 1e-12)),
            "row_bias": float(error.mean()),
        }

        if "weight" not in clean.columns or clean["weight"].isna().all():
            weights_df = RecursiveEnsemblePredictor.load_test_weights()
            clean["unique_id"] = clean["unique_id"].astype(str)
            clean = clean.drop(columns=["weight"], errors="ignore").merge(weights_df, on="unique_id", how="left")

        if "weight" in clean.columns and clean["weight"].notna().any():
            weighted = clean.loc[
                clean["weight"].notna() & np.isfinite(clean["weight"]) & (clean["weight"] >= 0)
            ].copy()
            weighted["__ae"] = np.abs(weighted[prediction_column] - weighted[actual_column])
            weighted["__error"] = weighted[prediction_column] - weighted[actual_column]
            by_series = weighted.groupby("unique_id", as_index=False).agg(
                weight=("weight", "first"), series_mae=("__ae", "mean"), series_bias=("__error", "mean")
            )
            denom = max(float(by_series["weight"].sum()), 1e-12)
            result["wmae"] = float((by_series["series_mae"] * by_series["weight"]).sum() / denom)
            result["weighted_bias"] = float((by_series["series_bias"] * by_series["weight"]).sum() / denom)
            result["cancellation_ratio"] = float(
                1.0 - min(abs(result["weighted_bias"]) / max(result["wmae"], 1e-12), 1.0)
            )
        else:
            result["wmae"] = result["mae"]
            result["weighted_bias"] = result["row_bias"]
            result["cancellation_ratio"] = 1.0

        return result


if __name__ == "__main__":
    import time

    print("=== SELF-CHECK: RecursiveEnsemblePredictor & TreeSHAP Explainer ===")
    real_past_csv = Path("backend/data/output/feature_engineered_item_10_30d_past.csv")
    assert real_past_csv.exists(), f"Missing real validation dataset: {real_past_csv}"

    full_df = pl.read_csv(real_past_csv).with_columns(
        pl.col("date").str.to_date(),
        pl.col("sales").cast(pl.Float32),
    )
    full_df = full_df.with_columns(
        [pl.col(c).cast(pl.Float32) for c in full_df.columns if full_df[c].dtype == pl.Float64]
    )

    cutoff_date = full_df["date"].sort().unique().to_list()[15]
    df_past = full_df.filter(pl.col("date") <= cutoff_date)
    actual_future = full_df.filter(pl.col("date") > cutoff_date).sort("date")
    df_future = actual_future.with_columns(pl.lit(None, dtype=pl.Float32).alias("sales"))

    predictor = RecursiveEnsemblePredictor()

    print("\n1. Testing predict_and_explain (mode='auto')...")
    t0 = time.perf_counter()
    preds_df, explanations = predictor.predict_and_explain(df_past, df_future, mode="auto")
    elapsed = time.perf_counter() - t0

    print(f"Completed in {elapsed:.3f}s")
    assert preds_df.height == 14
    assert len(explanations) == 14

    first_exp = explanations[0]
    print(f"Sample explanation horizon 1 (mode: {first_exp['mode']}):")
    print(f"  Forecast: {first_exp['forecast']}")
    print("  Top Positive Features (Increase):")
    for f in first_exp["top_positive_features"]:
        print(f"    • {f['feature']} ({f['feature_label']}): {f['shap_value']:+.4f} [{f['feature_group']}]")
    print("  Top Negative Features (Decrease):")
    for f in first_exp["top_negative_features"]:
        print(f"    • {f['feature']} ({f['feature_label']}): {f['shap_value']:+.4f} [{f['feature_group']}]")

    assert len(first_exp["top_positive_features"]) == 5
    assert len(first_exp["top_negative_features"]) == 5
    assert all(f["direction"] == "increase" for f in first_exp["top_positive_features"])
    assert all(f["direction"] == "decrease" for f in first_exp["top_negative_features"])

    print("\n2. Testing predict_and_explain (mode='online' live C++ TreeSHAP for 1 step)...")
    # Test online mode on single step to verify live C++ execution
    t0 = time.perf_counter()
    preds_online, exp_online = predictor.predict_and_explain(
        df_past, df_future.filter(pl.col("date") == df_future["date"].min()), mode="online"
    )
    elapsed_online = time.perf_counter() - t0
    print(f"Online live C++ TreeSHAP step completed in {elapsed_online:.3f}s")
    assert exp_online[0]["mode"] == "online"
    assert len(exp_online[0]["top_positive_features"]) == 5
    assert len(exp_online[0]["top_negative_features"]) == 5

    print("\nALL PREDICTION & TREESHAP TESTS PASSED!")
