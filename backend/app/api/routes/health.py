import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/database")
def database_health() -> dict[str, str | bool]:
    """Verify that PostgreSQL is reachable and this session uses TLS."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            tls_enabled = bool(
                connection.execute(
                    text(
                        "SELECT ssl FROM pg_stat_ssl "
                        "WHERE pid = pg_backend_pid()"
                    )
                ).scalar_one()
            )
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    if not tls_enabled:
        logger.error("Database connection succeeded without TLS")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is not encrypted",
        )

    return {
        "status": "healthy",
        "database": "connected",
        "tls": True,
    }

