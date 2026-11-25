from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import engine as api_engine


def main() -> None:
    # 1. Check master database connection
    master_engine = create_engine(
        settings.master_database_url,
        pool_pre_ping=True,
        connect_args={
            "sslmode": settings.rds_ssl_mode,
            "sslrootcert": settings.rds_ssl_root_cert,
            "connect_timeout": 10,
            "application_name": "rohlik-check-db-master",
        },
    )

    tls_enabled = False
    try:
        with master_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            master_tls = bool(
                connection.execute(
                    text(
                        "SELECT ssl FROM pg_stat_ssl "
                        "WHERE pid = pg_backend_pid()"
                    )
                ).scalar_one()
            )
            tls_enabled = master_tls
        print("Master database connection: OK")
    except SQLAlchemyError as exc:
        raise SystemExit(f"Master database connection: FAILED\n{exc}") from exc
    finally:
        master_engine.dispose()

    # 2. Check API database connection
    try:
        with api_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            api_tls = bool(
                connection.execute(
                    text(
                        "SELECT ssl FROM pg_stat_ssl "
                        "WHERE pid = pg_backend_pid()"
                    )
                ).scalar_one()
            )
            tls_enabled = tls_enabled and api_tls
        print("API database connection: OK")
    except SQLAlchemyError as exc:
        raise SystemExit(f"API database connection: FAILED\n{exc}") from exc

    print(f"TLS connection: {'enabled' if tls_enabled else 'disabled'}")

    if not tls_enabled:
        raise SystemExit("Refusing to continue: PostgreSQL connection is not encrypted")


if __name__ == "__main__":
    main()
