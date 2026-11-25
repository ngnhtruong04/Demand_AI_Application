import json
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import forecast
from app.services.forecast_jobs import ForecastJobs


def wait_terminal(manager, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = manager.get(job_id)
        if snapshot['status'] in {'completed', 'failed'}:
            return snapshot
        time.sleep(0.005)
    pytest.fail('Job did not finish')


def success(emit):
    for stage in range(1, 5):
        emit(stage, 'running', 'Working')
        emit(stage, 'completed', 'Done')
    return str(uuid4())


def test_stages_wait_for_actual_work_and_commit():
    entered = threading.Event()
    release = threading.Event()
    def runner(emit):
        emit(1, 'running', 'Fetching')
        entered.set()
        assert release.wait(3)
        emit(1, 'completed', 'Fetched')
        for stage in range(2, 5):
            emit(stage, 'running', 'Working')
            emit(stage, 'completed', 'Done')
        return 'saved-run'
    manager = ForecastJobs(runner)
    try:
        job = manager.start('request')
        assert entered.wait(3)
        snapshot = manager.get(job['job_id'])
        assert snapshot['steps'][0]['status'] == 'running'
        assert all(s['status'] == 'pending' for s in snapshot['steps'][1:])
        assert snapshot['run_id'] is None
        assert manager.start('request')['job_id'] == job['job_id']
        assert manager.start('another-tab')['job_id'] == job['job_id']
        release.set()
        final = wait_terminal(manager, job['job_id'])
        assert final['status'] == 'completed'
        assert final['run_id'] == 'saved-run'
    finally:
        release.set()
        manager.executor.shutdown()


@pytest.mark.parametrize('failure_stage', [1, 2, 3, 4])
def test_failure_marks_only_current_stage_and_never_completes(failure_stage):
    def runner(emit):
        for stage in range(1, 5):
            emit(stage, 'running', 'Working')
            if stage == failure_stage:
                raise ValueError('Actual pipeline error')
            emit(stage, 'completed', 'Done')
    manager = ForecastJobs(runner)
    try:
        final = wait_terminal(manager, manager.start('request')['job_id'])
        assert final['status'] == 'failed'
        assert final['run_id'] is None
        assert final['error'] == 'Actual pipeline error'
        assert final['steps'][failure_stage - 1]['status'] == 'failed'
        assert all(s['status'] == 'pending' for s in final['steps'][failure_stage:])
    finally:
        manager.executor.shutdown()


def test_missing_committed_run_is_failure():
    def runner(emit):
        success(emit)
        return None
    manager = ForecastJobs(runner)
    try:
        assert wait_terminal(manager, manager.start('request')['job_id'])['status'] == 'failed'
    finally:
        manager.executor.shutdown()


def test_post_idempotency_status_and_sse_replay(monkeypatch):
    calls = []
    def runner(emit):
        calls.append(True)
        return success(emit)
    manager = ForecastJobs(runner)
    monkeypatch.setattr(forecast, 'forecast_jobs', manager)
    try:
        with TestClient(app) as client:
            payload = {'request_id': str(uuid4())}
            response = client.post('/api/v1/forecast/runs', json=payload)
            assert response.status_code == 202
            job_id = response.json()['job_id']
            wait_terminal(manager, job_id)
            assert client.post('/api/v1/forecast/runs', json=payload).json()['job_id'] == job_id
            assert client.get(f'/api/v1/forecast/runs/{job_id}').json()['status'] == 'completed'
            for _ in range(2):
                response = client.get(f'/api/v1/forecast/runs/{job_id}/events')
                event = next(line[6:] for line in response.text.splitlines() if line.startswith('data: '))
                assert json.loads(event)['status'] == 'completed'
            assert len(calls) == 1
            assert client.get(f'/api/v1/forecast/runs/{uuid4()}').status_code == 404
    finally:
        manager.executor.shutdown()


def test_real_runner_saves_new_forecast_without_computing_shap(monkeypatch, tmp_path):
    """Exercise orchestration + real parquet adapter; substitute models and external IO."""
    from datetime import date, timedelta
    from types import SimpleNamespace
    import polars as pl
    from app.services.forecast_jobs import run_live_pipeline
    from app.services import forecast_persistence
    from app.pipeline import load_pipeline, recursive_ensemble
    from app.db import session

    dates = [date(2026, 9, 16) + timedelta(days=i) for i in range(14)]
    future = pl.DataFrame({'unique_id': ['10'] * 14, 'date': dates})
    monkeypatch.setattr(load_pipeline, 'fetch_raw_data', lambda **kw: future)
    monkeypatch.setattr(load_pipeline, 'load_and_engineer_splits', lambda **kw: (future, future))
    from app.services import forecast_jobs, forecast_artifacts
    monkeypatch.setattr(forecast_jobs, 'ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(forecast_artifacts, 'ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(forecast_jobs, 'snapshot_models', lambda source, destination: destination.mkdir())
    stages = []
    class Predictor:
        feature_columns = ['sales_lag_1']
        def __init__(self, **kwargs):
            self.explainer = self
        def predict(self, past, frame, on_horizon):
            rows = []
            for horizon, dt in enumerate(dates, 1):
                rec = {'unique_id': '10', 'date': dt, 'horizon': horizon, 'predicted_sales': 12.0}
                rows.append(rec)
                on_horizon(horizon, [rec], None, None, None, None)
            return pl.DataFrame(rows)
        def explain(self, *args, **kwargs):
            pytest.fail("Forecast readiness must not depend on SHAP computation")
    monkeypatch.setattr(recursive_ensemble, 'RecursiveEnsemblePredictor', Predictor)
    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def scalars(self): return [saved_id[0]]
    saved_id = []
    monkeypatch.setattr(session, 'SessionLocal', DB)
    def save(db, *, preds_path, strict, include_shap, run_id, model_version):
        assert include_shap is False
        saved_id.append(run_id)
        assert strict
        assert stages[-1][:2] == (4, 'running')
        data = forecast_persistence.extract_model_parquet_data(preds_path, include_shap=False)
        assert data['start_date'] == dates[0]
        assert data['end_date'] == dates[-1]
        assert data['pred_totals'] == {'10': 168.0}
        assert len(data['daily_predictions']['10']) == 14
        assert data['daily_features_map'] == {}
        return SimpleNamespace(run_id=run_id)
    monkeypatch.setattr(forecast_persistence, 'save_forecast_run', save)
    assert run_live_pipeline(lambda *args: stages.append(args)) == str(saved_id[0])
    assert (tmp_path / str(saved_id[0]) / 'horizon-14.pickle').is_file()
    assert [(step, status) for step, status, _ in stages if status == 'completed'] == [(1,'completed'), (2,'completed'), (3,'completed'), (4,'completed')]


def test_missing_models_reports_all_required_artifacts(tmp_path):
    from app.pipeline.recursive_ensemble import RecursiveEnsemblePredictor
    with pytest.raises(FileNotFoundError, match='lightgbm.joblib, xgboost.joblib, catboost.joblib'):
        RecursiveEnsemblePredictor(models_dir=tmp_path)


@pytest.mark.parametrize('uid, predicted_uid', [('10', 10), ('0010', '0010')])
def test_recursive_updates_preserve_series_key_types(monkeypatch, uid, predicted_uid):
    from datetime import date
    import polars as pl
    from app.pipeline.load_pipeline import recompute_future_features, RohlikFeatureEngineeringPipeline
    monkeypatch.setattr(RohlikFeatureEngineeringPipeline, 'recompute_target_dependent_features', lambda self, frame: frame)
    past = pl.DataFrame({'unique_id': [uid], 'warehouse': ['A'], 'date': [date(2026, 9, 15)], 'sales': [2.0]})
    future = pl.DataFrame({'unique_id': [uid], 'warehouse': ['A'], 'date': [date(2026, 9, 16)], 'sales': [None]})
    prediction = pl.DataFrame({'unique_id': [predicted_uid], 'warehouse': ['A'], 'date': [date(2026, 9, 16)], 'sales': [7.0]})
    updated = recompute_future_features(future, past, prediction)
    assert updated['unique_id'].to_list() == [uid]
    assert updated['sales'].to_list() == [7.0]


def test_live_save_uses_only_predicted_items_and_commits_new_status(monkeypatch):
    from datetime import date, timedelta
    from sqlalchemy.sql.dml import Insert
    from app.services import forecast_persistence as persistence
    start = date(2026, 9, 16)
    monkeypatch.setattr(persistence, 'extract_model_parquet_data', lambda **kwargs: {
        'pred_totals': {'10': 28.0},
        'daily_predictions': {'10': [{'day': i + 1, 'date': str(start + timedelta(days=i)), 'predicted': 2.0} for i in range(14)]},
        'drivers_breakdown_map': {}, 'summary_features_map': {}, 'daily_features_map': {},
        'start_date': start, 'end_date': start + timedelta(days=13),
    })
    monkeypatch.setattr(persistence, 'prune_old_forecast_runs', lambda *args, **kwargs: 0)
    class Result:
        def mappings(self): return self
        def fetchall(self):
            return [{'unique_id': uid, 'warehouse': 'A', 'current_stock': 1, 'safety_stock': 2,
                     'baseline_reorder_point': 100, 'lead_time_days': 3, 'scenario_group': 'In Stock',
                     'baseline_avg_daily_sales': 999} for uid in ['10', 'unpredicted']]
    class DB:
        committed = False
        inserts = {}
        def execute(self, statement, values=None):
            if isinstance(statement, Insert): self.inserts[statement.table.name] = values
            return Result()
        def add(self, obj): self.run = obj
        def flush(self): pass
        def commit(self): self.committed = True
    db = DB()
    run = persistence.save_forecast_run(db, strict=True)
    assert db.committed
    assert run.total_items == 1
    assert run.forecast_start_date == start
    summary = db.inserts['forecast_item_summary'][0]
    assert summary['scenario_group'] == 'Critical'
    assert summary['baseline_reorder_point'] == 8
    assert summary['forecast_14d'] == 28
    assert len(db.inserts['forecast_daily_points']) == 14
