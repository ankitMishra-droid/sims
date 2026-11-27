from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship
from ..database import base


class InventoryLog(base):
    __tablename__ = "inventory_logs"
    __table_args__ = (
        Index("ix_inventory_logs_biz_prod_ts", "business_id", "product_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    movement_type = Column(String(30), nullable=False, default="STOCK_ADJUSTMENT")
    stock_in = Column(Integer, nullable=False, default=0)
    stock_out = Column(Integer, nullable=False, default=0)
    previous_stock = Column(Integer, nullable=False, default=0)
    closing_stock = Column(Integer, nullable=False)
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(Integer, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(String, nullable=False)

    product = relationship("Product", back_populates="inventory_logs")

    @property
    def quantity(self) -> int:
        return int(self.stock_in or 0) - int(self.stock_out or 0)

    @property
    def resulting_stock(self) -> int:
        return int(self.closing_stock)
