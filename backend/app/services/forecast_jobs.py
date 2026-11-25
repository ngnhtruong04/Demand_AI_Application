"""Real forecast orchestration for a single API worker.

Jobs outlive SSE connections, but not an API process restart. Completed predictions
are durable in PostgreSQL. Only one live job runs at a time to bound model memory.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
import threading
from typing import Any, Callable
from uuid import uuid4
import os
from app.services.forecast_artifacts import ARTIFACT_ROOT, snapshot_models, run_directory, prune_artifacts, prune_old_sessions
from uuid import UUID
import polars as pl


logger = logging.getLogger(__name__)
STEP_NAMES = ["Fetch Data", "Feature Engineering", "Recursive Ensemble Forecast", "Inventory Analysis & Save"]


def run_live_pipeline(emit: Callable[[int, str, str], None], session_key: str | None = None) -> str:
    from app.db.session import SessionLocal
    from app.pipeline.load_pipeline import fetch_raw_data, load_and_engineer_splits
    from app.pipeline.recursive_ensemble import MODELS_DIR, RecursiveEnsemblePredictor, get_global_models
    from app.services.forecast_persistence import save_forecast_run

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    run_uuid = uuid4()
    if session_key:
        try:
            run_uuid = UUID(str(session_key).strip())
        except ValueError:
            pass
    with TemporaryDirectory(prefix=".building-", dir=ARTIFACT_ROOT) as temp:
        work = Path(temp)
        prewarm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-prewarm")
        try:
            def _prewarm_models():
                models_dest = work / "models"
                snapshot_models(MODELS_DIR, models_dest)
                return RecursiveEnsemblePredictor(
                    models_dir=models_dest, contract_path=models_dest / "feature_contract.json",
                    weights_path=models_dest / "selected_weights.json", feature_dict_path=models_dest / "feature_dictionary.json",
                    models=get_global_models(MODELS_DIR),
                )

            prewarm_future = prewarm_executor.submit(_prewarm_models)

            emit(1, "running", "Connecting to database & checking sales history...")
            raw = fetch_raw_data(days=60, use_inactive_items=False, min_days_no_sale=10)
            if raw.is_empty():
                raise ValueError("No sales history was returned.")
            emit(1, "completed", f"Loaded {raw.height:,} history rows for {raw['unique_id'].n_unique():,} items.")

            def _on_feature_engineering_progress(step: str, status: str, detail: Any) -> None:
                if status != "running":
                    return
                msg = str(detail) if isinstance(detail, str) else f"{step}: {detail}"
                emit(2, "running", msg[:1000])

            emit(2, "running", "Generating future inputs and engineering time-series features...")
            past, future = load_and_engineer_splits(
                source_data=raw, use_inactive_items=False, min_days_no_sale=30, save=False,
                emit=_on_feature_engineering_progress,
            )
            del raw
            if future.is_empty() or future['date'].n_unique() != 14:
                raise ValueError("Feature engineering did not produce a 14-day horizon.")
            emit(2, "completed", f"Engineered {future.height:,} future rows.")

            emit(3, "running", "Loading trained ensemble models...")
            predictor = prewarm_future.result()

            pickle_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pickle-writer")
            pickle_futures = []

            def _write_pickle(horizon, data):
                with (work / f"horizon-{horizon}.pickle").open("wb") as stream:
                    pickle.dump(data, stream)

            def capture(horizon, records, pdf, lgb, xgb, cat):
                fut = pickle_executor.submit(_write_pickle, horizon, (records, pdf, lgb, xgb, cat))
                pickle_futures.append(fut)
                emit(3, "running", f"Predicted day {horizon}/14 for {len(records):,} items.")

            predictions = predictor.predict(past, future, on_horizon=capture)
            for fut in pickle_futures:
                fut.result()
            pickle_executor.shutdown(wait=True)

            if predictions.height != future.height or predictions['horizon'].n_unique() != 14:
                raise ValueError("The model returned an incomplete forecast.")
            if predictions.filter(pl.col('predicted_sales').is_null() | ~pl.col('predicted_sales').is_finite() | (pl.col('predicted_sales') < 0)).height:
                raise ValueError("The model returned invalid forecast values.")
            preds_path = work / "predictions.parquet"
            predictions.write_parquet(preds_path)
            emit(3, "completed", f"Generated {predictions.height:,} predictions over 14 days.")
            del past, future, predictions

            emit(4, "running", "Calculating inventory statuses and safety stock...")
            # Publish immutable inputs before committing the run; failed saves leave
            # an orphan directory that the next successful run's retention removes.
            destination = run_directory(str(run_uuid))
            os.replace(work, destination)
            emit(4, "running", "Saving forecast results to PostgreSQL database...")
            with SessionLocal() as db:
                save_kwargs = {"session_key": session_key} if session_key else {}
                run = save_forecast_run(
                    db, preds_path=destination / "predictions.parquet", strict=True,
                    include_shap=False, run_id=run_uuid,
                    model_version="recursive-ensemble-ondemand-v1.0",
                    **save_kwargs,
                )
                run_id = str(run.run_id)
                from sqlalchemy import select
                from app.models.core.forecast import CoreForecastRun
                retained = {str(value) for value in db.execute(select(CoreForecastRun.run_id)).scalars()}
            try:
                prune_artifacts(retained)
                prune_old_sessions(keep_n=4)
            except OSError:
                logger.warning("Could not remove expired forecast artifacts", exc_info=True)
            emit(4, "completed", "Forecast ready. Inventory analysis and database save completed; SHAP is available on demand.")
            return run_id
        finally:
            prewarm_executor.shutdown(wait=False)


class ForecastJobs:
    def __init__(self, runner=run_live_pipeline):
        self.runner = runner
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forecast")
        self.jobs: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.active: str | None = None

    def start(self, request_id: str) -> dict[str, Any]:
        with self.lock:
            if request_id in self.keys:
                return self.get(self.keys[request_id])
            if self.active:
                self.keys[request_id] = self.active
                return self.get(self.active)
            if len(self.jobs) >= 30:
                oldest = next(iter(self.jobs))
                del self.jobs[oldest]
                self.keys = {k: v for k, v in self.keys.items() if v != oldest}
            job_id = str(uuid4())
            self.jobs[job_id] = {
                "job_id": job_id, "status": "queued", "sequence": 0, "run_id": None,
                "error": None, "created_at": datetime.now(timezone.utc).isoformat(),
                "progress": 0.0,
                "steps": [{"id": i, "title": name, "status": "pending", "message": "Waiting"}
                          for i, name in enumerate(STEP_NAMES, 1)],
            }
            self.keys[request_id] = job_id
            self.active = job_id
            self.executor.submit(self._run, job_id, request_id)
            return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self.jobs[job_id])

    def _run(self, job_id: str, session_key: str | None = None) -> None:
        active_step = 1

        def emit(step: int, status: str, message: str, progress: float | None = None) -> None:
            nonlocal active_step
            with self.lock:
                job = self.jobs[job_id]
                if any(s['status'] != 'completed' for s in job['steps'][:step - 1]):
                    raise ValueError("Pipeline attempted to skip an unfinished stage.")
                active_step = step
                job['status'] = 'running'
                job['steps'][step - 1].update(status=status, message=message)

                if progress is not None:
                    calc_prog = progress
                elif status == 'completed':
                    calc_prog = step * 25.0
                else:
                    base = (step - 1) * 25.0
                    sub = 5.0
                    if step == 1:
                        sub = 14.0 if ("history" in message.lower() or "fetch" in message.lower()) else 6.0
                    elif step == 2:
                        sub_steps = ["future", "pricing", "momentum", "rolling", "discount", "validat"]
                        matched = [i for i, s in enumerate(sub_steps, 1) if s in message.lower()]
                        sub = (matched[0] / len(sub_steps)) * 24.0 if matched else 10.0
                    elif step == 3:
                        import re
                        m = re.search(r"day\s+(\d+)/14", message, re.I)
                        sub = (int(m.group(1)) / 14.0) * 24.0 if m else 3.0
                    elif step == 4:
                        sub = 18.0 if ("saving" in message.lower() or "database" in message.lower()) else 8.0
                    calc_prog = base + sub

                job['progress'] = round(max(job.get('progress', 0.0), min(99.0, calc_prog)), 1)
                job['sequence'] += 1

        try:
            import inspect
            sig = inspect.signature(self.runner)
            if "session_key" in sig.parameters:
                run_id = self.runner(emit, session_key=session_key)
            else:
                run_id = self.runner(emit)
            with self.lock:
                job = self.jobs[job_id]
                if not run_id or any(s['status'] != 'completed' for s in job['steps']):
                    raise ValueError("Pipeline ended without committed results or completed stages.")
                job.update(status='completed', run_id=run_id, shap_status='on_demand', progress=100.0)
                job['sequence'] += 1
        except Exception as exc:
            logger.exception("Forecast job %s failed in stage %s", job_id, active_step)
            # SQLAlchemy errors may contain SQL parameters/connection details.
            from sqlalchemy.exc import SQLAlchemyError
            message = "Database operation failed; check the backend logs." if isinstance(exc, SQLAlchemyError) else str(exc)
            with self.lock:
                job = self.jobs[job_id]
                job.update(status='failed', error=message)
                job['steps'][active_step - 1].update(status='failed', message=message)
                job['sequence'] += 1
        finally:
            with self.lock:
                self.active = None


forecast_jobs = ForecastJobs()
