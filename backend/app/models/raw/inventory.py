from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawInventory(Base):
    __tablename__ = "inventory"
    __table_args__ = {"schema": "raw"}

    unique_id: Mapped[str] = mapped_column(Text, primary_key=True)
    product_unique_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    L1_category_name_en: Mapped[str] = mapped_column(Text, nullable=False)
    L2_category_name_en: Mapped[str] = mapped_column(Text, nullable=False)
    L3_category_name_en: Mapped[str] = mapped_column(Text, nullable=False)
    L4_category_name_en: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse: Mapped[str] = mapped_column(Text, primary_key=True)
