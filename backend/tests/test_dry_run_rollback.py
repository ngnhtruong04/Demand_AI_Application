from unittest.mock import MagicMock
import pytest

from scripts.ingestion import load_raw


class SpyConnection:
    """
    Connection mock that tracks all calls and their sequence,
    verifying rollback is always invoked before connection exit and commit is never called.
    """
    def __init__(self, copied_rows):
        self.call_log = []
        self.cursor_mock = MagicMock()
        self.cursor_mock.__enter__.return_value = self.cursor_mock
        self.cursor_mock.rowcount = -1
        self.cursor_mock.execute.side_effect = AssertionError("No table-count queries allowed")
        self.cursor_mock.copy.return_value.__exit__.side_effect = lambda *args: self._finish_copy(copied_rows)
        self.cursor_mock.copy.return_value.__enter__.return_value = MagicMock()

    def _finish_copy(self, copied_rows):
        self.cursor_mock.rowcount = copied_rows
        self.call_log.append(("copy_finished", copied_rows))
        return False

    def cursor(self):
        self.call_log.append(("cursor", None))
        return self.cursor_mock

    def rollback(self):
        self.call_log.append(("rollback", None))

    def commit(self):
        self.call_log.append(("commit", None))

    def __enter__(self):
        self.call_log.append(("__enter__", None))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.call_log.append(("__exit__", exc_type))


@pytest.fixture
def mock_dataset_and_csv(tmp_path):
    csv_file = tmp_path / "test_data.csv"
    # Header + 10 data rows
    lines = ["id,val\n"] + [f"{i},val_{i}\n" for i in range(10)]
    csv_file.write_text("".join(lines), encoding="utf-8")

    dataset = {
        "name": "test_ds",
        "file": "test_data.csv",
        "schema": "raw",
        "table": "test_ds",
    }
    return dataset, str(tmp_path)


def test_dry_run_success_always_rolls_back_before_exit(monkeypatch, mock_dataset_and_csv):
    dataset, raw_dir = mock_dataset_and_csv
    monkeypatch.setattr(load_raw.settings, "raw_data_dir", raw_dir)

    # COPY reports five rows after its context exits.
    spy_conn = SpyConnection(copied_rows=5)
    monkeypatch.setattr(load_raw, "get_master_connection", lambda: spy_conn)

    result = load_raw.load_dataset(dataset, dry_run=True, limit=5)

    assert result is True
    spy_conn.cursor_mock.execute.assert_not_called()
    spy_conn.cursor_mock.fetchone.assert_not_called()

    # Verify call sequence
    actions = [a[0] for a in spy_conn.call_log]
    assert "rollback" in actions
    assert "commit" not in actions

    # Verify rollback was called BEFORE __exit__
    rollback_idx = actions.index("rollback")
    exit_idx = actions.index("__exit__")
    assert rollback_idx < exit_idx, f"rollback ({rollback_idx}) must precede __exit__ ({exit_idx})"


def test_dry_run_mismatch_always_rolls_back_before_exit(monkeypatch, mock_dataset_and_csv):
    dataset, raw_dir = mock_dataset_and_csv
    monkeypatch.setattr(load_raw.settings, "raw_data_dir", raw_dir)

    # COPY reports three rows, but five were expected.
    spy_conn = SpyConnection(copied_rows=3)
    monkeypatch.setattr(load_raw, "get_master_connection", lambda: spy_conn)

    result = load_raw.load_dataset(dataset, dry_run=True, limit=5)

    assert result is False

    actions = [a[0] for a in spy_conn.call_log]
    assert "rollback" in actions
    assert "commit" not in actions

    rollback_idx = actions.index("rollback")
    exit_idx = actions.index("__exit__")
    assert rollback_idx < exit_idx, f"rollback ({rollback_idx}) must precede __exit__ ({exit_idx})"


def test_dry_run_exception_always_rolls_back_in_finally(monkeypatch, mock_dataset_and_csv):
    dataset, raw_dir = mock_dataset_and_csv
    monkeypatch.setattr(load_raw.settings, "raw_data_dir", raw_dir)

    spy_conn = SpyConnection(copied_rows=-1)
    # Simulate COPY query raising an exception
    spy_conn.cursor_mock.copy.side_effect = RuntimeError("Simulated COPY syntax error")
    monkeypatch.setattr(load_raw, "get_master_connection", lambda: spy_conn)

    result = load_raw.load_dataset(dataset, dry_run=True, limit=5)

    assert result is False

    actions = [a[0] for a in spy_conn.call_log]
    assert "rollback" in actions
    assert "commit" not in actions

    rollback_idx = actions.index("rollback")
    exit_idx = actions.index("__exit__")
    assert rollback_idx < exit_idx


def test_dry_run_does_not_query_counts_affected_by_concurrent_writes(monkeypatch, mock_dataset_and_csv):
    dataset, raw_dir = mock_dataset_and_csv
    monkeypatch.setattr(load_raw.settings, "raw_data_dir", raw_dir)

    # Existing rows and concurrent writes must not affect this COPY result.
    spy_conn = SpyConnection(copied_rows=5)
    monkeypatch.setattr(load_raw, "get_master_connection", lambda: spy_conn)

    result = load_raw.load_dataset(dataset, dry_run=True, limit=5)

    assert result is True
    spy_conn.cursor_mock.execute.assert_not_called()
    spy_conn.cursor_mock.fetchone.assert_not_called()

    actions = [a[0] for a in spy_conn.call_log]
    assert "rollback" in actions
    assert "commit" not in actions
    assert actions.index("rollback") < actions.index("__exit__")


@pytest.mark.parametrize("failure_point", ["cursor", "write"])
def test_dry_run_additional_failures_roll_back(monkeypatch, mock_dataset_and_csv, failure_point):
    dataset, raw_dir = mock_dataset_and_csv
    monkeypatch.setattr(load_raw.settings, "raw_data_dir", raw_dir)
    conn = SpyConnection(copied_rows=5)
    error = RuntimeError("simulated failure")
    if failure_point == "cursor":
        conn.cursor_mock.__enter__.side_effect = error
    else:
        conn.cursor_mock.copy.return_value.__enter__.return_value.write.side_effect = error
    monkeypatch.setattr(load_raw, "get_master_connection", lambda: conn)
    assert load_raw.load_dataset(dataset, dry_run=True, limit=5) is False
    actions = [a[0] for a in conn.call_log]
    assert actions[-2:] == ["rollback", "__exit__"]
    assert "commit" not in actions


def test_dry_run_unknown_copy_count_fails_closed(monkeypatch, mock_dataset_and_csv):
    dataset, raw_dir = mock_dataset_and_csv
    monkeypatch.setattr(load_raw.settings, "raw_data_dir", raw_dir)
    conn = SpyConnection(copied_rows=-1)
    monkeypatch.setattr(load_raw, "get_master_connection", lambda: conn)
    assert load_raw.load_dataset(dataset, dry_run=True, limit=5) is False
    assert [a[0] for a in conn.call_log][-2:] == ["rollback", "__exit__"]
