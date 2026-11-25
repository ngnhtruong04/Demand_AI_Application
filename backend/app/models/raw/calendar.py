from datetime import date
from typing import Optional

from sqlalchemy import Date, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawCalendar(Base):
    __tablename__ = "calendar"
    __table_args__ = {"schema": "raw"}

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    holiday_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    holiday: Mapped[int] = mapped_column(Integer, nullable=False)
    shops_closed: Mapped[int] = mapped_column(Integer, nullable=False)
    winter_school_holidays: Mapped[int] = mapped_column(Integer, nullable=False)
    school_holidays: Mapped[int] = mapped_column(Integer, nullable=False)
    warehouse: Mapped[str] = mapped_column(Text, primary_key=True)
