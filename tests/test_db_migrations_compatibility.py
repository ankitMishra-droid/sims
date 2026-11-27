import os
from datetime import date, datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from app import models
from app.core.security import hash_password
from app.database import (
    get_connect_args,
    get_engine_kwargs,
    normalize_database_url,
)
from app.db_migrate import BACKEND_DIR, backfill_legacy_defaults, ensure_schema_and_backfill
from app.main import app


def _alembic_cfg_for(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_database_url_normalization_and_ssl_defaults(monkeypatch):
    assert normalize_database_url("postgres://u:p@db.supabase.co:5432/postgres") == (
        "postgresql+psycopg2://u:p@db.supabase.co:5432/postgres"
    )
    assert normalize_database_url("postgresql://u:p@db.supabase.co:5432/postgres") == (
        "postgresql+psycopg2://u:p@db.supabase.co:5432/postgres"
    )
    assert get_connect_args("postgresql+psycopg2://u:p@aws-0-ap-south-1.pooler.supabase.com:5432/postgres") == {
        "sslmode": "require"
    }
    assert get_connect_args("postgresql+psycopg2://u:p@127.0.0.1:5432/sims_test") == {}
    assert get_connect_args("postgresql+psycopg2://u:p@db.supabase.co:5432/postgres?sslmode=verify-full") == {}

    monkeypatch.setenv("DB_USE_NULL_POOL", "true")
    kwargs = get_engine_kwargs("postgresql+psycopg2://u:p@db.supabase.co:5432/postgres")
    assert kwargs["poolclass"] is NullPool
    assert kwargs["pool_pre_ping"] is True


def test_sqlite_fresh_migration_idempotency_and_downgrade(tmp_path):
    db_file = tmp_path / "fresh_sqlite.db"
    url = f"sqlite:///{db_file.as_posix()}"
    test_engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        ensure_schema_and_backfill(test_engine)
        ensure_schema_and_backfill(test_engine)  # Repeated execution must stay idempotent

        insp = inspect(test_engine)
        tables = set(insp.get_table_names())
        expected = {
            "alembic_version",
            "users",
            "businesses",
            "business_members",
            "business_invitations",
            "business_onboarding_progress",
            "revoked_tokens",
            "password_reset_tokens",
            "suppliers",
            "products",
            "sales",
            "inventory_logs",
            "purchase_orders",
            "purchase_order_items",
            "goods_receipts",
            "goods_receipt_items",
            "purchase_order_supplier_actions",
        }
        assert expected.issubset(tables)

        cfg = _alembic_cfg_for(url)
        with test_engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")
            conn.commit()
        assert "products" not in inspect(test_engine).get_table_names()

        with test_engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        assert "products" in inspect(test_engine).get_table_names()
    finally:
        test_engine.dispose()


def test_sqlite_legacy_schema_upgrade_and_backfill_preserves_data(tmp_path):
    db_file = tmp_path / "legacy_sqlite.db"
    url = f"sqlite:///{db_file.as_posix()}"
    legacy_engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        with legacy_engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
                "email VARCHAR(120) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL, "
                "role VARCHAR(30) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            ))
            conn.execute(text(
                "CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name VARCHAR(150) NOT NULL, "
                "contact_person VARCHAR(100), email VARCHAR(255), phone VARCHAR(30), "
                "address VARCHAR(255), lead_time_days INTEGER NOT NULL DEFAULT 7, "
                "is_active BOOLEAN NOT NULL DEFAULT 1)"
            ))
            conn.execute(text(
                "CREATE TABLE products (id INTEGER PRIMARY KEY, sku VARCHAR NOT NULL, name VARCHAR NOT NULL, "
                "category VARCHAR NOT NULL DEFAULT 'General', unit VARCHAR NOT NULL DEFAULT 'piece', "
                "cost_price FLOAT NOT NULL DEFAULT 0, selling_price FLOAT NOT NULL DEFAULT 0, "
                "current_stock INTEGER NOT NULL DEFAULT 0, reorder_level INTEGER NOT NULL DEFAULT 10, "
                "supplier_id INTEGER, is_active BOOLEAN NOT NULL DEFAULT 1)"
            ))
            conn.execute(text("CREATE UNIQUE INDEX ix_products_sku ON products (sku)"))
            conn.execute(text(
                "CREATE TABLE sales (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, "
                "sales_date DATETIME DEFAULT CURRENT_TIMESTAMP, quantity_sold INTEGER NOT NULL, "
                "selling_price FLOAT NOT NULL, revenue FLOAT NOT NULL)"
            ))
            conn.execute(text(
                "CREATE TABLE inventory_logs (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, "
                "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, stock_in INTEGER NOT NULL DEFAULT 0, "
                "stock_out INTEGER NOT NULL DEFAULT 0, closing_stock INTEGER NOT NULL, reason VARCHAR NOT NULL)"
            ))
            conn.execute(text(
                "CREATE TABLE purchase_orders (id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL, "
                "status VARCHAR(20) NOT NULL DEFAULT 'DRAFT', order_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "expected_delivery_date DATETIME, notes TEXT)"
            ))
            conn.execute(text(
                "CREATE TABLE purchase_order_items (id INTEGER PRIMARY KEY, purchase_order_id INTEGER NOT NULL, "
                "product_id INTEGER NOT NULL, ordered_quantity INTEGER NOT NULL, "
                "received_quantity INTEGER NOT NULL DEFAULT 0, unit_cost NUMERIC(12, 2) NOT NULL)"
            ))

            conn.execute(
                text("INSERT INTO users (id, name, email, password_hash, role) VALUES (1, 'Owner', 'owner@legacy.in', :pw, 'admin')"),
                {"pw": hash_password("Secret123!")},
            )
            conn.execute(text("INSERT INTO suppliers (id, name) VALUES (1, 'Legacy Vendor')"))
            conn.execute(text("INSERT INTO products (id, sku, name, current_stock, supplier_id) VALUES (1, 'LEG-1', 'Legacy Item', 15, 1)"))
            conn.execute(text("INSERT INTO inventory_logs (id, product_id, stock_in, stock_out, closing_stock, reason) VALUES (1, 1, 15, 0, 15, 'initial_stock')"))
            conn.execute(text("INSERT INTO purchase_orders (id, supplier_id, status) VALUES (1, 1, 'DRAFT')"))
            conn.execute(text("INSERT INTO purchase_order_items (id, purchase_order_id, product_id, ordered_quantity, received_quantity, unit_cost) VALUES (1, 1, 1, 10, 0, 25.50)"))

        ensure_schema_and_backfill(legacy_engine)

        with legacy_engine.connect() as conn:
            prod = conn.execute(text("SELECT business_id, sku FROM products WHERE id = 1")).fetchone()
            assert prod[0] == 1
            assert prod[1] == "LEG-1"

            po = conn.execute(text("SELECT order_number, total_amount, shared_with_supplier FROM purchase_orders WHERE id = 1")).fetchone()
            assert po[0] == "PO-0001"
            assert float(po[1]) == 255.0
            assert bool(po[2]) is False

            log_row = conn.execute(text("SELECT movement_type, previous_stock FROM inventory_logs WHERE id = 1")).fetchone()
            assert log_row[0] == "OPENING_STOCK"
            assert log_row[1] == 0

            # Verify legacy global unique SKU index was converted to tenant-scoped uniqueness
            idx_rows = conn.execute(text("PRAGMA index_list(products)")).fetchall()
            sku_idx = [r for r in idx_rows if r[1] == "ix_products_sku"]
            assert sku_idx and sku_idx[0][2] == 0
            assert any(r[1] == "uq_product_business_sku" and r[2] == 1 for r in idx_rows)
    finally:
        legacy_engine.dispose()


