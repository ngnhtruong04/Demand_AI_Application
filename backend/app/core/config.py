from pathlib import Path
from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    app_name: str = "Rohlik Sales API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    rds_endpoint: str
    rds_port: int = 5432
    rds_database: str
    rds_master_username: str
    rds_master_password: SecretStr
    rds_api_username: str
    rds_api_password: SecretStr
    rds_ssl_mode: str = "verify-full"
    rds_ssl_root_cert: str = "certs/global-bundle.pem"

    raw_data_dir: str = "data/raw"
    raw_profile_report: str = "reports/raw_profile.json"

    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 300

    # LLM Provider API Keys (OpenRouter, ChatGPT, Groq)
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    groq_api_key: str | None = None

    # Centralized reporting currency configuration (single point of truth)
    default_currency: str = "Thousand VND"
    default_currency_unit: str = "K VNĐ"

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def resolve_backend_paths(self) -> "Settings":
        for attr in ("rds_ssl_root_cert", "raw_data_dir", "raw_profile_report"):
            val = getattr(self, attr)
            if val:
                p = Path(val)
                if not p.is_absolute():
                    setattr(self, attr, str(BACKEND_ROOT / p))
        return self

    @model_validator(mode="after")
    def validate_user_separation(self) -> "Settings":
        if self.app_env != "test" and self.rds_master_username == self.rds_api_username:
            raise ValueError(
                "Master username and API username must not be identical in non-test environment"
            )
        return self

    @property
    def api_database_url(self) -> URL:
        """Build database URL for FastAPI runtime (API user)."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.rds_api_username,
            password=self.rds_api_password.get_secret_value(),
            host=self.rds_endpoint,
            port=self.rds_port,
            database=self.rds_database,
        )

    @property
    def master_database_url(self) -> URL:
        """Build database URL for Alembic migrations and ingestion (Master user)."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.rds_master_username,
            password=self.rds_master_password.get_secret_value(),
            host=self.rds_endpoint,
            port=self.rds_port,
            database=self.rds_database,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
