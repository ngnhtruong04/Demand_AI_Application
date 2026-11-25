import os
from pathlib import Path
import pytest

from app.core.config import BACKEND_ROOT, Settings
from scripts.ingestion.common import DEFAULT_MANIFEST_PATH, load_manifest


def test_settings_resolves_relative_paths_to_backend_root(monkeypatch, tmp_path) -> None:
    # Change CWD to a clean temporary directory
    monkeypatch.chdir(tmp_path)

    settings = Settings(
        rds_endpoint="db.internal",
        rds_database="rohlik_sales",
        rds_master_username="tttv_admin",
        rds_master_password="master_secret_password",
        rds_api_username="tttv_demandforecast_api",
        rds_api_password="api_secret_password",
        app_env="test",
    )

    assert Path(settings.rds_ssl_root_cert) == BACKEND_ROOT / "certs" / "global-bundle.pem"
    assert Path(settings.raw_data_dir) == BACKEND_ROOT / "data" / "raw"
    assert Path(settings.raw_profile_report) == BACKEND_ROOT / "reports" / "raw_profile.json"


def test_settings_preserves_absolute_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    custom_cert = "/custom/path/cert.pem"
    custom_data = "/custom/path/raw_data"
    custom_report = "/custom/path/report.json"

    settings = Settings(
        rds_endpoint="db.internal",
        rds_database="rohlik_sales",
        rds_master_username="tttv_admin",
        rds_master_password="master_secret_password",
        rds_api_username="tttv_demandforecast_api",
        rds_api_password="api_secret_password",
        rds_ssl_root_cert=custom_cert,
        raw_data_dir=custom_data,
        raw_profile_report=custom_report,
        app_env="test",
    )

    assert settings.rds_ssl_root_cert == custom_cert
    assert settings.raw_data_dir == custom_data
    assert settings.raw_profile_report == custom_report


def test_settings_environment_variable_override(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAW_DATA_DIR", "/override/data/dir")
    monkeypatch.setenv("RDS_SSL_ROOT_CERT", "/override/certs/ca.pem")

    settings = Settings(
        rds_endpoint="db.internal",
        rds_database="rohlik_sales",
        rds_master_username="tttv_admin",
        rds_master_password="master_secret_password",
        rds_api_username="tttv_demandforecast_api",
        rds_api_password="api_secret_password",
        app_env="test",
    )

    assert settings.raw_data_dir == "/override/data/dir"
    assert settings.rds_ssl_root_cert == "/override/certs/ca.pem"


def test_load_manifest_finds_default_from_foreign_working_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    # 1. Default invocation
    datasets = load_manifest()
    assert len(datasets) == 4
    assert [d["name"] for d in datasets] == ["calendar", "inventory", "test_weights", "sales_train"]

    # 2. Invocation with relative path string
    datasets_rel = load_manifest("config/raw_datasets.json")
    assert len(datasets_rel) == 4
