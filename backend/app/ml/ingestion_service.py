import os
import pandas as pd
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from ..models.sales import Sale
from ..models.products import Product

class DataIngestionService:
    """
    Ingests and loads raw sales transaction records from the database or external CSV files.
    Standardizes output schema to [date, product_id, sku, quantity, unit_price, total_amount].
    """

    @staticmethod
    def load_from_database(db: Session, product_id: Optional[int] = None) -> pd.DataFrame:
        """
        Extracts sales transactions directly from the database and returns a standardized DataFrame.
        """
        query = db.query(
            Sale.sales_date.label("date"),
            Sale.product_id,
            Product.sku,
            Sale.quantity_sold.label("quantity"),
            Sale.selling_price.label("unit_price"),
            Sale.revenue.label("total_amount")
        ).join(Product, Sale.product_id == Product.id)

        if product_id is not None:
            query = query.filter(Sale.product_id == product_id)

        records = query.all()
        if not records:
            return pd.DataFrame(columns=["date", "product_id", "sku", "quantity", "unit_price", "total_amount"])

        df = pd.DataFrame(records, columns=["date", "product_id", "sku", "quantity", "unit_price", "total_amount"])
        df["date"] = pd.to_datetime(df["date"])
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
        return df

    @staticmethod
    def load_from_csv(file_path: str) -> pd.DataFrame:
        """
        Ingests historical sales records from a CSV file.
        Expects columns: date (or sales_date), product_id (or sku), quantity (or quantity_sold).
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Sales dataset file not found at: {file_path}")

        df = pd.read_csv(file_path)
        df.columns = [col.strip().lower() for col in df.columns]

        date_col = next((c for c in ["date", "sale_date", "sales_date", "timestamp"] if c in df.columns), None)
        if not date_col:
            raise ValueError("CSV must contain a 'date' or 'sales_date' column.")
        df["date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["date"])

        qty_col = next((c for c in ["quantity", "quantity_sold", "qty", "demand"] if c in df.columns), None)
        if not qty_col:
            raise ValueError("CSV must contain a 'quantity' or 'quantity_sold' column.")
        df["quantity"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)

        return df
