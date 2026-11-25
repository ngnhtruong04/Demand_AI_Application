from datetime import date
from typing import Optional

from sqlalchemy import Date, Double, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawSalesTrain(Base):
    __tablename__ = "sales_train"
    __table_args__ = {"schema": "raw"}

    unique_id: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    warehouse: Mapped[str] = mapped_column(Text, primary_key=True)
    total_orders: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sales: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sell_price_main: Mapped[float] = mapped_column(Double, nullable=False)
    availability: Mapped[float] = mapped_column(Double, nullable=False)
    type_0_discount: Mapped[float] = mapped_column(Double, nullable=False)
    type_1_discount: Mapped[float] = mapped_column(Double, nullable=False)
    type_2_discount: Mapped[float] = mapped_column(Double, nullable=False)
    type_3_discount: Mapped[float] = mapped_column(Double, nullable=False)
    type_4_discount: Mapped[float] = mapped_column(Double, nullable=False)
    type_5_discount: Mapped[float] = mapped_column(Double, nullable=False)
    type_6_discount: Mapped[float] = mapped_column(Double, nullable=False)
