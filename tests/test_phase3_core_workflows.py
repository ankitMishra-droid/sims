from concurrent.futures import ThreadPoolExecutor
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.security import hash_password
from app.database import base, get_db, _set_sqlite_pragma
from app.main import app
from app.services import stock_service
from sqlalchemy import event


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSession


def _register_and_login(client: TestClient, *, name: str, email: str, role: str = "admin", business_name: str | None = None):
    reg = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "Password123!",
            "role": role,
            "business_name": business_name or f"{name} Biz",
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/api/auth/login", json={"email": email, "password": "Password123!"})
    assert login.status_code == 200, login.text
    data = login.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]


def test_products_suppliers_crud_validation_and_ledger_isolation():
    client, _ = _make_client()
    try:
        # Unauthenticated requests must be rejected
        assert client.get("/api/products/").status_code == 401
        assert client.get("/api/suppliers/").status_code == 401
        assert client.get("/api/sales/").status_code == 401
        assert client.get("/api/purchase-orders/").status_code == 401
        assert client.get("/dashboard/summary").status_code == 401

        hdrs_a, _ = _register_and_login(client, name="Alice", email="alice@biz1.com", role="admin")

        # Create two suppliers with NULL email (regression for NULL == NULL bug)
        s1 = client.post("/api/suppliers/", headers=hdrs_a, json={"name": "Vendor One", "lead_time_days": 4})
        s2 = client.post("/api/suppliers/", headers=hdrs_a, json={"name": "Vendor Two", "lead_time_days": 6})
        assert s1.status_code == 200
        assert s2.status_code == 200
        s1_id = s1.json()["data"]["id"]
        assert s1_id is not None

        # Invalid negative price/stock rejected
        bad_prod = client.post(
            "/api/products/",
            headers=hdrs_a,
            json={"sku": "BAD-1", "name": "Bad", "cost_price": -5, "selling_price": 10},
        )
        assert bad_prod.status_code == 422

        # Blank category defaults safely to "General"; opening stock creates OPENING_STOCK ledger entry
        p1 = client.post(
            "/api/products/",
            headers=hdrs_a,
            json={
                "sku": "SKU-A1",
                "name": "Widget Alpha",
                "category": "",
                "cost_price": 50.0,
                "selling_price": 80.0,
                "current_stock": 15,
                "reorder_level": 5,
                "supplier_id": s1_id,
            },
        )
        assert p1.status_code == 200, p1.text
        p1_data = p1.json()["data"]
        assert p1_data["category"] == "General"
        p1_id = p1_data["id"]

        # Duplicate SKU in same business rejected
        dup_sku = client.post(
            "/api/products/",
            headers=hdrs_a,
            json={"sku": "SKU-A1", "name": "Duplicate SKU"},
        )
        assert dup_sku.status_code == 400

        # PUT /api/products/{id} must NOT mutate current_stock directly
        upd = client.put(
            f"/api/products/{p1_id}",
            headers=hdrs_a,
            json={
                "sku": "SKU-A1",
                "name": "Widget Alpha Updated",
                "category": "Hardware",
                "cost_price": 55.0,
                "selling_price": 90.0,
                "current_stock": 9999,  # attempted bypass
                "reorder_level": 6,
            },
        )
        assert upd.status_code == 200
        assert upd.json()["data"]["current_stock"] == 15
        assert upd.json()["data"]["name"] == "Widget Alpha Updated"

        # Stock adjustment requires valid reason and supports negative delta
        bad_adj = client.post(
            "/api/inventory/adjust",
            headers=hdrs_a,
            json={"product_id": p1_id, "quantity_delta": -2, "reason": " "},
        )
        assert bad_adj.status_code == 422

        too_much = client.post(
            "/api/inventory/adjust",
            headers=hdrs_a,
            json={"product_id": p1_id, "quantity_delta": -50, "reason": "damaged"},
        )
        assert too_much.status_code == 400

        ok_adj = client.post(
            "/api/inventory/adjust",
            headers=hdrs_a,
            json={"product_id": p1_id, "quantity_delta": -3, "reason": "damaged_units"},
        )
        assert ok_adj.status_code == 200
        assert ok_adj.json()["current_stock"] == 12

        logs = client.get(f"/api/inventory/logs/{p1_id}", headers=hdrs_a).json()
        assert len(logs) == 2
        assert logs[0]["movement_type"] == "STOCK_ADJUSTMENT"
        assert logs[0]["previous_stock"] == 15
        assert logs[0]["resulting_stock"] == 12
        assert logs[1]["movement_type"] == "OPENING_STOCK"
        assert logs[1]["resulting_stock"] == 15

        # Deactivate & reactivate product
        assert client.patch(f"/api/products/deactivate/{p1_id}", headers=hdrs_a).status_code == 200
        assert client.get(f"/api/products/{p1_id}", headers=hdrs_a).status_code == 404
        assert client.patch(f"/api/products/activate/{p1_id}", headers=hdrs_a).status_code == 200
        assert client.get(f"/api/products/{p1_id}", headers=hdrs_a).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_sales_idempotency_rollback_and_cancellation():
    client, _ = _make_client()
    try:
        hdrs, _ = _register_and_login(client, name="Seller", email="seller@biz.com", role="admin")
        p = client.post(
            "/api/products/",
            headers=hdrs,
            json={"sku": "SALE-1", "name": "Sold Item", "cost_price": 20, "selling_price": 35, "current_stock": 10},
        ).json()["data"]
        pid = p["id"]

        # Idempotent sale submission must only deduct stock once
        idem_hdrs = {**hdrs, "Idempotency-Key": "sale-req-123"}
        s1 = client.post("/api/sales/", headers=idem_hdrs, json={"product_id": pid, "quantity_sold": 4})
        s2 = client.post("/api/sales/", headers=idem_hdrs, json={"product_id": pid, "quantity_sold": 4})
        assert s1.status_code == 200
        assert s2.status_code == 200
        assert s1.json()["data"]["id"] == s2.json()["data"]["id"]
        assert s1.json()["data"]["revenue"] == 140.0

        prod_after_sale = client.get(f"/api/products/{pid}", headers=hdrs).json()["data"]
        assert prod_after_sale["current_stock"] == 6

        # Insufficient stock rolls back cleanly and leaves stock at 6
        bad_sale = client.post("/api/sales/", headers=hdrs, json={"product_id": pid, "quantity_sold": 99})
        assert bad_sale.status_code == 400
        assert client.get(f"/api/products/{pid}", headers=hdrs).json()["data"]["current_stock"] == 6

        # Cancel sale restores stock via REVERSAL ledger entry; double cancel blocked
        sale_id = s1.json()["data"]["id"]
        cancel_res = client.post(
            f"/api/sales/{sale_id}/cancel",
            headers=hdrs,
            json={"reason": "customer_return"},
        )
        assert cancel_res.status_code == 200
        assert cancel_res.json()["data"]["status"] == "CANCELLED"
        assert client.get(f"/api/products/{pid}", headers=hdrs).json()["data"]["current_stock"] == 10
        assert client.post(f"/api/sales/{sale_id}/cancel", headers=hdrs, json={"reason": "retry"}).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_po_lifecycle_partial_multi_line_receipts_and_inventory_position():
    client, _ = _make_client()
    try:
        hdrs, _ = _register_and_login(client, name="Buyer", email="buyer@biz.com", role="admin")
        supp = client.post("/api/suppliers/", headers=hdrs, json={"name": "Main Supplier", "lead_time_days": 5}).json()["data"]
        p_a = client.post(
            "/api/products/",
            headers=hdrs,
            json={"sku": "PA-1", "name": "Product A", "cost_price": 10, "selling_price": 20, "current_stock": 0},
        ).json()["data"]
        p_b = client.post(
            "/api/products/",
            headers=hdrs,
            json={"sku": "PB-1", "name": "Product B", "cost_price": 15, "selling_price": 30, "current_stock": 5},
        ).json()["data"]

        # Create PO in DRAFT (must NOT increase stock or incoming stock yet)
        po_res = client.post(
            "/api/purchase-orders/",
            headers=hdrs,
            json={
                "supplier_id": supp["id"],
                "expected_delivery_date": date.today().isoformat(),
                "items": [
                    {"product_id": p_a["id"], "ordered_quantity": 100, "unit_cost": 10},
                    {"product_id": p_b["id"], "ordered_quantity": 50, "unit_cost": 15},
                ],
            },
        )
        assert po_res.status_code == 201
        po = po_res.json()
        assert po["status"] == "DRAFT"
        assert po["total_amount"] == 1750.0
        assert po["order_number"].startswith("PO-")

        pos_draft = client.get(f"/api/inventory/positions/{p_a['id']}", headers=hdrs).json()
        assert pos_draft["on_hand_stock"] == 0
        assert pos_draft["incoming_stock"] == 0

        # Receiving DRAFT PO directly must be rejected
        item_a_id = next(i["id"] for i in po["items"] if i["product_id"] == p_a["id"])
        item_b_id = next(i["id"] for i in po["items"] if i["product_id"] == p_b["id"])
        assert (
            client.post(
                f"/api/purchase-orders/{po['id']}/receipts",
                headers=hdrs,
                json={"items": [{"purchase_order_item_id": item_a_id, "received_quantity": 10}]},
            ).status_code
            == 400
        )

        # Send PO -> SENT (still does NOT increase on-hand stock, but adds incoming_stock)
        sent = client.post(f"/api/purchase-orders/{po['id']}/send", headers=hdrs)
        assert sent.status_code == 200
        assert sent.json()["status"] == "SENT"

        pos_sent = client.get(f"/api/inventory/positions/{p_a['id']}", headers=hdrs).json()
        assert pos_sent["on_hand_stock"] == 0
        assert pos_sent["incoming_stock"] == 100
        assert pos_sent["inventory_position"] == 100

        # Partial multi-line receipt: A=40, B=20 with idempotency key
        r1 = client.post(
            f"/api/purchase-orders/{po['id']}/receipts",
            headers={**hdrs, "Idempotency-Key": "gr-1"},
            json={
                "items": [
                    {"purchase_order_item_id": item_a_id, "received_quantity": 40},
                    {"purchase_order_item_id": item_b_id, "received_quantity": 20},
                ],
                "notes": "First truck delivery",
            },
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "PARTIALLY_RECEIVED"

        # Duplicate idempotent submission must NOT increase stock again
        r1_dup = client.post(
            f"/api/purchase-orders/{po['id']}/receipts",
            headers={**hdrs, "Idempotency-Key": "gr-1"},
            json={
                "items": [
                    {"purchase_order_item_id": item_a_id, "received_quantity": 40},
                    {"purchase_order_item_id": item_b_id, "received_quantity": 20},
                ],
            },
        )
        assert r1_dup.status_code == 200

        pos_a_mid = client.get(f"/api/inventory/positions/{p_a['id']}", headers=hdrs).json()
        pos_b_mid = client.get(f"/api/inventory/positions/{p_b['id']}", headers=hdrs).json()
        assert pos_a_mid["on_hand_stock"] == 40
        assert pos_a_mid["incoming_stock"] == 60
        assert pos_a_mid["inventory_position"] == 100
        assert pos_b_mid["on_hand_stock"] == 25  # 5 + 20
        assert pos_b_mid["incoming_stock"] == 30
        assert pos_b_mid["inventory_position"] == 55

        # Over-receipt validation (trying to receive 61 when 60 remain) must roll back whole receipt
        over = client.post(
            f"/api/purchase-orders/{po['id']}/receipts",
            headers=hdrs,
            json={
                "items": [
                    {"purchase_order_item_id": item_b_id, "received_quantity": 10},
                    {"purchase_order_item_id": item_a_id, "received_quantity": 61},
                ]
            },
        )
        assert over.status_code == 400
        assert client.get(f"/api/products/{p_b['id']}", headers=hdrs).json()["data"]["current_stock"] == 25

        # Cancel & delete on PARTIALLY_RECEIVED must be rejected
        assert client.post(f"/api/purchase-orders/{po['id']}/cancel", headers=hdrs).status_code == 400
        assert client.delete(f"/api/purchase-orders/{po['id']}", headers=hdrs).status_code == 400

        # Receive remaining -> RECEIVED
        r2 = client.post(f"/api/purchase-orders/{po['id']}/receive", headers=hdrs)
        assert r2.status_code == 200
        assert r2.json()["status"] == "RECEIVED"

        receipts = client.get(f"/api/purchase-orders/{po['id']}/receipts", headers=hdrs).json()
        assert len(receipts) == 2

        pos_a_end = client.get(f"/api/inventory/positions/{p_a['id']}", headers=hdrs).json()
        assert pos_a_end["on_hand_stock"] == 100
        assert pos_a_end["incoming_stock"] == 0
        assert pos_a_end["inventory_position"] == 100
    finally:
        app.dependency_overrides.clear()


def test_cross_tenant_isolation_and_role_restrictions():
    client, SessionMaker = _make_client()
    try:
        hdrs_a, user_a = _register_and_login(client, name="Owner A", email="ownera@a.com", role="admin")
        hdrs_b, user_b = _register_and_login(client, name="Owner B", email="ownerb@b.com", role="admin")
        hdrs_sup, _ = _register_and_login(client, name="Supplier User", email="sup@s.com", role="supplier")

        # Create product & supplier in Business A
        supp_a = client.post("/api/suppliers/", headers=hdrs_a, json={"name": "A Vendor"}).json()["data"]
        prod_a = client.post(
            "/api/products/",
            headers=hdrs_a,
            json={"sku": "SHARED-SKU", "name": "A Secret Product", "current_stock": 20, "supplier_id": supp_a["id"]},
        ).json()["data"]

        # Business B can use same SKU in its own workspace without colliding with Business A
        prod_b = client.post(
            "/api/products/",
            headers=hdrs_b,
            json={"sku": "SHARED-SKU", "name": "B Product", "current_stock": 5},
        )
        assert prod_b.status_code == 200

        # Business B cannot read/update Business A records or switch X-Business-Id header
        assert client.get(f"/api/products/{prod_a['id']}", headers=hdrs_b).status_code == 404
        assert client.put(f"/api/products/{prod_a['id']}", headers=hdrs_b, json={"name": "Hijack"}).status_code == 404
        assert client.get(f"/api/suppliers/{supp_a['id']}", headers=hdrs_b).status_code == 404
        assert client.get("/api/products/", headers={**hdrs_b, "X-Business-Id": str(user_a["active_business_id"])}).status_code == 403

        # Supplier role must NOT access full business inventory/sales/products/POs
        assert client.get("/api/products/", headers=hdrs_sup).status_code == 403
        assert client.get("/api/sales/", headers=hdrs_sup).status_code == 403
        assert client.get("/api/inventory/low-stock", headers=hdrs_sup).status_code == 403
        assert client.get("/dashboard/summary", headers=hdrs_sup).status_code == 403

        # Staff member in Business A can read/record sales, but cannot create products/POs or adjust stock
        with SessionMaker() as db:
            staff = models.User(
                name="Staff A",
                email="staff@a.com",
                password_hash=hash_password("Password123!"),
                role="staff",
                active_business_id=user_a["active_business_id"],
                is_active=True,
            )
            db.add(staff)
            db.flush()
            db.add(models.BusinessMember(business_id=user_a["active_business_id"], user_id=staff.id, role="staff"))
            db.commit()

        staff_login = client.post("/api/auth/login", json={"email": "staff@a.com", "password": "Password123!"})
        staff_hdrs = {"Authorization": f"Bearer {staff_login.json()['access_token']}"}
        assert client.get("/api/products/", headers=staff_hdrs).status_code == 200
        assert client.post("/api/products/", headers=staff_hdrs, json={"sku": "S-1", "name": "Nope"}).status_code == 403
        assert client.post("/api/inventory/adjust", headers=staff_hdrs, json={"product_id": prod_a["id"], "quantity_delta": 1, "reason": "test"}).status_code == 403
        assert client.post("/api/sales/", headers=staff_hdrs, json={"product_id": prod_a["id"], "quantity_sold": 2}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_concurrent_stock_deduction_prevents_negative_stock(tmp_path):
    db_file = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionMaker() as db:
        u = models.User(name="C", email="c@c.com", password_hash=hash_password("Password123!"), role="admin")
        db.add(u)
        db.flush()
        b = models.Business(name="CBiz", business_type="retailer", owner_user_id=u.id)
        db.add(b)
        db.flush()
        p = models.Product(business_id=b.id, sku="CONC-1", name="Concurrent Item", category="General", current_stock=10)
        db.add(p)
        db.commit()
        biz_id, prod_id, uid = b.id, p.id, u.id

    def attempt_sale():
        with SessionMaker() as db:
            try:
                stock_service.decrease_stock(
                    db,
                    product_id=prod_id,
                    quantity=6,
                    reason="concurrent_sale",
                    business_id=biz_id,
                    user_id=uid,
                )
                db.commit()
                return "OK"
            except Exception:
                db.rollback()
                return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt_sale(), range(2)))

    assert sorted(outcomes) == ["OK", "REJECTED"]
    with SessionMaker() as db:
        final_prod = db.query(models.Product).filter(models.Product.id == prod_id).first()
        assert final_prod.current_stock == 4
        logs = db.query(models.InventoryLog).filter(models.InventoryLog.product_id == prod_id).all()
        assert len(logs) == 1
        assert logs[0].closing_stock == 4
    engine.dispose()
