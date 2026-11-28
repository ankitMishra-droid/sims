from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import engine

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _escape_configparser_value(value: str) -> str:
    """Escape '%' so ConfigParser interpolation does not reject percent-encoded URLs."""
    return value.replace("%", "%%")


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", _escape_configparser_value(str(BACKEND_DIR / "migrations")))
    cfg.set_main_option("sqlalchemy.url", _escape_configparser_value(url))
    return cfg


def run_alembic_migrations(target_engine: Engine = engine) -> None:
    """Apply Alembic schema revisions against target_engine safely on SQLite and PostgreSQL."""
    from . import models  # Register SQLAlchemy metadata.

    _ = models.__all__  # Keep the side-effect import explicit to static analyzers.

    url = target_engine.url.render_as_string(hide_password=False)
    cfg = _alembic_config(url)
    with target_engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        # Ensure connection commit when dialect isn't autocommit
        if conn.in_transaction():
            conn.commit()


def _drop_legacy_global_product_sku_unique(conn, insp) -> None:
    """Replace any legacy global-unique products.sku index/constraint with non-unique ix_products_sku."""
    if not insp.has_table("products"):
        return

    if conn.dialect.name == "sqlite":
        idx_rows = conn.execute(text("PRAGMA index_list(products)")).fetchall()
        for row in idx_rows:
            if row[1] == "ix_products_sku" and row[2] == 1 and row[3] == "c":
                conn.execute(text("DROP INDEX IF EXISTS ix_products_sku"))
    else:
        for idx in insp.get_indexes("products"):
            if idx.get("name") == "ix_products_sku" and idx.get("unique"):
                conn.execute(text("DROP INDEX IF EXISTS ix_products_sku"))
        for uc in insp.get_unique_constraints("products"):
            if uc.get("column_names") == ["sku"] and uc.get("name"):
                conn.execute(text(f'ALTER TABLE products DROP CONSTRAINT IF EXISTS "{uc["name"]}"'))

    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_sku ON products (sku)"))


def _ensure_tenant_unique_indexes(conn, insp) -> None:
    """Ensure tenant-scoped SKU and supplier-name uniqueness exists on both SQLite and PostgreSQL."""
    if insp.has_table("products"):
        existing_uqs = {uc.get("name") for uc in insp.get_unique_constraints("products")}
        existing_uqs.update(idx.get("name") for idx in insp.get_indexes("products") if idx.get("unique"))
        if "uq_product_business_sku" not in existing_uqs:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_business_sku "
                    "ON products (business_id, sku)"
                )
            )

    if insp.has_table("suppliers"):
        existing_uqs = {uc.get("name") for uc in insp.get_unique_constraints("suppliers")}
        existing_uqs.update(idx.get("name") for idx in insp.get_indexes("suppliers") if idx.get("unique"))
        if "uq_supplier_business_name" not in existing_uqs:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_business_name "
                    "ON suppliers (business_id, name)"
                )
            )


def backfill_legacy_defaults(target_engine: Engine = engine) -> None:
    """Idempotently backfill tenant ownership, defaults, order numbers, and stock history."""
    with target_engine.begin() as conn:
        insp = inspect(conn)

        biz_count = conn.execute(text("SELECT COUNT(*) FROM businesses")).scalar() or 0
        default_biz_id = None
        if biz_count == 0:
            user_rows = conn.execute(text("SELECT id, role FROM users ORDER BY id ASC")).fetchall()
            if user_rows:
                owner_id = next((r[0] for r in user_rows if r[1] == "admin"), user_rows[0][0])
                conn.execute(
                    text(
                        "INSERT INTO businesses (name, business_type, owner_user_id, allow_negative_stock, onboarding_completed, is_active) "
                        "VALUES (:name, :btype, :owner_id, :allow_neg, :onboarded, :active)"
                    ),
                    {
                        "name": "StockSangati Primary Workspace",
                        "btype": "retailer",
                        "owner_id": owner_id,
                        "allow_neg": False,
                        "onboarded": False,
                        "active": True,
                    },
                )
                default_biz_id = conn.execute(text("SELECT id FROM businesses ORDER BY id ASC LIMIT 1")).scalar()
                for uid, role in user_rows:
                    conn.execute(
                        text(
                            "INSERT INTO business_members (business_id, user_id, role, is_active) "
                            "VALUES (:bid, :uid, :role, :active)"
                        ),
                        {"bid": default_biz_id, "uid": uid, "role": role or "staff", "active": True},
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

        # Cross-dialect PO order_number and total_amount backfill
        if conn.dialect.name == "sqlite":
            conn.execute(
                text(
                    "UPDATE purchase_orders "
                    "SET order_number = 'PO-' || printf('%04d', id) "
                    "WHERE order_number IS NULL"
                )
            )
        else:
            conn.execute(
                text(
                    "UPDATE purchase_orders "
                    "SET order_number = CONCAT('PO-', LPAD(CAST(id AS TEXT), 4, '0')) "
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

        # Backfill InventoryLog movement_type and dialect-neutral non-negative previous_stock
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
                "previous_stock = CASE "
                "  WHEN (closing_stock - COALESCE(stock_in, 0) + COALESCE(stock_out, 0)) > 0 "
                "  THEN (closing_stock - COALESCE(stock_in, 0) + COALESCE(stock_out, 0)) "
                "  ELSE 0 "
                "END "
                "WHERE previous_stock IS NULL"
            )
        )

        conn.execute(text("UPDATE sales SET status = 'COMPLETED' WHERE status IS NULL"))
        conn.execute(text("UPDATE users SET preferred_language = 'en' WHERE preferred_language IS NULL OR preferred_language = ''"))
        conn.execute(text("UPDATE users SET token_version = 1 WHERE token_version IS NULL"))
        conn.execute(text("UPDATE businesses SET default_language = 'en' WHERE default_language IS NULL OR default_language = ''"))
        conn.execute(text("UPDATE businesses SET currency = 'INR' WHERE currency IS NULL OR currency = ''"))
        conn.execute(text("UPDATE businesses SET low_stock_threshold_default = 10 WHERE low_stock_threshold_default IS NULL"))
        conn.execute(
            text("UPDATE businesses SET onboarding_completed = :val WHERE onboarding_completed IS NULL"),
            {"val": False},
        )
        conn.execute(
            text("UPDATE purchase_orders SET shared_with_supplier = :val WHERE shared_with_supplier IS NULL"),
            {"val": False},
        )
        conn.execute(
            text(
                "UPDATE businesses SET onboarding_completed = :done "
                "WHERE onboarding_completed = :pending "
                "AND EXISTS (SELECT 1 FROM products WHERE products.business_id = businesses.id) "
                "AND NOT EXISTS (SELECT 1 FROM business_onboarding_progress WHERE business_onboarding_progress.business_id = businesses.id)"
            ),
            {"done": True, "pending": False},
        )

        _drop_legacy_global_product_sku_unique(conn, insp)
        _ensure_tenant_unique_indexes(conn, insp)


def ensure_schema_and_backfill(target_engine: Engine = engine) -> None:
    """Run controlled Alembic schema migrations followed by idempotent legacy data backfill."""
    if target_engine.dialect.name == "postgresql":
        lock_id = 71092026
        with target_engine.connect() as lock_conn:
            lock_conn.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})
            try:
                run_alembic_migrations(target_engine)
                backfill_legacy_defaults(target_engine)
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
                if lock_conn.in_transaction():
                    lock_conn.commit()
        return

    run_alembic_migrations(target_engine)
    backfill_legacy_defaults(target_engine)


if __name__ == "__main__":
    ensure_schema_and_backfill(engine)
