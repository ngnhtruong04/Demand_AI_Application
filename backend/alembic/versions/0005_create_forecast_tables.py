"""Create forecast persistence tables in core schema.

Revision ID: 0005_create_forecast_tables
Revises: 0004_inventory_snapshot
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_create_forecast_tables"
down_revision: Union[str, None] = "0004_inventory_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE core.forecast_runs (
    run_id UUID PRIMARY KEY,
    model_version TEXT NOT NULL,
    horizon_days INTEGER NOT NULL DEFAULT 14,
    forecast_start_date DATE NOT NULL,
    forecast_end_date DATE NOT NULL,
    total_items INTEGER NOT NULL,
    total_predicted_demand DOUBLE PRECISION NOT NULL,
    is_latest BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_forecast_runs_horizon_days CHECK (horizon_days > 0),
    CONSTRAINT ck_forecast_runs_dates CHECK (forecast_end_date >= forecast_start_date)
);

CREATE UNIQUE INDEX uq_forecast_runs_latest ON core.forecast_runs (is_latest) WHERE is_latest = TRUE;
CREATE INDEX ix_forecast_runs_created_at ON core.forecast_runs (created_at DESC);

CREATE TABLE core.forecast_item_summary (
    run_id UUID NOT NULL REFERENCES core.forecast_runs (run_id) ON DELETE CASCADE,
    unique_id TEXT NOT NULL REFERENCES core.inventory (unique_id),
    warehouse TEXT NOT NULL,
    forecast_14d DOUBLE PRECISION NOT NULL,
    current_stock BIGINT NOT NULL,
    baseline_reorder_point DOUBLE PRECISION NOT NULL,
    safety_stock DOUBLE PRECISION NOT NULL,
    lead_time_days INTEGER NOT NULL,
    days_of_supply DOUBLE PRECISION,
    scenario_group TEXT NOT NULL,
    drivers_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb,
    all_features_shap JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_core_forecast_item_summary PRIMARY KEY (run_id, unique_id),
    CONSTRAINT ck_forecast_item_summary_current_stock CHECK (current_stock >= 0),
    CONSTRAINT ck_forecast_item_summary_scenario CHECK (
        scenario_group IN ('In Stock', 'Monitor', 'Reorder', 'Critical', 'Deadstock')
    )
);

CREATE INDEX ix_core_forecast_item_summary_warehouse ON core.forecast_item_summary (warehouse);
CREATE INDEX ix_core_forecast_item_summary_scenario ON core.forecast_item_summary (scenario_group);

CREATE TABLE core.forecast_daily_points (
    run_id UUID NOT NULL REFERENCES core.forecast_runs (run_id) ON DELETE CASCADE,
    unique_id TEXT NOT NULL REFERENCES core.inventory (unique_id),
    date DATE NOT NULL,
    horizon_day SMALLINT NOT NULL,
    predicted_sales DOUBLE PRECISION NOT NULL,
    all_features_shap JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT pk_core_forecast_daily_points PRIMARY KEY (run_id, unique_id, date),
    CONSTRAINT ck_forecast_daily_points_horizon CHECK (horizon_day >= 1 AND horizon_day <= 365)
);

CREATE INDEX ix_core_forecast_daily_points_unique_id ON core.forecast_daily_points (unique_id);
CREATE INDEX ix_core_forecast_daily_points_date ON core.forecast_daily_points (date);

GRANT SELECT, INSERT, UPDATE, DELETE ON core.forecast_runs TO tttv_demandforecast_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.forecast_item_summary TO tttv_demandforecast_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.forecast_daily_points TO tttv_demandforecast_api;
""")


def downgrade() -> None:
    op.execute("""
REVOKE ALL PRIVILEGES ON core.forecast_daily_points FROM tttv_demandforecast_api;
REVOKE ALL PRIVILEGES ON core.forecast_item_summary FROM tttv_demandforecast_api;
REVOKE ALL PRIVILEGES ON core.forecast_runs FROM tttv_demandforecast_api;
DROP TABLE IF EXISTS core.forecast_daily_points CASCADE;
DROP TABLE IF EXISTS core.forecast_item_summary CASCADE;
DROP TABLE IF EXISTS core.forecast_runs CASCADE;
""")
