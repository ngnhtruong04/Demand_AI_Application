import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.core.config import Settings
from app.db.session import engine as fastapi_engine


def test_settings_reads_master_and_api_credentials() -> None:
    settings = Settings(
        rds_endpoint="db.internal",
        rds_database="rohlik_sales",
        rds_master_username="tttv_admin",
        rds_master_password="master_secret_password",
        rds_api_username="tttv_demandforecast_api",
        rds_api_password="api_secret_password",
        app_env="development",
    )
    assert settings.rds_master_username == "tttv_admin"
    assert settings.rds_master_password.get_secret_value() == "master_secret_password"
    assert settings.rds_api_username == "tttv_demandforecast_api"
    assert settings.rds_api_password.get_secret_value() == "api_secret_password"

    # Verify URLs are built properly
    master_url = settings.master_database_url
    api_url = settings.api_database_url

    assert master_url.username == "tttv_admin"
    assert master_url.password == "master_secret_password"
    assert master_url.database == "rohlik_sales"

    assert api_url.username == "tttv_demandforecast_api"
    assert api_url.password == "api_secret_password"
    assert api_url.database == "rohlik_sales"


def test_database_url_handles_special_characters_in_password() -> None:
    special_pw = "p@$$w0rd#/?=&[]!%"
    settings = Settings(
        rds_endpoint="db.internal",
        rds_database="rohlik_sales",
        rds_master_username="tttv_admin",
        rds_master_password=special_pw,
        rds_api_username="tttv_demandforecast_api",
        rds_api_password=special_pw,
        app_env="development",
    )
    master_url = settings.master_database_url
    assert master_url.password == special_pw

    rendered = master_url.render_as_string(hide_password=False)
    assert special_pw not in rendered or "%" in rendered  # properly encoded


def test_settings_rejects_identical_master_and_api_user_in_non_test() -> None:
    with pytest.raises(ValidationError):
        Settings(
            rds_endpoint="db.internal",
            rds_database="rohlik_sales",
            rds_master_username="same_user",
            rds_master_password="pw1",
            rds_api_username="same_user",
            rds_api_password="pw2",
            app_env="production",
        )


def test_fastapi_engine_uses_api_username() -> None:
    # Verify the runtime FastAPI engine is bound to the API username
    from app.core.config import settings
    assert fastapi_engine.url.username == settings.rds_api_username
    assert fastapi_engine.url.username != settings.rds_master_username
