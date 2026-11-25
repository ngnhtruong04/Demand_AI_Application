import os
import pytest
from sqlalchemy import text
from app.db.session import engine

pytestmark = pytest.mark.integration


@pytest.mark.skipif(os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1", reason="Core RDS checks are opt-in")
def test_api_role_reads_core_but_cannot_write():
    with engine.connect() as connection:
        counts = connection.execute(text("SELECT (SELECT count(*) FROM core.inventory), (SELECT count(*) FROM core.calendar), (SELECT count(*) FROM core.sales_daily), (SELECT count(*) FROM core.series_weights)")).one()
        assert counts == (5432, 23016, 4007419, 5390)
        privileges = connection.execute(text("SELECT has_schema_privilege(current_user,'core','USAGE'), has_table_privilege(current_user,'core.sales_daily','SELECT'), has_table_privilege(current_user,'core.sales_daily','INSERT'), has_table_privilege(current_user,'raw.sales_train','UPDATE')")).one()
        assert privileges == (True, True, False, False)
