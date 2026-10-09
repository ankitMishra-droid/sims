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

# sales model
class Sale(base):
    __tablename__ = "sales"

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

    sales_date = Column(
        DateTime,
        server_default=func.now()
    )

    quantity_sold = Column(
        Integer,
        nullable=False
    )

    selling_price = Column(
        Float,
        nullable=False
    )

    revenue = Column(
        Float,
        nullable=False
    )

    # Many Sales -> One Product
    product = relationship(
        "Product",
        back_populates="sales"
    )

