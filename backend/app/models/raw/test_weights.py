from sqlalchemy import Double, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawTestWeights(Base):
    __tablename__ = "test_weights"
    __table_args__ = {"schema": "raw"}

    unique_id: Mapped[str] = mapped_column(Text, primary_key=True)
    weight: Mapped[float] = mapped_column(Double, nullable=False)
