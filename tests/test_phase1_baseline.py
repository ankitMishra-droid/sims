from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.database import base, get_db
from app.main import app
from app import models


def _create_isolated_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def test_phase1_supplier_nullable_fields_and_po_lifecycle():
    client, SessionMaker = _create_isolated_client()
    try:
        with SessionMaker() as db:
            user = models.User(
                name="Phase1 Admin",
                email="phase1@stocksangati.com",
                password_hash=hash_password("SecretPassword123!"),
                role="admin",
                is_active=True,
            )
            db.add(user)
            db.flush()
            biz = models.Business(
                name="Phase1 Workspace",
                business_type="retailer",
                owner_user_id=user.id,
                is_active=True,
            )
            db.add(biz)
            db.flush()
            db.add(models.BusinessMember(business_id=biz.id, user_id=user.id, role="admin", is_active=True))
            user.active_business_id = biz.id
            db.commit()

        # Login over HTTP
        login_res = client.post(
            "/api/auth/login",
            json={"email": "phase1@stocksangati.com", "password": "SecretPassword123!"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create supplier with nullable email/phone/address
        supp_res = client.post(
            "/api/suppliers/",
            headers=headers,
            json={"name": "Minimal Vendor", "lead_time_days": 5},
        )
        assert supp_res.status_code == 200
        list_supp = client.get("/api/suppliers/", headers=headers)
        assert list_supp.status_code == 200
        suppliers = list_supp.json()["data"]
        assert len(suppliers) == 1
        supplier_id = suppliers[0]["id"]
        assert suppliers[0]["email"] is None

        # Create product
        prod_res = client.post(
            "/api/products/",
            headers=headers,
            json={
                "sku": "PH1-SKU-001",
                "name": "Phase 1 Test Widget",
                "category": "Hardware",
                "unit": "piece",
                "cost_price": 100.0,
                "selling_price": 150.0,
                "current_stock": 10,
                "reorder_level": 5,
                "supplier_id": supplier_id,
            },
        )
        assert prod_res.status_code == 200
        product_id = prod_res.json()["data"]["id"]

        # Convert recommendation to PO
        po_res = client.post(
            "/api/decision/convert-to-po",
            headers=headers,
            json={
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 20}],
                "expected_delivery_date": date.today().isoformat(),
                "notes": "Phase 1 regression check",
            },
        )
        assert po_res.status_code == 201
        po_data = po_res.json()
        po_id = po_data["purchase_order_id"]
        assert po_data["total_amount"] == 2000.0

        # Update draft PO scalar fields safely
        upd_res = client.put(
            f"/api/purchase-orders/{po_id}",
            headers=headers,
            json={"notes": "Updated PO notes"},
        )
        assert upd_res.status_code == 200
        assert upd_res.json()["notes"] == "Updated PO notes"

        # Send PO before receiving
        send_res = client.post(f"/api/purchase-orders/{po_id}/send", headers=headers)
        assert send_res.status_code == 200
        assert send_res.json()["status"] == "SENT"

        # Partial receive then full receive should add exact remaining units (20 total)
        po_detail = client.get(f"/api/purchase-orders/{po_id}", headers=headers).json()
        item_id = po_detail["items"][0]["id"]

        part_res = client.post(
            f"/api/purchase-orders/{po_id}/partially_receive",
            headers=headers,
            json={"purchase_order_item_id": item_id, "received_quantity": 8},
        )
        assert part_res.status_code == 200
        assert part_res.json()["status"] == "PARTIALLY_RECEIVED"

        full_res = client.post(f"/api/purchase-orders/{po_id}/receive", headers=headers)
        assert full_res.status_code == 200
        assert full_res.json()["status"] == "RECEIVED"

        # Double receive must be rejected
        dup_res = client.post(f"/api/purchase-orders/{po_id}/receive", headers=headers)
        assert dup_res.status_code == 400

        # Final product stock must be 10 + 8 + 12 = 30
        prod_after = client.get(f"/api/products/{product_id}", headers=headers).json()["data"]
        assert prod_after["current_stock"] == 30
    finally:
        app.dependency_overrides.clear()
