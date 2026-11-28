from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.inventory import InventoryLog
from ..models.products import Product
from ..models.purchase_order import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
)
from ..models.sales import Sale


def _normalize_cutoff_dt(as_of_date: Optional[datetime | date]) -> Optional[datetime]:
    if as_of_date is None:
        return None
    if isinstance(as_of_date, datetime):
        dt = as_of_date.astimezone(timezone.utc).replace(tzinfo=None) if as_of_date.tzinfo else as_of_date
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return datetime(as_of_date.year, as_of_date.month, as_of_date.day, 23, 59, 59, 999999)


class DataIngestionService:
    """
    Tenant-isolated historical demand, receipt, stock-ledger, and category loader.
    Strictly scopes all reads by business_id, excludes CANCELLED sales, tracks
    synthetic-record provenance, and supports deterministic cutoff dates.
    """

    @staticmethod
    def _resolve_business_id(
        db: Session,
        business_id: Optional[int],
        product_id: Optional[int],
    ) -> Optional[int]:
        if business_id is not None:
            return business_id
        if product_id is not None:
            prod = db.query(Product.business_id).filter(Product.id == product_id).first()
            if prod is not None:
                return prod[0]
        return None

    @classmethod
    def load_from_database(
        cls,
        db: Session,
        business_id: Optional[int] = None,
        product_id: Optional[int] = None,
        as_of_date: Optional[datetime | date] = None,
        include_cancelled: bool = False,
    ) -> pd.DataFrame:
        """
        Load tenant-scoped sales history joined with product metadata and provenance.
        Excludes CANCELLED sales unless explicitly requested.
        """
        resolved_biz_id = cls._resolve_business_id(db, business_id, product_id)
        if resolved_biz_id is None:
            raise ValueError("business_id (or a valid product_id) is required for tenant-isolated ingestion.")

        query = (
            db.query(
                Sale.id.label("sale_id"),
                Sale.business_id.label("business_id"),
                Sale.sales_date.label("date"),
                Sale.product_id.label("product_id"),
                Product.sku.label("sku"),
                Product.name.label("product_name"),
                Product.category.label("category"),
                Product.unit.label("unit"),
                Sale.quantity_sold.label("quantity"),
                Sale.selling_price.label("unit_price"),
                Sale.revenue.label("total_amount"),
                Sale.status.label("status"),
                Sale.is_synthetic.label("is_synthetic"),
            )
            .join(Product, Sale.product_id == Product.id)
            .filter(
                Sale.business_id == resolved_biz_id,
                Product.business_id == resolved_biz_id,
            )
        )

        if product_id is not None:
            query = query.filter(Sale.product_id == product_id)

        if not include_cancelled:
            query = query.filter(func.upper(func.coalesce(Sale.status, "COMPLETED")) != "CANCELLED")

        cutoff_dt = _normalize_cutoff_dt(as_of_date)
        if cutoff_dt is not None:
            query = query.filter(Sale.sales_date <= cutoff_dt)

        rows = query.order_by(Sale.sales_date.asc(), Sale.id.asc()).all()
        columns = [
            "sale_id",
            "business_id",
            "date",
            "product_id",
            "sku",
            "product_name",
            "category",
            "unit",
            "quantity",
            "unit_price",
            "total_amount",
            "status",
            "is_synthetic",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0).clip(lower=0.0)
        df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0.0).clip(lower=0.0)
        df["is_synthetic"] = df["is_synthetic"].fillna(False).astype(bool)
        return df

    @classmethod
    def load_stock_ledger_for_product(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
        as_of_date: Optional[datetime | date] = None,
    ) -> pd.DataFrame:
        """
        Load tenant-scoped daily stock ledger closing balances for stockout-day inference.
        """
        query = db.query(
            InventoryLog.timestamp.label("timestamp"),
            InventoryLog.closing_stock.label("closing_stock"),
            InventoryLog.stock_in.label("stock_in"),
            InventoryLog.stock_out.label("stock_out"),
            InventoryLog.movement_type.label("movement_type"),
            InventoryLog.is_synthetic.label("is_synthetic"),
        ).filter(
            InventoryLog.business_id == business_id,
            InventoryLog.product_id == product_id,
        )
        cutoff_dt = _normalize_cutoff_dt(as_of_date)
        if cutoff_dt is not None:
            query = query.filter(InventoryLog.timestamp <= cutoff_dt)

        rows = query.order_by(InventoryLog.timestamp.asc(), InventoryLog.id.asc()).all()
        columns = ["timestamp", "closing_stock", "stock_in", "stock_out", "movement_type", "is_synthetic"]
        if not rows:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["is_synthetic"] = df["is_synthetic"].fillna(False).astype(bool)
        return df.dropna(subset=["timestamp"])

    @classmethod
    def load_purchase_receipt_context(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
        as_of_date: Optional[datetime | date] = None,
    ) -> pd.DataFrame:
        """
        Load tenant-scoped Goods Receipt & PO cost history for replenishments up to cutoff date.
        """
        query = (
            db.query(
                GoodsReceipt.received_at.label("date"),
                GoodsReceiptItem.quantity_received.label("received_quantity"),
                PurchaseOrderItem.unit_cost.label("unit_cost"),
                PurchaseOrder.supplier_id.label("supplier_id"),
                GoodsReceipt.is_synthetic.label("is_synthetic"),
            )
            .join(GoodsReceipt, GoodsReceiptItem.goods_receipt_id == GoodsReceipt.id)
            .join(PurchaseOrderItem, GoodsReceiptItem.purchase_order_item_id == PurchaseOrderItem.id)
            .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.purchase_order_id)
            .filter(
                GoodsReceipt.business_id == business_id,
                PurchaseOrder.business_id == business_id,
                GoodsReceiptItem.product_id == product_id,
            )
        )
        cutoff_dt = _normalize_cutoff_dt(as_of_date)
        if cutoff_dt is not None:
            query = query.filter(GoodsReceipt.received_at <= cutoff_dt)

        rows = query.order_by(GoodsReceipt.received_at.asc(), GoodsReceiptItem.id.asc()).all()
        columns = ["date", "received_quantity", "unit_cost", "supplier_id", "is_synthetic"]
        if not rows:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["received_quantity"] = pd.to_numeric(df["received_quantity"], errors="coerce").fillna(0.0).clip(lower=0.0)
        df["unit_cost"] = pd.to_numeric(df["unit_cost"], errors="coerce").fillna(0.0).clip(lower=0.0)
        df["is_synthetic"] = df["is_synthetic"].fillna(False).astype(bool)
        return df

    @classmethod
    def load_category_benchmark_context(
        cls,
        db: Session,
        business_id: int,
        category: Optional[str],
        exclude_product_id: Optional[int] = None,
        as_of_date: Optional[datetime | date] = None,
    ) -> Dict[str, Any]:
        """
        Compute Level-2 category demand patterns strictly inside a single workspace (business_id).
        Never accesses any sibling/foreign workspace data.
        """
        norm_cat = (category or "").strip()
        if not norm_cat:
            return {"available": False, "reason": "Product category not specified."}

        query = (
            db.query(
                Sale.product_id,
                Sale.sales_date,
                Sale.quantity_sold,
            )
            .join(Product, Sale.product_id == Product.id)
            .filter(
                Sale.business_id == business_id,
                Product.business_id == business_id,
                Product.category == norm_cat,
                Product.is_active.is_(True),
                func.upper(func.coalesce(Sale.status, "COMPLETED")) != "CANCELLED",
            )
        )
        if exclude_product_id is not None:
            query = query.filter(Product.id != exclude_product_id)

        cutoff_dt = _normalize_cutoff_dt(as_of_date)
        if cutoff_dt is not None:
            query = query.filter(Sale.sales_date <= cutoff_dt)

        rows = query.order_by(Sale.sales_date.asc()).all()
        if not rows:
            return {
                "available": False,
                "category": norm_cat,
                "reason": "No peer sales records in this category within workspace.",
            }

        df = pd.DataFrame(rows, columns=["product_id", "date", "quantity"])
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df = df.dropna(subset=["date"])
        if df.empty:
            return {"available": False, "category": norm_cat, "reason": "No dated category observations."}

        peer_count = df["product_id"].nunique()
        daily_by_sku = df.groupby(["product_id", "date"], as_index=False)["quantity"].sum()
        span_days = max(1, int((daily_by_sku["date"].max() - daily_by_sku["date"].min()).days) + 1)

        if peer_count < 1 or len(daily_by_sku) < 7:
            return {
                "available": False,
                "category": norm_cat,
                "peer_products": peer_count,
                "reason": "Insufficient category observations in workspace for Level-2 prior.",
            }

        sku_avgs = daily_by_sku.groupby("product_id")["quantity"].sum() / float(span_days)
        mean_daily = float(sku_avgs.mean())
        median_daily = float(sku_avgs.median())

        daily_by_sku["dow"] = daily_by_sku["date"].dt.day_of_week
        dow_means = daily_by_sku.groupby("dow")["quantity"].mean()
        overall_nonzero_mean = float(daily_by_sku["quantity"].mean())
        dow_factors: Dict[int, float] = {}
        if overall_nonzero_mean > 0:
            for dow in range(7):
                val = float(dow_means.get(dow, overall_nonzero_mean))
                dow_factors[dow] = round(max(0.4, min(2.0, val / overall_nonzero_mean)), 3)
        else:
            dow_factors = {d: 1.0 for d in range(7)}

        return {
            "available": mean_daily > 0,
            "category": norm_cat,
            "peer_products": peer_count,
            "observed_category_days": len(daily_by_sku),
            "span_days": span_days,
            "mean_daily_demand": round(mean_daily, 4),
            "median_daily_demand": round(median_daily, 4),
            "dow_factors": dow_factors,
            "std_dev": round(float(np.std(sku_avgs.values)) if len(sku_avgs) > 1 else mean_daily * 0.35, 4),
        }
