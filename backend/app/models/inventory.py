from sqlalchemy import (
    Column,
    Integer,
    DateTime,
    String,
    Float,
    Boolean,
    ForeignKey,
    func
)
from sqlalchemy.orm import relationship
from ..database import base

# ============================================================
# Inventory Log
# ============================================================

class InventoryLog(base):
    __tablename__ = "inventory_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False
    )

    timestamp = Column(
        DateTime,
        server_default=func.now()
    )

    stock_in = Column(
        Integer,
        default=0
    )

    stock_out = Column(
        Integer,
        default=0
    )

    closing_stock = Column(
        Integer,
        nullable=False
    )

    reason = Column(
        String,
        nullable=False
    )

    # Many Inventory Logs -> One Product
    product = relationship(
        "Product",
        back_populates="inventory_logs"
    )
