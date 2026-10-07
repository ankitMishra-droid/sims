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
from .database import base


# ============================================================
# Supplier
# ============================================================

class Supplier(base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    #This lets you identify the agreement under which you're purchasing. A supplier contract number/reference
    contract = Column(String, nullable=False)
    name = Column(String, nullable=False)
    #How many days does this supplier normally take to deliver an order? it tells us when should i order more stock
    lead_time_days = Column(Integer, default=7) # Lead Time Days=Stock Available Date−Purchase Order Date

    # One Supplier -> Many Products
    products = relationship(
        "Product",
        back_populates="supplier"
    )

    # One Supplier -> Many Purchase Orders
    purchase_orders = relationship(
        "PurchaseOrder",
        back_populates="supplier"
    )


# ============================================================
# Product
# ============================================================

class Product(base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    sku = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    name = Column(String, nullable=False)
    category = Column(String, nullable=False)

    unit = Column(
        String,
        default="piece"
    )

    cost_price = Column(
        Float,
        default=0
    )

    selling_price = Column(
        Float,
        default=0
    )

    current_stock = Column(
        Integer,
        default=0
    )

    # Reorder Point=(Average Daily Demand×Lead Time Days)+Safety Stock
    reorder_level = Column(
        Integer,
        default=10
    )

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=True
    )

    is_active = Column(
        Boolean, default=True
    )

    # Many Products -> One Supplier
    supplier = relationship(
        "Supplier",
        back_populates="products"
    )

    # One Product -> Many Sales
    sales = relationship(
        "Sale",
        back_populates="product"
    )

    # One Product -> Many Inventory Logs
    inventory_logs = relationship(
        "InventoryLog",
        back_populates="product"
    )

    # One Product -> Many Purchase Order Items
    purchase_order_items = relationship(
        "PurchaseOrderItems",
        back_populates="product"
    )


# ============================================================
# Sale
# ============================================================

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


# ============================================================
# Purchase Order
# ============================================================

class PurchaseOrder(base):
    __tablename__ = "purchase_orders"

    po_id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=False
    )

    order_date = Column(
        DateTime,
        server_default=func.now()
    )

    expected_delivery_date = Column(
        DateTime,
        nullable=True
    )

    status = Column(
        String,
        default="pending"
    )

    # Many Purchase Orders -> One Supplier
    supplier = relationship(
        "Supplier",
        back_populates="purchase_orders"
    )

    # One Purchase Order -> Many Purchase Order Items
    items = relationship(
        "PurchaseOrderItems",
        back_populates="purchase_order"
    )


# ============================================================
# Purchase Order Items
# ============================================================

class PurchaseOrderItems(base):
    __tablename__ = "purchase_order_items"

    po_item_id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    po_id = Column(
        Integer,
        ForeignKey("purchase_orders.po_id"),
        nullable=False
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False
    )

    ordered_quantity = Column(
        Integer,
        default=0
    )

    received_quantity = Column(
        Integer,
        default=0
    )

    # Many Purchase Order Items -> One Product
    product = relationship(
        "Product",
        back_populates="purchase_order_items"
    )

    # Many Purchase Order Items -> One Purchase Order
    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="items"
    )


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