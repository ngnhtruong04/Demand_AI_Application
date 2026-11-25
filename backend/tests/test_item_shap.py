import pickle
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from app.services import item_shap, forecast_artifacts


@pytest.fixture
def artifact_root(monkeypatch, tmp_path):
    monkeypatch.setattr(forecast_artifacts, 'ARTIFACT_ROOT', tmp_path)
    return tmp_path


def wait_finished(jobs, run_id, item_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = jobs.status(run_id, item_id)
        if value['status'] in {'failed', 'completed'}:
            return value
        time.sleep(0.005)
    pytest.fail('SHAP did not finish')


def test_selected_item_only_and_persistent_cache(monkeypatch, artifact_root):
    run_id = str(uuid4())
    directory = forecast_artifacts.run_directory(run_id)
    directory.mkdir()
    for day in range(1, 15):
        frame = pd.DataFrame({'category': pd.Categorical(['selected', f'other-{day}'])})
        records = [{'unique_id': uid, 'horizon': day} for uid in ('10', '20')]
        with (directory / f'horizon-{day}.pickle').open('wb') as stream:
            pickle.dump((records, frame, *[np.array([2., 3.])] * 3), stream)
    calls = []
    class Explainer:
        def explain(self, records, frame, *preds, mode, **kwargs):
            assert mode == 'online'
            assert len(records) == len(frame) == 14
            for r in records:
                assert r['unique_id'] == '10'
                calls.append(r['horizon'])
            return [{'horizon': r['horizon'], 'top_positive_features': [{'feature': 'sales_1', 'feature_label': 'Yesterday',
                     'feature_group': 'sales_lag', 'shap_value': 2., 'direction': 'increase'}], 'top_negative_features': []} for r in records]
    monkeypatch.setattr(item_shap, 'predictor_for_run', lambda run: SimpleNamespace(explainer=Explainer(), feature_columns=['sales_1']))
    writes = []
    class DB:
        committed = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement):
            writes.append(statement.compile().params)
            return SimpleNamespace(rowcount=1)
        def commit(self): self.committed = True
    db = DB()
    monkeypatch.setattr(item_shap, 'SessionLocal', lambda: db)
    def read(*args, **kwargs):
        assert db.committed
        return {'items': [{'id': '10', 'daily_points': [], 'grouped_drivers': []}]}
    monkeypatch.setattr(item_shap, 'get_latest_forecast_from_db', read)
    result = item_shap.calculate_item_shap(run_id, '10')
    assert calls == list(range(1, 15))
    assert len(writes) == 15
    assert writes[0]['all_features_shap'][0]['shap'] == 28
    assert writes[0]['drivers_breakdown'][0]['score'] == 100
    assert result['item']['shap_status'] == 'completed'
    assert item_shap.ItemShapJobs().status(run_id, '10') == result
    assert item_shap.ItemShapJobs().status(str(uuid4()), '10')['status'] == 'not_requested'


def test_deduplication_and_retry(monkeypatch, artifact_root):
    run_id = str(uuid4())
    directory = forecast_artifacts.run_directory(run_id)
    directory.mkdir()
    (directory / 'horizon-14.pickle').touch()
    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def scalar_one_or_none(self): return '10'
    monkeypatch.setattr(item_shap, 'SessionLocal', DB)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def calculate(run, item):
        calls.append((run, item))
        entered.set()
        assert release.wait(3)
        if len(calls) == 1: raise ValueError('SHAP error')
        return {'status': 'completed', 'run_id': run, 'item_id': item, 'item': {'id': item}}
    jobs = item_shap.ItemShapJobs(calculate)
    try:
        jobs.start(run_id, '10')
        assert entered.wait(3)
        assert jobs.start(run_id, '10')['status'] == 'running'
        release.set()
        assert wait_finished(jobs, run_id, '10')['status'] == 'failed'
        jobs.start(run_id, '10')
        assert wait_finished(jobs, run_id, '10')['status'] == 'completed'
        assert len(calls) == 2
    finally:
        release.set()
        jobs.executor.shutdown()


def test_missing_inputs_and_path_isolation(artifact_root):
    run = str(uuid4())
    jobs = item_shap.ItemShapJobs()
    try:
        with pytest.raises(FileNotFoundError, match='Run a new forecast'):
            jobs.start(run, '10')
        assert item_shap.cache_path(run, '../../escape').parent == artifact_root / run / 'shap'
    finally:
        jobs.executor.shutdown()


def test_priority_queue_promotion_and_eviction(monkeypatch, artifact_root):
    run_id = str(uuid4())
    directory = forecast_artifacts.run_directory(run_id)
    directory.mkdir()
    (directory / 'horizon-14.pickle').touch()

    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def scalar_one_or_none(self): return 'exists'
    monkeypatch.setattr(item_shap, 'SessionLocal', DB)

    entered, release = threading.Event(), threading.Event()
    order = []
    def calculate(run, item):
        if item == 'blocker':
            entered.set()
            release.wait(3)
        order.append(item)
        return {'status': 'completed', 'run_id': run, 'item_id': item, 'item': {'id': item}}

    jobs = item_shap.ItemShapJobs(calculate)
    try:
        jobs.start(run_id, 'blocker')
        assert entered.wait(3)

        for i in range(1, 6):
            jobs.start(run_id, str(i))
        assert [k[1] for k in jobs.queue] == ['5', '4', '3', '2', '1']

        # Item 6 evicts oldest '1'
        jobs.start(run_id, '6')
        assert [k[1] for k in jobs.queue] == ['6', '5', '4', '3', '2']
        assert jobs.status(run_id, '1')['status'] == 'not_requested'

        # Re-requesting '3' promotes it to front
        jobs.start(run_id, '3')
        assert [k[1] for k in jobs.queue] == ['3', '6', '5', '4', '2']

        release.set()
        wait_finished(jobs, run_id, '3')
        assert order[0] == 'blocker'
        assert order[1] == '3'
    finally:
        release.set()
        jobs.executor.shutdown()

