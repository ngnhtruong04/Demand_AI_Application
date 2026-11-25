"""Create secondary indexes on raw tables

Revision ID: 0002_raw_indexes
Revises: 0001_raw_schema
Create Date: 2026-09-07 16:11:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_raw_indexes"
down_revision: Union[str, None] = "0001_raw_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Secondary indexes on raw tables
    op.create_index(
        "idx_sales_train_item_warehouse_date",
        "sales_train",
        ["unique_id", "warehouse", "date"],
        schema="raw",
    )
    op.create_index(
        "idx_sales_train_warehouse_date",
        "sales_train",
        ["warehouse", "date"],
        schema="raw",
    )
    op.create_index(
        "idx_calendar_warehouse_date",
        "calendar",
        ["warehouse", "date"],
        schema="raw",
    )
    op.create_index(
        "idx_inventory_item_warehouse",
        "inventory",
        ["unique_id", "warehouse"],
        schema="raw",
    )


def downgrade() -> None:
    op.drop_index("idx_inventory_item_warehouse", table_name="inventory", schema="raw")
    op.drop_index("idx_calendar_warehouse_date", table_name="calendar", schema="raw")
    op.drop_index("idx_sales_train_warehouse_date", table_name="sales_train", schema="raw")
    op.drop_index("idx_sales_train_item_warehouse_date", table_name="sales_train", schema="raw")
