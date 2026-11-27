"""
Historical Retail Sales Data Seeder
Populates comprehensive, realistic multi-year daily sales records for all 21 products.
Models true retail characteristics: weekly seasonality, holiday surges, trends, and intermittent zero days.
"""

import sys
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.products import Product
from app.models.sales import Sale

def seed_historical_sales(days: int = 700):
    db = SessionLocal()
    products = db.query(Product).all()
    if not products:
        print("No products found in database! Please run seed_data.py first.")
        db.close()
        return

    existing_sales_count = db.query(Sale).count()
    if existing_sales_count > 500:
        print(f"Database already contains {existing_sales_count} sales records. Skipping seed.")
        db.close()
        return

    print(f"Generating realistic {days}-day sales history across {len(products)} products...")

    start_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    new_sales = []

    random.seed(42)

    for product in products:
        # Base daily demand depends on product category & price
        price = float(product.selling_price or 1000.0)
        if price > 50000:
            base_demand = 1.2
            std_demand = 0.8
        elif price > 10000:
            base_demand = 2.5
            std_demand = 1.2
        else:
            base_demand = 5.0
            std_demand = 2.0

        for day_offset in range(days):
            current_date = start_date + timedelta(days=day_offset)
            dow = current_date.weekday()
            month = current_date.month

            # Weekly seasonality: Mon-Wed and Sat higher
            dow_factor = 1.25 if dow in [1, 2, 5] else (0.85 if dow == 6 else 1.0)
            # Monthly / Festive seasonality: Q4 holiday spikes
            month_factor = 1.35 if month in [10, 11, 12] else (0.9 if month in [1, 2] else 1.0)
            # Upward trend
            trend_factor = 1.0 + (day_offset / days) * 0.15

            expected = base_demand * dow_factor * month_factor * trend_factor
            qty = max(0, int(round(random.gauss(expected, std_demand))))

            if qty > 0:
                revenue = round(qty * price, 2)
                sale = Sale(
                    business_id=product.business_id,
                    product_id=product.id,
                    quantity_sold=qty,
                    selling_price=price,
                    revenue=revenue,
                    sales_date=current_date
                )
                new_sales.append(sale)

                if len(new_sales) >= 2000:
                    db.bulk_save_objects(new_sales)
                    db.commit()
                    new_sales = []

    if new_sales:
        db.bulk_save_objects(new_sales)
        db.commit()

    total_sales = db.query(Sale).count()
    print(f"Historical sales seeding completed successfully! Total sales records in DB: {total_sales}")
    db.close()

if __name__ == "__main__":
    seed_historical_sales(700)
