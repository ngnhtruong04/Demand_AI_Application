"""Create raw schema and tables with permissions

Revision ID: 0001_raw_schema
Revises: 
Create Date: 2026-09-07 16:07:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_raw_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create schema raw and configure permissions
    op.execute("CREATE SCHEMA IF NOT EXISTS raw AUTHORIZATION tttv_admin")
    op.execute("REVOKE CREATE ON SCHEMA raw FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA raw TO tttv_demandforecast_api")

    # 2. Create raw.ingestion_log
    op.execute(
        """
        CREATE TABLE raw.ingestion_log (
            ingestion_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_file        TEXT NOT NULL,
            target_schema      TEXT NOT NULL,
            target_table       TEXT NOT NULL,
            file_sha256        TEXT NOT NULL,
            file_size_bytes    BIGINT NOT NULL,
            expected_row_count BIGINT,
            loaded_row_count   BIGINT,
            status             TEXT NOT NULL,
            started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at       TIMESTAMPTZ,
            error_message      TEXT,
            CONSTRAINT ck_ingestion_log_status
                CHECK (status IN ('running', 'success', 'failed', 'skipped')),
            CONSTRAINT uq_ingestion_file
                UNIQUE (target_schema, target_table, file_sha256)
        );
        """
    )

    # 3. Create raw.calendar
    op.create_table(
        "calendar",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("holiday_name", sa.Text(), nullable=True),
        sa.Column("holiday", sa.Integer(), nullable=False),
        sa.Column("shops_closed", sa.Integer(), nullable=False),
        sa.Column("winter_school_holidays", sa.Integer(), nullable=False),
        sa.Column("school_holidays", sa.Integer(), nullable=False),
        sa.Column("warehouse", sa.Text(), nullable=False),
        schema="raw",
    )

    # 4. Create raw.inventory
    op.create_table(
        "inventory",
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("product_unique_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("L1_category_name_en", sa.Text(), nullable=False),
        sa.Column("L2_category_name_en", sa.Text(), nullable=False),
        sa.Column("L3_category_name_en", sa.Text(), nullable=False),
        sa.Column("L4_category_name_en", sa.Text(), nullable=False),
        sa.Column("warehouse", sa.Text(), nullable=False),
        schema="raw",
    )

    # 5. Create raw.test_weights
    op.create_table(
        "test_weights",
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("weight", sa.Double(), nullable=False),
        schema="raw",
    )

    # 6. Create raw.sales_train
    op.create_table(
        "sales_train",
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("warehouse", sa.Text(), nullable=False),
        sa.Column("total_orders", sa.Double(), nullable=True),
        sa.Column("sales", sa.Double(), nullable=True),
        sa.Column("sell_price_main", sa.Double(), nullable=False),
        sa.Column("availability", sa.Double(), nullable=False),
        sa.Column("type_0_discount", sa.Double(), nullable=False),
        sa.Column("type_1_discount", sa.Double(), nullable=False),
        sa.Column("type_2_discount", sa.Double(), nullable=False),
        sa.Column("type_3_discount", sa.Double(), nullable=False),
        sa.Column("type_4_discount", sa.Double(), nullable=False),
        sa.Column("type_5_discount", sa.Double(), nullable=False),
        sa.Column("type_6_discount", sa.Double(), nullable=False),
        schema="raw",
    )

    # 7. Grant SELECT only on the four raw data tables to tttv_demandforecast_api
    op.execute(
        """
        GRANT SELECT ON TABLE
            raw.calendar,
            raw.inventory,
            raw.sales_train,
            raw.test_weights
        TO tttv_demandforecast_api;
        """
    )


def downgrade() -> None:
    # Revoke permissions
    op.execute(
        """
        REVOKE SELECT ON TABLE
            raw.calendar,
            raw.inventory,
            raw.sales_train,
            raw.test_weights
        FROM tttv_demandforecast_api;
        """
    )
    op.drop_table("sales_train", schema="raw")
    op.drop_table("test_weights", schema="raw")
    op.drop_table("inventory", schema="raw")
    op.drop_table("calendar", schema="raw")
    op.drop_table("ingestion_log", schema="raw")
    op.execute("REVOKE USAGE ON SCHEMA raw FROM tttv_demandforecast_api")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")
