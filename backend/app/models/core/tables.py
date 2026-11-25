from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Double, ForeignKey, ForeignKeyConstraint, Integer, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CoreInventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("unique_id", "warehouse", name="uq_core_inventory_id_warehouse"),
        CheckConstraint("btrim(unique_id) <> ''", name="ck_core_inventory_unique_id_nonempty"),
        CheckConstraint("btrim(warehouse) <> ''", name="ck_core_inventory_warehouse_nonempty"),
        {"schema": "core"},
    )
    unique_id: Mapped[str] = mapped_column(Text, primary_key=True)
    warehouse: Mapped[str] = mapped_column(Text, nullable=False)
    product_unique_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    name: Mapped[Optional[str]] = mapped_column(Text)
    l1_category_name_en: Mapped[Optional[str]] = mapped_column(Text)
    l2_category_name_en: Mapped[Optional[str]] = mapped_column(Text)
    l3_category_name_en: Mapped[Optional[str]] = mapped_column(Text)
    l4_category_name_en: Mapped[Optional[str]] = mapped_column(Text)


class CoreInventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    __table_args__ = (
        CheckConstraint("current_stock >= 0", name="ck_inventory_snapshot_current_stock"),
        CheckConstraint("lead_time_days >= 0", name="ck_inventory_snapshot_lead_time"),
        CheckConstraint(
            "scenario_group IN ('In Stock', 'Monitor', 'Reorder', 'Critical', 'Deadstock')",
            name="ck_inventory_snapshot_scenario_group",
        ),
        {"schema": "core"},
    )
    unique_id: Mapped[str] = mapped_column(Text, ForeignKey("core.inventory.unique_id"), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    current_stock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock: Mapped[float] = mapped_column(Double, nullable=False)
    baseline_avg_daily_sales: Mapped[float] = mapped_column(Double, nullable=False)
    baseline_reorder_point: Mapped[float] = mapped_column(Double, nullable=False)
    scenario_group: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class CoreCalendar(Base):
    __tablename__ = "calendar"
    __table_args__ = (
        CheckConstraint("btrim(warehouse) <> ''", name="ck_core_calendar_warehouse_nonempty"),
        CheckConstraint("holiday IN (0, 1)", name="ck_core_calendar_holiday_flag"),
        CheckConstraint("shops_closed IN (0, 1)", name="ck_core_calendar_shops_closed_flag"),
        CheckConstraint("winter_school_holidays IN (0, 1)", name="ck_core_calendar_winter_school_flag"),
        CheckConstraint("school_holidays IN (0, 1)", name="ck_core_calendar_school_flag"),
        {"schema": "core"},
    )
    warehouse: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    holiday_name: Mapped[Optional[str]] = mapped_column(Text)
    holiday: Mapped[Optional[int]] = mapped_column(SmallInteger)
    shops_closed: Mapped[Optional[int]] = mapped_column(SmallInteger)
    winter_school_holidays: Mapped[Optional[int]] = mapped_column(SmallInteger)
    school_holidays: Mapped[Optional[int]] = mapped_column(SmallInteger)


class CoreSalesDaily(Base):
    __tablename__ = "sales_daily"
    __table_args__ = (
        ForeignKeyConstraint(["unique_id", "warehouse"], ["core.inventory.unique_id", "core.inventory.warehouse"], name="fk_core_sales_inventory"),
        ForeignKeyConstraint(["warehouse", "date"], ["core.calendar.warehouse", "core.calendar.date"], name="fk_core_sales_calendar"),
        CheckConstraint("btrim(unique_id) <> ''", name="ck_core_sales_unique_id_nonempty"),
        CheckConstraint("btrim(warehouse) <> ''", name="ck_core_sales_warehouse_nonempty"),
        {"schema": "core"},
    )
    unique_id: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    warehouse: Mapped[str] = mapped_column(Text, nullable=False)
    sales: Mapped[Optional[float]] = mapped_column(Double)
    total_orders: Mapped[Optional[float]] = mapped_column(Double)
    sell_price_main: Mapped[Optional[float]] = mapped_column(Double)
    availability: Mapped[Optional[float]] = mapped_column(Double)
    type_0_discount: Mapped[Optional[float]] = mapped_column(Double)
    type_1_discount: Mapped[Optional[float]] = mapped_column(Double)
    type_2_discount: Mapped[Optional[float]] = mapped_column(Double)
    type_3_discount: Mapped[Optional[float]] = mapped_column(Double)
    type_4_discount: Mapped[Optional[float]] = mapped_column(Double)
    type_5_discount: Mapped[Optional[float]] = mapped_column(Double)
    type_6_discount: Mapped[Optional[float]] = mapped_column(Double)


class CoreSeriesWeight(Base):
    __tablename__ = "series_weights"
    __table_args__ = (
        CheckConstraint("btrim(unique_id) <> ''", name="ck_core_weights_unique_id_nonempty"),
        CheckConstraint("weight > 0 AND weight < 'Infinity'::double precision", name="ck_core_weights_positive_finite"),
        {"schema": "core"},
    )
    unique_id: Mapped[str] = mapped_column(Text, ForeignKey("core.inventory.unique_id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Double, nullable=False)