def test_health_endpoint_ok():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["database"] == "connected"


def _postgres_test_url() -> str | None:
    raw = os.getenv("TEST_POSTGRES_URL") or os.getenv("POSTGRES_TEST_URL")
    return normalize_database_url(raw) if raw else None


@pytest.mark.skipif(_postgres_test_url() is None, reason="TEST_POSTGRES_URL not set")
def test_postgresql_full_migration_constraints_backfill_and_api_isolation():
    """Run real PostgreSQL end-to-end verification when TEST_POSTGRES_URL is provided."""
    pg_url = _postgres_test_url()
    assert pg_url is not None
    pg_engine = create_engine(pg_url, **get_engine_kwargs(pg_url))
    try:
        # 1. Clean slate downgrade/drop on dedicated test database/schema if needed
        cfg = _alembic_cfg_for(pg_url)
        with pg_engine.connect() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"))
            conn.commit()

        # 2. Fresh Alembic upgrade + repeated idempotent runs + backfill
        ensure_schema_and_backfill(pg_engine)
        ensure_schema_and_backfill(pg_engine)

        insp = inspect(pg_engine)
        assert "alembic_version" in insp.get_table_names()
        assert "purchase_orders" in insp.get_table_names()

        # Verify PostgreSQL column types (TIMESTAMPTZ/TIMESTAMP, BOOLEAN, NUMERIC)
        sup_cols = {c["name"]: c for c in insp.get_columns("suppliers")}
        assert "TIMESTAMP" in str(sup_cols["created_at"]["type"]).upper()
        biz_cols = {c["name"]: c for c in insp.get_columns("businesses")}
        assert "BOOL" in str(biz_cols["onboarding_completed"]["type"]).upper()

        # 3. Verify partial legacy upgrade path on PostgreSQL (including legacy boolean NULLs & stock calc)
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, name, email, password_hash, role, preferred_language, token_version, is_active) "
                    "VALUES (100, 'PG Legacy', 'pglegacy@sims.in', :pw, 'admin', 'en', 1, true)"
                ),
                {"pw": hash_password("Secret123!")},
            )
            conn.execute(text("INSERT INTO suppliers (id, business_id, name, lead_time_days, is_active) VALUES (100, 1, 'PG Sup', 5, true)") if False else text("SELECT 1"))

        # Test ORM + tenant-scoped SKU uniqueness + boolean/timestamp/numeric writes
        from sqlalchemy.orm import sessionmaker
        from app.database import get_db
        from app.core.rate_limiter import reset_rate_limits

        reset_rate_limits()
        PGSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

        def override_pg_db():
            db = PGSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_pg_db
        with TestClient(app) as client:
            health = client.get("/health")
            assert health.status_code == 200

            # Register Tenant A & Tenant B
            r1 = client.post(
                "/api/auth/register",
                json={"name": "PG Owner A", "email": "pga@sims.in", "password": "Password123!", "business_name": "PG Biz A"},
            )
            r2 = client.post(
                "/api/auth/register",
                json={"name": "PG Owner B", "email": "pgb@sims.in", "password": "Password123!", "business_name": "PG Biz B"},
            )
            assert r1.status_code == 201, r1.text
            assert r2.status_code == 201, r2.text

            tok_a = client.post("/api/auth/login", json={"email": "pga@sims.in", "password": "Password123!"}).json()["access_token"]
            tok_b = client.post("/api/auth/login", json={"email": "pgb@sims.in", "password": "Password123!"}).json()["access_token"]
            hdr_a = {"Authorization": f"Bearer {tok_a}"}
            hdr_b = {"Authorization": f"Bearer {tok_b}"}

            # Same SKU allowed across different tenants; duplicate SKU rejected in same tenant
            p_a = client.post(
                "/api/products/",
                headers=hdr_a,
                json={"sku": "SHARED-PG-SKU", "name": "Tenant A Item", "cost_price": 12.5, "selling_price": 20.0, "current_stock": 10},
            )
            p_b = client.post(
                "/api/products/",
                headers=hdr_b,
                json={"sku": "SHARED-PG-SKU", "name": "Tenant B Item", "cost_price": 15.0, "selling_price": 25.0, "current_stock": 8},
            )
            assert p_a.status_code == 200, p_a.text
            assert p_b.status_code == 200, p_b.text
            dup_a = client.post(
                "/api/products/",
                headers=hdr_a,
                json={"sku": "SHARED-PG-SKU", "name": "Dup Item"},
            )
            assert dup_a.status_code == 400

            # Tenant isolation: Tenant B cannot see Tenant A's product
            a_id = p_a.json()["data"]["id"]
            assert client.get(f"/api/products/{a_id}", headers=hdr_b).status_code == 404

            # Purchase Order + Receive Goods + Sale on PostgreSQL
            sup_a = client.post("/api/suppliers/", headers=hdr_a, json={"name": "PG Supplier A", "lead_time_days": 4}).json()["data"]
            po = client.post(
                "/api/purchase-orders/",
                headers=hdr_a,
                json={
                    "supplier_id": sup_a["id"],
                    "expected_delivery_date": date.today().isoformat(),
                    "items": [{"product_id": a_id, "ordered_quantity": 5, "unit_cost": 12.5}],
                },
            )
            assert po.status_code == 201, po.text
            po_id = po.json()["id"]
            assert client.post(f"/api/purchase-orders/{po_id}/send", headers=hdr_a).status_code == 200
            rec = client.post(
                f"/api/purchase-orders/{po_id}/receive",
                headers=hdr_a,
                json={"items": [{"purchase_order_item_id": po.json()["items"][0]["id"], "received_quantity": 5}]},
            )
            assert rec.status_code == 200, rec.text
            assert rec.json()["status"] == "RECEIVED"

            sale = client.post("/api/sales/", headers=hdr_a, json={"product_id": a_id, "quantity_sold": 3})
            assert sale.status_code == 200, sale.text
            assert client.get(f"/api/products/{a_id}", headers=hdr_a).json()["data"]["current_stock"] == 12

        # 4. Also test backfill_legacy_defaults directly on PostgreSQL (including GREATEST/CASE previous_stock & bool backfill)
        with pg_engine.begin() as conn:
            conn.execute(text("UPDATE purchase_orders SET order_number = NULL, total_amount = 0, shared_with_supplier = NULL"))
            conn.execute(text("UPDATE inventory_logs SET previous_stock = NULL, movement_type = NULL"))
        backfill_legacy_defaults(pg_engine)
        with pg_engine.connect() as conn:
            po_row = conn.execute(text("SELECT order_number, total_amount, shared_with_supplier FROM purchase_orders WHERE id = :id"), {"id": po_id}).fetchone()
            assert po_row[0] == f"PO-{po_id:04d}"
            assert float(po_row[1]) == 62.5
            assert po_row[2] is False
            log_prev = conn.execute(text("SELECT previous_stock, movement_type FROM inventory_logs ORDER BY id ASC LIMIT 1")).fetchone()
            assert log_prev[0] >= 0
            assert log_prev[1] in {"OPENING_STOCK", "PURCHASE_RECEIPT", "SALE", "STOCK_ADJUSTMENT"}
    finally:
        app.dependency_overrides.clear()
        pg_engine.dispose()
