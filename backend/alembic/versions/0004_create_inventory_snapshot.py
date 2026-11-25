"""Create demo inventory snapshots.

Revision ID: 0004_inventory_snapshot
Revises: 0003_core_schema
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_inventory_snapshot"
down_revision: Union[str, None] = "0003_core_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE core.inventory_snapshot (
 unique_id TEXT NOT NULL REFERENCES core.inventory (unique_id),
 snapshot_date DATE NOT NULL,
 current_stock BIGINT NOT NULL,
 lead_time_days INTEGER NOT NULL,
 safety_stock DOUBLE PRECISION NOT NULL,
 baseline_avg_daily_sales DOUBLE PRECISION NOT NULL,
 baseline_reorder_point DOUBLE PRECISION NOT NULL,
 scenario_group TEXT NOT NULL,
 source_file TEXT NOT NULL,
 source_sha256 TEXT NOT NULL,
 loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 is_demo BOOLEAN NOT NULL DEFAULT TRUE,
 CONSTRAINT pk_core_inventory_snapshot PRIMARY KEY (unique_id, snapshot_date),
 CONSTRAINT ck_inventory_snapshot_current_stock CHECK (current_stock >= 0),
 CONSTRAINT ck_inventory_snapshot_lead_time CHECK (lead_time_days >= 0),
 CONSTRAINT ck_inventory_snapshot_safety_stock CHECK (
   safety_stock >= 0 AND safety_stock < 'Infinity'::double precision),
 CONSTRAINT ck_inventory_snapshot_avg_sales CHECK (
   baseline_avg_daily_sales >= 0 AND baseline_avg_daily_sales < 'Infinity'::double precision),
 CONSTRAINT ck_inventory_snapshot_reorder_point CHECK (
   baseline_reorder_point >= 0 AND baseline_reorder_point < 'Infinity'::double precision),
 CONSTRAINT ck_inventory_snapshot_scenario_group CHECK (
   scenario_group IN ('In Stock', 'Monitor', 'Reorder', 'Critical', 'Deadstock')),
 CONSTRAINT ck_inventory_snapshot_sha256 CHECK (source_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX ix_core_inventory_snapshot_date ON core.inventory_snapshot (snapshot_date);
GRANT SELECT ON core.inventory_snapshot TO tttv_demandforecast_api;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
 ON core.inventory_snapshot FROM tttv_demandforecast_api;
""")


def downgrade() -> None:
    op.execute("DROP TABLE core.inventory_snapshot")
