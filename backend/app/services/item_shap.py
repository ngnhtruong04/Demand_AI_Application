"""On-demand SHAP for a single saved run/item, with persistent result caching."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
import logging
from pathlib import Path
import pickle
import threading
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models.core.forecast import CoreForecastItemSummary, CoreForecastDailyPoint
from app.services.forecast_artifacts import run_directory
from app.services.forecast_persistence import GROUP_MAPPING, GROUP_COLORS, get_latest_forecast_from_db

logger = logging.getLogger(__name__)


def cache_path(run_id: str, item_id: str) -> Path:
    return run_directory(run_id) / "shap" / (hashlib.sha256(item_id.encode()).hexdigest() + ".json")


@lru_cache(maxsize=1)
def get_run_horizons(run_id: str):
    """Cache parsed horizon data and item-to-index map for the active run."""
    work = run_directory(run_id)
    horizons = []
    for horizon in range(1, 15):
        pickle_path = work / f"horizon-{horizon}.pickle"
        if not pickle_path.is_file():
            return None
        with pickle_path.open("rb") as stream:
            day_records, pdf, lgb, xgb, cat = pickle.load(stream)
        id_map = {str(row["unique_id"]): i for i, row in enumerate(day_records)}
        horizons.append((day_records, pdf, lgb, xgb, cat, id_map))
    return horizons


@lru_cache(maxsize=4)
def predictor_for_run(run_id: str):
    from app.pipeline.recursive_ensemble import RecursiveEnsemblePredictor, get_global_models, MODELS_DIR
    models = run_directory(run_id) / "models"
    preloaded = get_global_models(MODELS_DIR)
    return RecursiveEnsemblePredictor(
        models_dir=models,
        contract_path=models / "feature_contract.json",
        weights_path=models / "selected_weights.json",
        feature_dict_path=models / "feature_dictionary.json",
        models=preloaded,
    )


def calculate_item_shap(run_id: str, item_id: str) -> dict:
    work = run_directory(run_id)
    predictor = predictor_for_run(run_id)

    cached_horizons = get_run_horizons(run_id)
    day_records_all = []
    pdf_rows = []
    lgb_all = []
    xgb_all = []
    cat_all = []

    if cached_horizons is not None and len(cached_horizons) == 14:
        for day_records, pdf, lgb, xgb, cat, id_map in cached_horizons:
            if item_id not in id_map:
                raise ValueError("Item must have exactly one prediction per day in the saved run.")
            index = id_map[item_id]
            day_records_all.append(day_records[index])
            pdf_rows.append(pdf.iloc[[index]])
            lgb_all.append(lgb[index])
            xgb_all.append(xgb[index])
            cat_all.append(cat[index])
    else:
        for horizon in range(1, 15):
            with (work / f"horizon-{horizon}.pickle").open("rb") as stream:
                day_records, pdf, lgb, xgb, cat = pickle.load(stream)
            matches = [i for i, row in enumerate(day_records) if str(row['unique_id']) == item_id]
            if len(matches) != 1:
                raise ValueError("Item must have exactly one prediction per day in the saved run.")
            index = matches[0]
            day_records_all.append(day_records[index])
            pdf_rows.append(pdf.iloc[[index]])
            lgb_all.append(lgb[index])
            xgb_all.append(xgb[index])
            cat_all.append(cat[index])

    pdf_14 = pd.concat(pdf_rows, ignore_index=True)
    cat_cols = getattr(getattr(predictor, "explainer", None), "cat_cols", [])
    for col in cat_cols:
        if col in pdf_14.columns:
            if isinstance(pdf_rows[0][col].dtype, pd.CategoricalDtype):
                pdf_14[col] = pdf_14[col].astype(pdf_rows[0][col].dtype)
            else:
                pdf_14[col] = pdf_14[col].astype("category")

    lgb_preds = np.asarray(lgb_all, dtype=np.float32)
    xgb_preds = np.asarray(xgb_all, dtype=np.float32)
    cat_preds = np.asarray(cat_all, dtype=np.float32)

    explanations = predictor.explainer.explain(
        day_records_all,
        pdf_14,
        lgb_preds,
        xgb_preds,
        cat_preds,
        mode="online",
        top_k_positive=len(predictor.feature_columns),
        top_k_negative=len(predictor.feature_columns),
    )

    if len(explanations) != 14 or {int(e['horizon']) for e in explanations} != set(range(1, 15)):
        raise ValueError("SHAP did not return all 14 days.")
    summaries, groups = {}, {}
    daily = []
    for explanation in explanations:
        features = []
        for value in explanation['top_positive_features'] + explanation['top_negative_features']:
            contribution = float(value['shap_value'])
            if not np.isfinite(contribution):
                raise ValueError('Model returned a non-finite SHAP value.')
            feature = {'feature': value['feature'], 'label': value['feature_label'], 'group': value['feature_group'],
                       'shap': contribution, 'abs_shap': abs(contribution), 'direction': value['direction']}
            features.append(feature)
            summary = summaries.setdefault(feature['feature'], {**feature, 'shap': 0.0, 'abs_shap': 0.0})
            summary['shap'] += contribution
            summary['abs_shap'] += abs(contribution)
            group = GROUP_MAPPING.get(feature['group'], 'Order Context')
            groups[group] = groups.get(group, 0.0) + abs(contribution)
        daily.append((int(explanation['horizon']), sorted(features, key=lambda f: -f['abs_shap'])))
    for feature in summaries.values():
        feature['direction'] = 'increase' if feature['shap'] >= 0 else 'decrease'
    total = sum(groups.values()) or 1.0
    drivers = [{'id': name.lower().replace(' ', '_').replace('&', 'and'), 'name': name,
                'score': round(value / total * 100, 2), 'color': GROUP_COLORS.get(name, '#94a3b8')}
               for name, value in sorted(groups.items(), key=lambda pair: -pair[1])]
    with SessionLocal() as db:
        condition = (CoreForecastItemSummary.run_id == UUID(run_id), CoreForecastItemSummary.unique_id == item_id)
        result = db.execute(update(CoreForecastItemSummary).where(*condition).values(
            all_features_shap=sorted(summaries.values(), key=lambda f: -f['abs_shap']), drivers_breakdown=drivers))
        if result.rowcount != 1:
            raise ValueError("Forecast item is no longer available.")
        for horizon, features in daily:
            result = db.execute(update(CoreForecastDailyPoint).where(
                CoreForecastDailyPoint.run_id == UUID(run_id), CoreForecastDailyPoint.unique_id == item_id,
                CoreForecastDailyPoint.horizon_day == horizon).values(all_features_shap=features))
            if result.rowcount != 1:
                raise ValueError("Forecast daily point is no longer available.")
        db.commit()
        payload = get_latest_forecast_from_db(db, unique_id=item_id, requested_run_id=UUID(run_id))
        if not payload or not payload.get('items'):
            raise ValueError("Saved SHAP could not be retrieved.")
        item = {**payload['items'][0], 'run_id': run_id, 'shap_status': 'completed'}
    result = {
        'status': 'completed',
        'run_id': run_id,
        'item_id': item_id,
        'item': item,
        'active_item_id': None,
        'queued_item_ids': [],
        'completed_item_ids': [],
    }
    path = cache_path(run_id, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
    temporary.write_text(json.dumps(result), encoding='utf-8')
    temporary.replace(path)
    return result


class ItemShapJobs:
    def __init__(self, calculate=calculate_item_shap):
        self.calculate = calculate
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)
        self.queue: list[tuple[str, str]] = []  # Max 5 pending items (promoted on revisit)
        self.active_item: tuple[str, str] | None = None
        self.jobs: dict[tuple[str, str], dict] = {}
        self.completed_items: set[tuple[str, str]] = set()
        self._stopped = False
        self.worker = threading.Thread(target=self._worker_loop, daemon=True, name="item-shap-worker")
        self.worker.start()
        self.executor = SimpleNamespace(shutdown=self.stop)

    def stop(self, wait: bool = True, **kwargs):
        with self.lock:
            self._stopped = True
            self.cv.notify_all()
        if wait and self.worker.is_alive() and threading.current_thread() != self.worker:
            self.worker.join(timeout=2)

    def status(self, run_id: str, item_id: str) -> dict:
        path = cache_path(run_id, item_id)
        if path.is_file():
            payload = json.loads(path.read_text(encoding='utf-8'))
        else:
            with self.lock:
                payload = deepcopy(self.jobs.get((run_id, item_id), {'status': 'not_requested', 'run_id': run_id, 'item_id': item_id}))
        with self.lock:
            payload['active_item_id'] = self.active_item[1] if self.active_item and self.active_item[0] == run_id else None
            payload['queued_item_ids'] = [item[1] for item in self.queue if item[0] == run_id]
            payload['completed_item_ids'] = [item[1] for item in self.completed_items if item[0] == run_id]
        return payload

    def start(self, run_id: str, item_id: str) -> dict:
        with self.lock:
            # 1. Return immediately if completed on disk
            current = self.status(run_id, item_id)
            if current['status'] == 'completed':
                return current

            key = (run_id, item_id)

            # 2. Return current running state if active
            if self.active_item == key or self.jobs.get(key, {}).get('status') == 'running':
                return self.status(run_id, item_id)

            if not (run_directory(run_id) / 'horizon-14.pickle').is_file():
                raise FileNotFoundError('Saved model inputs are unavailable for this run. Run a new forecast to enable on-demand SHAP.')
            with SessionLocal() as db:
                exists = db.execute(select(CoreForecastItemSummary.unique_id).where(
                    CoreForecastItemSummary.run_id == UUID(run_id), CoreForecastItemSummary.unique_id == item_id)).scalar_one_or_none()
                if exists is None:
                    raise LookupError('Forecast item not found in this run.')

            # 3. Promote to front (index 0) if already in queue, or insert at front
            if key in self.queue:
                self.queue.remove(key)
            self.queue.insert(0, key)
            self.jobs[key] = {'status': 'queued', 'run_id': run_id, 'item_id': item_id}

            # 4. Cap queue at max 5 items: evict oldest from tail
            while len(self.queue) > 5:
                evicted = self.queue.pop()
                self.jobs[evicted] = {'status': 'not_requested', 'run_id': evicted[0], 'item_id': evicted[1]}

            self.cv.notify()
            return self.status(run_id, item_id)

    def _worker_loop(self):
        while True:
            with self.lock:
                while not self.queue and not self._stopped:
                    self.cv.wait()
                if self._stopped:
                    break
                key = self.queue.pop(0)
                self.active_item = key
                self.jobs[key]['status'] = 'running'

            run_id, item_id = key
            try:
                result = self.calculate(run_id, item_id)
                with self.lock:
                    self.jobs[key] = result
                    self.completed_items.add(key)
            except Exception as error:
                logger.exception('SHAP failed for run %s item %s', run_id, item_id)
                message = 'Database operation failed. Please try again.' if isinstance(error, SQLAlchemyError) else str(error)
                with self.lock:
                    self.jobs[key].update(status='failed', error=message)
            finally:
                with self.lock:
                    self.active_item = None


item_shap_jobs = ItemShapJobs()
