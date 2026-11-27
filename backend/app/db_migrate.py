from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .database import base, engine


def _existing_columns(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {col["name"] for col in insp.get_columns(table_name)}


def _add_column_if_missing(conn, insp, table_name: str, col_name: str, ddl_type: str) -> None:
    cols = _existing_columns(insp, table_name)
    if col_name not in cols:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {ddl_type}"))


def ensure_schema_and_backfill(target_engine: Engine = engine) -> None:
    """Safely create missing tables/columns/indexes and backfill default tenant ownership."""
    from . import models  # noqa: F401 - register metadata

    base.metadata.create_all(bind=target_engine)

    with target_engine.begin() as conn:
        insp = inspect(conn)

        _add_column_if_missing(conn, insp, "users", "active_business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "users", "preferred_language", "VARCHAR(10) DEFAULT 'en'")
        _add_column_if_missing(conn, insp, "users", "token_version", "INTEGER DEFAULT 1")

        _add_column_if_missing(conn, insp, "businesses", "default_language", "VARCHAR(10) DEFAULT 'en'")
        _add_column_if_missing(conn, insp, "businesses", "contact_email", "VARCHAR(120)")
        _add_column_if_missing(conn, insp, "businesses", "contact_phone", "VARCHAR(30)")
        _add_column_if_missing(conn, insp, "businesses", "address", "VARCHAR(255)")
        _add_column_if_missing(conn, insp, "businesses", "gstin_or_tax_id", "VARCHAR(50)")
        _add_column_if_missing(conn, insp, "businesses", "currency", "VARCHAR(10) DEFAULT 'INR'")
        _add_column_if_missing(conn, insp, "businesses", "low_stock_threshold_default", "INTEGER DEFAULT 10")
        _add_column_if_missing(conn, insp, "businesses", "onboarding_completed", "BOOLEAN DEFAULT 0")

        _add_column_if_missing(conn, insp, "suppliers", "business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "suppliers", "linked_business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "suppliers", "created_at", "DATETIME")
        _add_column_if_missing(conn, insp, "suppliers", "updated_at", "DATETIME")

        _add_column_if_missing(conn, insp, "products", "business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "products", "created_at", "DATETIME")
        _add_column_if_missing(conn, insp, "products", "updated_at", "DATETIME")

        _add_column_if_missing(conn, insp, "sales", "business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "sales", "status", "VARCHAR(20) DEFAULT 'COMPLETED'")
        _add_column_if_missing(conn, insp, "sales", "created_by", "INTEGER")
        _add_column_if_missing(conn, insp, "sales", "idempotency_key", "VARCHAR(120)")
        _add_column_if_missing(conn, insp, "sales", "notes", "TEXT")

        _add_column_if_missing(conn, insp, "inventory_logs", "business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "inventory_logs", "movement_type", "VARCHAR(30)")
        _add_column_if_missing(conn, insp, "inventory_logs", "previous_stock", "INTEGER")
        _add_column_if_missing(conn, insp, "inventory_logs", "reference_type", "VARCHAR(50)")
        _add_column_if_missing(conn, insp, "inventory_logs", "reference_id", "INTEGER")
        _add_column_if_missing(conn, insp, "inventory_logs", "user_id", "INTEGER")

        _add_column_if_missing(conn, insp, "purchase_orders", "business_id", "INTEGER")
        _add_column_if_missing(conn, insp, "purchase_orders", "order_number", "VARCHAR(40)")
        _add_column_if_missing(conn, insp, "purchase_orders", "total_amount", "NUMERIC(12, 2) DEFAULT 0")
        _add_column_if_missing(conn, insp, "purchase_orders", "created_by", "INTEGER")
        _add_column_if_missing(conn, insp, "purchase_orders", "sent_at", "DATETIME")
        _add_column_if_missing(conn, insp, "purchase_orders", "received_at", "DATETIME")
        _add_column_if_missing(conn, insp, "purchase_orders", "cancelled_at", "DATETIME")
        _add_column_if_missing(conn, insp, "purchase_orders", "updated_at", "DATETIME")
        _add_column_if_missing(conn, insp, "purchase_orders", "shared_with_supplier", "BOOLEAN DEFAULT 0")
        _add_column_if_missing(conn, insp, "purchase_orders", "shared_at", "DATETIME")
        _add_column_if_missing(conn, insp, "purchase_orders", "supplier_status", "VARCHAR(40)")
        _add_column_if_missing(conn, insp, "purchase_orders", "supplier_notes", "TEXT")
        _add_column_if_missing(conn, insp, "purchase_orders", "supplier_acknowledged_at", "DATETIME")
        _add_column_if_missing(conn, insp, "purchase_orders", "supplier_dispatched_at", "DATETIME")

        # Backfill default workspace for pre-existing single-tenant data before creating unique indexes
        biz_count = conn.execute(text("SELECT COUNT(*) FROM businesses")).scalar() or 0
        default_biz_id = None
        if biz_count == 0:
            user_rows = conn.execute(text("SELECT id, role FROM users ORDER BY id ASC")).fetchall()
            if user_rows:
                owner_id = next((r[0] for r in user_rows if r[1] == "admin"), user_rows[0][0])
                conn.execute(
                    text(
                        "INSERT INTO businesses (name, business_type, owner_user_id, allow_negative_stock, is_active) "
                        "VALUES (:name, :btype, :owner_id, 0, 1)"
                    ),
                    {"name": "StockSangati Primary Workspace", "btype": "retailer", "owner_id": owner_id},
                )
                default_biz_id = conn.execute(text("SELECT id FROM businesses ORDER BY id ASC LIMIT 1")).scalar()
                for uid, role in user_rows:
                    conn.execute(
                        text(
                            "INSERT INTO business_members (business_id, user_id, role, is_active) "
                            "VALUES (:bid, :uid, :role, 1)"
                        ),
                        {"bid": default_biz_id, "uid": uid, "role": role or "staff"},
                    )
                conn.execute(
                    text("UPDATE users SET active_business_id = :bid WHERE active_business_id IS NULL"),
                    {"bid": default_biz_id},
                )
        else:
            default_biz_id = conn.execute(text("SELECT id FROM businesses ORDER BY id ASC LIMIT 1")).scalar()

        if default_biz_id is not None:
            for tbl in ("suppliers", "products", "sales", "inventory_logs", "purchase_orders"):
                conn.execute(
                    text(f"UPDATE {tbl} SET business_id = :bid WHERE business_id IS NULL"),
                    {"bid": default_biz_id},
                )

        # Backfill PO order_number and total_amount
        conn.execute(
            text(
                "UPDATE purchase_orders "
                "SET order_number = 'PO-' || printf('%04d', id) "
                "WHERE order_number IS NULL"
            )
            if target_engine.dialect.name == "sqlite"
            else text(
                "UPDATE purchase_orders SET order_number = CONCAT('PO-', LPAD(CAST(id AS TEXT), 4, '0')) "
                "WHERE order_number IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE purchase_orders SET total_amount = ROUND(COALESCE(("
                "SELECT SUM(ordered_quantity * unit_cost) FROM purchase_order_items "
                "WHERE purchase_order_items.purchase_order_id = purchase_orders.id"
                "), 0), 2) WHERE total_amount IS NULL OR total_amount = 0"
            )
        )

        # Backfill InventoryLog movement_type and previous_stock
        conn.execute(
            text(
                "UPDATE inventory_logs SET "
                "movement_type = CASE "
                "  WHEN reason = 'initial_stock' THEN 'OPENING_STOCK' "
                "  WHEN reason = 'sale' THEN 'SALE' "
                "  WHEN reason LIKE 'purchase_order%' THEN 'PURCHASE_RECEIPT' "
                "  ELSE 'STOCK_ADJUSTMENT' "
                "END "
                "WHERE movement_type IS NULL OR movement_type = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE inventory_logs SET "
                "previous_stock = MAX(0, closing_stock - COALESCE(stock_in, 0) + COALESCE(stock_out, 0)) "
                "WHERE previous_stock IS NULL"
            )
        )
        conn.execute(text("UPDATE sales SET status = 'COMPLETED' WHERE status IS NULL"))
        conn.execute(text("UPDATE users SET preferred_language = 'en' WHERE preferred_language IS NULL OR preferred_language = ''"))
        conn.execute(text("UPDATE users SET token_version = 1 WHERE token_version IS NULL"))
        conn.execute(text("UPDATE businesses SET default_language = 'en' WHERE default_language IS NULL OR default_language = ''"))
        conn.execute(text("UPDATE businesses SET currency = 'INR' WHERE currency IS NULL OR currency = ''"))
        conn.execute(text("UPDATE businesses SET low_stock_threshold_default = 10 WHERE low_stock_threshold_default IS NULL"))
        conn.execute(text("UPDATE businesses SET onboarding_completed = 0 WHERE onboarding_completed IS NULL"))
        conn.execute(text("UPDATE purchase_orders SET shared_with_supplier = 0 WHERE shared_with_supplier IS NULL"))
        conn.execute(
            text(
                "UPDATE businesses SET onboarding_completed = 1 "
                "WHERE onboarding_completed = 0 "
                "AND EXISTS (SELECT 1 FROM products WHERE products.business_id = businesses.id) "
                "AND NOT EXISTS (SELECT 1 FROM business_onboarding_progress WHERE business_onboarding_progress.business_id = businesses.id)"
            )
        )

        # Replace global unique ix_products_sku with tenant-scoped unique index on SQLite
        if target_engine.dialect.name == "sqlite":
            idx_rows = conn.execute(text("PRAGMA index_list(products)")).fetchall()
            for row in idx_rows:
                # row: (seq, name, unique, origin, partial)
                if row[1] == "ix_products_sku" and row[2] == 1 and row[3] == "c":
                    conn.execute(text("DROP INDEX IF EXISTS ix_products_sku"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_sku ON products (sku)"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_business_sku "
                    "ON products (business_id, sku)"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_business_name "
                    "ON suppliers (business_id, name)"
                )
            )

        # Create performance indexes safely
        index_statements = [
            "CREATE INDEX IF NOT EXISTS ix_suppliers_business_id ON suppliers (business_id)",
            "CREATE INDEX IF NOT EXISTS ix_products_business_id ON products (business_id)",
            "CREATE INDEX IF NOT EXISTS ix_products_supplier_id ON products (supplier_id)",
            "CREATE INDEX IF NOT EXISTS ix_sales_business_id ON sales (business_id)",
            "CREATE INDEX IF NOT EXISTS ix_sales_product_id ON sales (product_id)",
            "CREATE INDEX IF NOT EXISTS ix_sales_sales_date ON sales (sales_date)",
            "CREATE INDEX IF NOT EXISTS ix_sales_biz_prod_date ON sales (business_id, product_id, sales_date)",
            "CREATE INDEX IF NOT EXISTS ix_inventory_logs_business_id ON inventory_logs (business_id)",
            "CREATE INDEX IF NOT EXISTS ix_inventory_logs_product_id ON inventory_logs (product_id)",
            "CREATE INDEX IF NOT EXISTS ix_inventory_logs_timestamp ON inventory_logs (timestamp)",
            "CREATE INDEX IF NOT EXISTS ix_inventory_logs_biz_prod_ts ON inventory_logs (business_id, product_id, timestamp)",
            "CREATE INDEX IF NOT EXISTS ix_purchase_orders_business_id ON purchase_orders (business_id)",
            "CREATE INDEX IF NOT EXISTS ix_purchase_orders_supplier_id ON purchase_orders (supplier_id)",
            "CREATE INDEX IF NOT EXISTS ix_purchase_orders_order_number ON purchase_orders (order_number)",
            "CREATE INDEX IF NOT EXISTS ix_po_biz_status ON purchase_orders (business_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_po_items_po_prod ON purchase_order_items (purchase_order_id, product_id)",
            "CREATE INDEX IF NOT EXISTS ix_users_active_business_id ON users (active_business_id)",
        ]
        for stmt in index_statements:
            conn.execute(text(stmt))
