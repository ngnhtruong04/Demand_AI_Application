"""Create core schema and relational tables.

Revision ID: 0003_core_schema
Revises: 0002_raw_indexes
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0003_core_schema"
down_revision: Union[str, None] = "0002_raw_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA core AUTHORIZATION tttv_admin")
    op.execute("REVOKE CREATE ON SCHEMA core FROM PUBLIC")
    op.execute("""
CREATE TABLE core.inventory (
 unique_id TEXT PRIMARY KEY, warehouse TEXT NOT NULL, product_unique_id BIGINT, name TEXT,
 l1_category_name_en TEXT, l2_category_name_en TEXT, l3_category_name_en TEXT, l4_category_name_en TEXT,
 CONSTRAINT uq_core_inventory_id_warehouse UNIQUE (unique_id, warehouse),
 CONSTRAINT ck_core_inventory_unique_id_nonempty CHECK (btrim(unique_id) <> ''),
 CONSTRAINT ck_core_inventory_warehouse_nonempty CHECK (btrim(warehouse) <> ''));
CREATE TABLE core.calendar (
 warehouse TEXT NOT NULL, date DATE NOT NULL, holiday_name TEXT, holiday SMALLINT, shops_closed SMALLINT,
 winter_school_holidays SMALLINT, school_holidays SMALLINT,
 CONSTRAINT pk_core_calendar PRIMARY KEY (warehouse, date),
 CONSTRAINT ck_core_calendar_warehouse_nonempty CHECK (btrim(warehouse) <> ''),
 CONSTRAINT ck_core_calendar_holiday_flag CHECK (holiday IN (0, 1)),
 CONSTRAINT ck_core_calendar_shops_closed_flag CHECK (shops_closed IN (0, 1)),
 CONSTRAINT ck_core_calendar_winter_school_flag CHECK (winter_school_holidays IN (0, 1)),
 CONSTRAINT ck_core_calendar_school_flag CHECK (school_holidays IN (0, 1)));
CREATE TABLE core.sales_daily (
 unique_id TEXT NOT NULL, warehouse TEXT NOT NULL, date DATE NOT NULL, sales DOUBLE PRECISION,
 total_orders DOUBLE PRECISION, sell_price_main DOUBLE PRECISION, availability DOUBLE PRECISION,
 type_0_discount DOUBLE PRECISION, type_1_discount DOUBLE PRECISION, type_2_discount DOUBLE PRECISION,
 type_3_discount DOUBLE PRECISION, type_4_discount DOUBLE PRECISION, type_5_discount DOUBLE PRECISION,
 type_6_discount DOUBLE PRECISION,
 CONSTRAINT pk_core_sales_daily PRIMARY KEY (unique_id, date),
 CONSTRAINT fk_core_sales_inventory FOREIGN KEY (unique_id, warehouse) REFERENCES core.inventory (unique_id, warehouse),
 CONSTRAINT fk_core_sales_calendar FOREIGN KEY (warehouse, date) REFERENCES core.calendar (warehouse, date),
 CONSTRAINT ck_core_sales_unique_id_nonempty CHECK (btrim(unique_id) <> ''),
 CONSTRAINT ck_core_sales_warehouse_nonempty CHECK (btrim(warehouse) <> ''));
CREATE INDEX ix_core_sales_daily_warehouse_date ON core.sales_daily (warehouse, date);
CREATE TABLE core.series_weights (
 unique_id TEXT PRIMARY KEY REFERENCES core.inventory (unique_id), weight DOUBLE PRECISION NOT NULL,
 CONSTRAINT ck_core_weights_unique_id_nonempty CHECK (btrim(unique_id) <> ''),
 CONSTRAINT ck_core_weights_positive_finite CHECK (weight > 0 AND weight < 'Infinity'::double precision));
GRANT USAGE ON SCHEMA core TO tttv_demandforecast_api;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO tttv_demandforecast_api;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA core FROM tttv_demandforecast_api;
""")


def downgrade() -> None:
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA core FROM tttv_demandforecast_api")
    op.execute("REVOKE USAGE ON SCHEMA core FROM tttv_demandforecast_api")
    op.execute("DROP TABLE core.series_weights")
    op.execute("DROP TABLE core.sales_daily")
    op.execute("DROP TABLE core.calendar")
    op.execute("DROP TABLE core.inventory")
    op.execute("DROP SCHEMA core")
