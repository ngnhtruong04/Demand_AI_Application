import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from scripts.ingestion import validate_raw


class MockCursor:
    def __init__(self):
        self.fetchone_results = []
        self.fetchall_results = []

    def execute(self, query, params=None):
        pass

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return (True,)

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    def __init__(self, cursor=None):
        self.cursor_mock = cursor or MockCursor()

    def cursor(self):
        return self.cursor_mock

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_validate_raw_logger_exists():
    """Verify logger object is defined and configured."""
    assert hasattr(validate_raw, "logger")
    assert validate_raw.logger is not None
    assert validate_raw.logger.name == "scripts.ingestion.validate_raw"


def test_validate_permissions_runs_without_name_error(monkeypatch):
    """
    Test validate_permissions runs through all checks with mock DB,
    ensuring logger calls and logic execute cleanly without NameError.
    """
    mock_cursor = MockCursor()
    # 1. CONNECT -> True
    # 2. USAGE -> True
    # 3. CREATE -> False (expected False)
    # 4. For 4 tables: SELECT -> True, and 4 write privs (INSERT, UPDATE, DELETE, TRUNCATE) -> False
    # 5. ingestion_log SELECT -> False (expected False)
    # 6. API user test connection SELECT 1 -> True
    mock_cursor.fetchone_results = [
        (True,),   # CONNECT
        (True,),   # USAGE
        (False,),  # CREATE
        # calendar
        (True,), (False,), (False,), (False,), (False,),
        # inventory
        (True,), (False,), (False,), (False,), (False,),
        # sales_train
        (True,), (False,), (False,), (False,), (False,),
        # test_weights
        (True,), (False,), (False,), (False,), (False,),
        # ingestion_log SELECT
        (False,),
        # API connection test SELECT 1
        (1,),
    ]

    mock_conn = MockConnection(mock_cursor)
    monkeypatch.setattr(validate_raw, "get_master_connection", lambda: mock_conn)
    monkeypatch.setattr(validate_raw, "get_api_connection", lambda: mock_conn)

    results = validate_raw.validate_permissions()
    assert results["all_passed"] is True
    assert results["connect_database"]["pass"] is True
    assert results["schema_raw_usage"]["pass"] is True
    assert results["schema_raw_create"]["pass"] is True
    assert results["tables"]["raw.calendar"]["pass"] is True
    assert results["tables"]["raw.ingestion_log"]["pass"] is True
    assert results["api_connection_test"]["pass"] is True


def test_validate_cross_table_reconciliation_runs_without_error(monkeypatch):
    """Test cross table reconciliation with mock DB."""
    mock_cursor = MockCursor()
    mock_cursor.fetchone_results = [
        (0,),  # unmatched_sales_inventory
        (0,),  # unmatched_sales_calendar
    ]
    mock_cursor.fetchall_results = [
        [],    # sample unmatched
    ]
    mock_conn = MockConnection(mock_cursor)
    monkeypatch.setattr(validate_raw, "get_master_connection", lambda: mock_conn)

    results = validate_raw.validate_cross_table_reconciliation()
    assert results["sales_train_vs_inventory"]["consistent"] is True
    assert results["sales_train_vs_calendar"]["consistent"] is True


def test_main_manifest_error_logs_and_exits(monkeypatch, tmp_path):
    """Verify that when manifest fails to load, it logs error and exits without NameError."""
    temp_report = tmp_path / "test_report.json"
    monkeypatch.setattr(validate_raw, "REPORT_FILE", temp_report)

    def failing_manifest():
        raise ValueError("Simulated manifest load error")

    monkeypatch.setattr(validate_raw, "load_manifest", failing_manifest)

    with pytest.raises(SystemExit) as exc_info:
        validate_raw.main()
    assert exc_info.value.code == 1
    # Report should not be created if manifest failed
    assert not temp_report.exists()
