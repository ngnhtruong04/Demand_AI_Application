import os
import pytest

from scripts.ingestion.common import get_api_connection, get_master_connection

run_integration = os.environ.get("RUN_RDS_INTEGRATION_TESTS") == "1"


@pytest.mark.integration
@pytest.mark.skipif(not run_integration, reason="RDS integration tests are opt-in via RUN_RDS_INTEGRATION_TESTS=1")
def test_master_and_api_connections_live() -> None:
    # 1. Master connection can query version and raw schema
    with get_master_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database()")
            user, dbname = cur.fetchone()
            assert "admin" in user

    # 2. API connection can read data from raw tables
    with get_api_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            api_user = cur.fetchone()[0]
            assert "api" in api_user

            for table in ["calendar", "inventory", "sales_train", "test_weights"]:
                cur.execute(f"SELECT count(*) FROM raw.{table}")
                count = cur.fetchone()[0]
                assert count > 0

            # API user must NOT be able to read ingestion_log
            import psycopg
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT count(*) FROM raw.ingestion_log")
