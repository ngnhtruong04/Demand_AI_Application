from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


engine = create_engine(
    settings.api_database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_seconds,
    connect_args={
        "sslmode": settings.rds_ssl_mode,
        "sslrootcert": settings.rds_ssl_root_cert,
        "connect_timeout": 10,
        "application_name": "rohlik-fastapi-local",
    },
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Provide one SQLAlchemy session per request."""
    database_session = SessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()

