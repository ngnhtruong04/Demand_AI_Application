from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CoreForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint("horizon_days > 0", name="ck_forecast_runs_horizon_days"),
        CheckConstraint("forecast_end_date >= forecast_start_date", name="ck_forecast_runs_dates"),
        {"schema": "core"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    forecast_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    forecast_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=5390)
    total_predicted_demand: Mapped[float] = mapped_column(Double, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    item_summaries: Mapped[list[CoreForecastItemSummary]] = relationship(
        "CoreForecastItemSummary", back_populates="run", cascade="all, delete-orphan"
    )
    daily_points: Mapped[list[CoreForecastDailyPoint]] = relationship(
        "CoreForecastDailyPoint", back_populates="run", cascade="all, delete-orphan"
    )


class CoreForecastItemSummary(Base):
    __tablename__ = "forecast_item_summary"
    __table_args__ = (
        CheckConstraint("current_stock >= 0", name="ck_forecast_item_summary_current_stock"),
        CheckConstraint(
            "scenario_group IN ('In Stock', 'Monitor', 'Reorder', 'Critical', 'Deadstock')",
            name="ck_forecast_item_summary_scenario",
        ),
        {"schema": "core"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.forecast_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    unique_id: Mapped[str] = mapped_column(
        Text, ForeignKey("core.inventory.unique_id"), primary_key=True
    )
    warehouse: Mapped[str] = mapped_column(Text, nullable=False)
    forecast_14d: Mapped[float] = mapped_column(Double, nullable=False)
    current_stock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    baseline_reorder_point: Mapped[float] = mapped_column(Double, nullable=False)
    safety_stock: Mapped[float] = mapped_column(Double, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    days_of_supply: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    scenario_group: Mapped[str] = mapped_column(Text, nullable=False)
    drivers_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    all_features_shap: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped[CoreForecastRun] = relationship("CoreForecastRun", back_populates="item_summaries")


class CoreForecastDailyPoint(Base):
    __tablename__ = "forecast_daily_points"
    __table_args__ = (
        CheckConstraint("horizon_day >= 1 AND horizon_day <= 365", name="ck_forecast_daily_points_horizon"),
        {"schema": "core"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.forecast_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    unique_id: Mapped[str] = mapped_column(
        Text, ForeignKey("core.inventory.unique_id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    horizon_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    predicted_sales: Mapped[float] = mapped_column(Double, nullable=False)
    all_features_shap: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")

    run: Mapped[CoreForecastRun] = relationship("CoreForecastRun", back_populates="daily_points")
