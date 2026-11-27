from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.rate_limiter import reset_rate_limits
from app.core.security import create_access_token, hash_reset_token
from app.database import base, get_db, _set_sqlite_pragma
from app.main import app
from app.services.auth import AuthService


def _make_client():
    reset_rate_limits()
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


def _auth_headers(token: str, biz_id: int | None = None) -> dict:
    hdrs = {"Authorization": f"Bearer {token}"}
    if biz_id is not None:
        hdrs["X-Business-Id"] = str(biz_id)
    return hdrs


def test_auth_lifecycle_refresh_logout_expiry_password_reset_and_rate_limit(monkeypatch):
    client, SessionMaker = _make_client()
    try:
        # 1. Register without workspace -> duplicate email rejected
        reg = client.post(
            "/api/auth/register",
            json={
                "name": "Auth Tester",
                "email": "authtest@sims.in",
                "password": "Password123!",
                "preferred_language": "hi",
                "create_workspace": False,
            },
        )
        assert reg.status_code == 201, reg.text
        user_data = reg.json()
        assert user_data["active_business_id"] is None
        assert user_data["preferred_language"] == "hi"

        dup = client.post(
            "/api/auth/register",
            json={
                "name": "Dup",
                "email": "AUTHTEST@sims.in",
                "password": "Password123!",
                "create_workspace": False,
            },
        )
        assert dup.status_code == 400

        # 2. Invalid password -> 401; valid login -> tokens
        bad = client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "WrongPassword!"})
        assert bad.status_code == 401

        login = client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "Password123!"})
        assert login.status_code == 200
        tokens = login.json()
        access_1 = tokens["access_token"]
        refresh_1 = tokens["refresh_token"]
        assert client.get("/api/auth/me", headers=_auth_headers(access_1)).status_code == 200

        # 3. Refresh token rotates cleanly and revokes old refresh token
        refreshed = client.post("/api/auth/refresh", json={"refresh_token": refresh_1})
        assert refreshed.status_code == 200
        access_2 = refreshed.json()["access_token"]
        refresh_2 = refreshed.json()["refresh_token"]
        assert client.post("/api/auth/refresh", json={"refresh_token": refresh_1}).status_code == 401

        # 4. Expired token rejected
        expired = create_access_token(
            {"sub": str(user_data["id"]), "email": "authtest@sims.in"},
            expires_delta=timedelta(minutes=-5),
        )
        assert client.get("/api/auth/me", headers=_auth_headers(expired)).status_code == 401

        # 5. Logout revokes active access & refresh tokens
        out = client.post(
            "/api/auth/logout",
            headers=_auth_headers(access_2),
            json={"refresh_token": refresh_2},
        )
        assert out.status_code == 200
        assert client.get("/api/auth/me", headers=_auth_headers(access_2)).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": refresh_2}).status_code == 401

        # 6. Login again + change password invalidates old token & keeps new token working
        login_2 = client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "Password123!"}).json()
        old_access = login_2["access_token"]
        cp = client.post(
            "/api/auth/change-password",
            headers=_auth_headers(old_access),
            json={"current_password": "Password123!", "new_password": "NewPassword456!"},
        )
        assert cp.status_code == 200
        new_access = cp.json()["access_token"]
        assert client.get("/api/auth/me", headers=_auth_headers(old_access)).status_code == 401
        assert client.get("/api/auth/me", headers=_auth_headers(new_access)).status_code == 200

        # 7. Verified Password Reset flow (token hashed in DB, single-use, never returned over HTTP)
        captured_tokens = []
        monkeypatch.setattr(
            AuthService,
            "_dispatch_password_reset_notification",
            staticmethod(lambda email, raw: captured_tokens.append((email, raw))),
        )
        req_reset = client.post("/api/auth/password-reset/request", json={"email": "authtest@sims.in"})
        assert req_reset.status_code == 200
        assert "token" not in req_reset.text.lower() or "token has been dispatched" in req_reset.text.lower()
        assert len(captured_tokens) == 1
        raw_reset = captured_tokens[0][1]

        with SessionMaker() as db:
            row = db.query(models.PasswordResetToken).first()
            assert row is not None
            assert row.token_hash == hash_reset_token(raw_reset)
            assert row.token_hash != raw_reset

        conf = client.post(
            "/api/auth/password-reset/confirm",
            json={"token": raw_reset, "new_password": "ResetPassword789!"},
        )
        assert conf.status_code == 200
        # Replay of used reset token rejected
        assert (
            client.post(
                "/api/auth/password-reset/confirm",
                json={"token": raw_reset, "new_password": "AnotherPassword000!"},
            ).status_code
            == 400
        )
        # Old access invalidated by reset; new password logs in cleanly
        assert client.get("/api/auth/me", headers=_auth_headers(new_access)).status_code == 401
        assert (
            client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "ResetPassword789!"}).status_code
            == 200
        )

        # 8. Rate limiter returns 429 when limit exceeded
        reset_rate_limits()
        monkeypatch.setenv("AUTH_LOGIN_LIMIT", "2")
        assert client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "wrong"}).status_code == 401
        limited = client.post("/api/auth/login", json={"email": "authtest@sims.in", "password": "wrong"})
        assert limited.status_code == 429
    finally:
        app.dependency_overrides.clear()


def test_workspaces_switching_rbac_onboarding_and_supplier_portal():
    client, _ = _make_client()
    try:
        # 1. Retailer registers without initial workspace, then creates workspace -> becomes OWNER
        client.post(
            "/api/auth/register",
            json={
                "name": "Ramesh Retailer",
                "email": "ramesh@retail.in",
                "password": "Password123!",
                "create_workspace": False,
            },
        )
        r_login = client.post("/api/auth/login", json={"email": "ramesh@retail.in", "password": "Password123!"}).json()
        r_tok = r_login["access_token"]
        assert r_login["user"]["active_business_id"] is None

        # Cannot read businesses/current until workspace created
        assert client.get("/api/businesses/current", headers=_auth_headers(r_tok)).status_code == 403

        biz1_res = client.post(
            "/api/businesses/",
            headers=_auth_headers(r_tok),
            json={"name": "Ramesh Kirana Store", "business_type": "retailer", "default_language": "hi"},
        )
        assert biz1_res.status_code == 201, biz1_res.text
        biz1 = biz1_res.json()
        assert biz1["role"] == "owner"
        biz1_id = biz1["business"]["id"]

        # Re-login confirms active workspace & permissions
        cur = client.get("/api/businesses/current", headers=_auth_headers(r_tok)).json()
        assert cur["business"]["id"] == biz1_id
        assert cur["role"] == "owner"

        # 2. Onboarding: step-by-step, Hindi language, profile, products (duplicate-safe), suppliers, opening stock (idempotent)
        p0 = client.get("/api/onboarding/progress", headers=_auth_headers(r_tok)).json()
        assert p0["applicable_steps"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 1, "action": "complete"})
        client.post(
            "/api/onboarding/step",
            headers=_auth_headers(r_tok),
            json={"step": 2, "action": "complete", "data": {"business_type": "retailer"}},
        )
        client.post(
            "/api/onboarding/step",
            headers=_auth_headers(r_tok),
            json={"step": 3, "action": "complete", "data": {"language": "hi"}},
        )
        # Required step cannot be skipped
        assert (
            client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 4, "action": "skip"}).status_code
            == 400
        )
        client.post(
            "/api/onboarding/step",
            headers=_auth_headers(r_tok),
            json={"step": 4, "action": "complete", "data": {"name": "Ramesh Mart", "contact_phone": "+919999000011"}},
        )
        client.post(
            "/api/onboarding/step",
            headers=_auth_headers(r_tok),
            json={"step": 5, "action": "complete", "data": {"currency": "INR", "low_stock_threshold_default": 8}},
        )

        # Step 6 duplicate submission check (must not duplicate SKU)
        prod_payload = {
            "products": [{"sku": "ATTA-5KG", "name": "Chakki Atta 5kg", "cost_price": 180, "selling_price": 220, "reorder_level": 8}]
        }
        s6a = client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 6, "action": "complete", "data": prod_payload}).json()
        assert s6a["step_data"]["products_summary"]["created_skus"] == ["ATTA-5KG"]
        s6b = client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 6, "action": "complete", "data": prod_payload}).json()
        assert s6b["step_data"]["products_summary"]["created_skus"] == []
        assert s6b["step_data"]["products_summary"]["skipped_duplicate_skus"] == ["ATTA-5KG"]

        # Optional Step 7 skip + go back + complete
        s7_skip = client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 7, "action": "skip"}).json()
        assert 7 in s7_skip["skipped_steps"]
        s7_back = client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 8, "action": "back"}).json()
        assert s7_back["current_step"] == 7

        client.post(
            "/api/onboarding/step",
            headers=_auth_headers(r_tok),
            json={"step": 7, "action": "complete", "data": {"suppliers": [{"name": "Bharat Mills", "lead_time_days": 4}]}},
        )
        # Opening stock Step 8 idempotency: running twice must NOT double stock
        os_data = {"opening_stocks": [{"sku": "ATTA-5KG", "quantity": 25}]}
        client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 8, "action": "complete", "data": os_data})
        client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 8, "action": "complete", "data": os_data})
        prods = client.get("/api/products/", headers=_auth_headers(r_tok)).json()["data"]
        assert len(prods) == 1
        assert prods[0]["current_stock"] == 25

        # Complete onboarding & confirm language persisted across fresh login
        client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 9, "action": "skip"})
        done = client.post("/api/onboarding/step", headers=_auth_headers(r_tok), json={"step": 10, "action": "complete"}).json()
        assert done["is_completed"] is True
        r_relogin = client.post("/api/auth/login", json={"email": "ramesh@retail.in", "password": "Password123!"}).json()
        assert r_relogin["user"]["preferred_language"] == "hi"
        r_tok = r_relogin["access_token"]

        # 3. Multi-workspace creation & switching + invalid workspace switch rejection
        biz2_res = client.post(
            "/api/businesses/",
            headers=_auth_headers(r_tok),
            json={"name": "Ramesh Wholesale Depot", "business_type": "wholesaler"},
        )
        assert biz2_res.status_code == 201
        biz2_id = biz2_res.json()["business"]["id"]
        assert len(client.get("/api/products/", headers=_auth_headers(r_tok)).json()["data"]) == 0  # isolated from biz1!

        assert client.post("/api/businesses/switch", headers=_auth_headers(r_tok), json={"business_id": 99999}).status_code == 403
        sw = client.post("/api/businesses/switch", headers=_auth_headers(r_tok), json={"business_id": biz1_id})
        assert sw.status_code == 200
        r_tok = sw.json()["access_token"]
        assert len(client.get("/api/products/", headers=_auth_headers(r_tok)).json()["data"]) == 1

        # 4. Invitations & RBAC hierarchy (Owner vs Admin vs Staff)
        client.post(
            "/api/auth/register",
            json={"name": "Asha Admin", "email": "asha@team.in", "password": "Password123!", "create_workspace": False},
        )
        asha_tok = client.post("/api/auth/login", json={"email": "asha@team.in", "password": "Password123!"}).json()["access_token"]

        inv_admin = client.post(
            "/api/members/invite",
            headers=_auth_headers(r_tok),
            json={"email": "asha@team.in", "role": "admin"},
        )
        assert inv_admin.status_code == 201
        inv_tok = inv_admin.json()["token"]
        assert client.post("/api/members/accept-invitation", headers=_auth_headers(asha_tok), json={"token": inv_tok}).status_code == 200

        # Admin can invite staff, but CANNOT invite another admin or modify owner
        assert (
            client.post(
                "/api/members/invite",
                headers=_auth_headers(asha_tok),
                json={"email": "someone@team.in", "role": "admin"},
            ).status_code
            == 403
        )
        members_list = client.get("/api/members/", headers=_auth_headers(asha_tok)).json()
        owner_member = next(m for m in members_list if m["role"] == "owner")
        assert (
            client.patch(
                f"/api/members/{owner_member['id']}/role",
                headers=_auth_headers(asha_tok),
                json={"role": "staff"},
            ).status_code
            == 403
        )
        assert client.delete(f"/api/members/{owner_member['id']}", headers=_auth_headers(asha_tok)).status_code == 403

        # 5. Comprehensive cross-tenant isolation & security checks across ALL resources (A vs B)
        client.post(
            "/api/auth/register",
            json={"name": "Competitor", "email": "comp@other.in", "password": "Password123!", "business_name": "Comp Mart"},
        )
        comp_tok = client.post("/api/auth/login", json={"email": "comp@other.in", "password": "Password123!"}).json()["access_token"]
        ramesh_prod_id = prods[0]["id"]
        # Record a sale in Ramesh's store so sales/logs/PO isolation can be tested against real IDs
        r_sale = client.post(
            "/api/sales/",
            headers=_auth_headers(r_tok),
            json={"product_id": ramesh_prod_id, "quantity_sold": 2},
        )
        assert r_sale.status_code == 200
        r_sale_id = r_sale.json()["data"]["id"]

        supp_id = client.get("/api/suppliers/", headers=_auth_headers(r_tok)).json()["data"][0]["id"]
        po = client.post(
            "/api/purchase-orders/",
            headers=_auth_headers(r_tok),
            json={
                "supplier_id": supp_id,
                "items": [{"product_id": ramesh_prod_id, "ordered_quantity": 20, "unit_cost": 175.0}],
            },
        ).json()
        # PO creation must NOT increase stock
        assert client.get(f"/api/products/{ramesh_prod_id}", headers=_auth_headers(r_tok)).json()["data"]["current_stock"] == 23

        # Competitor cannot read, update, deactivate, or access Ramesh's products, inventory, logs, sales, POs, forecasts, or workspace
        assert client.get(f"/api/products/{ramesh_prod_id}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.put(f"/api/products/{ramesh_prod_id}", headers=_auth_headers(comp_tok), json={"name": "Hack"}).status_code == 404
        assert client.patch(f"/api/products/deactivate/{ramesh_prod_id}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.get(f"/api/inventory/positions/{ramesh_prod_id}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.get(f"/api/inventory/logs/{ramesh_prod_id}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.get(f"/api/sales/{r_sale_id}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.post(f"/api/sales/{r_sale_id}/cancel", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.get(f"/api/purchase-orders/{po['id']}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.post(f"/api/purchase-orders/{po['id']}/send", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.post(f"/api/purchase-orders/{po['id']}/receive", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.get(f"/api/forecast/{ramesh_prod_id}", headers=_auth_headers(comp_tok)).status_code == 404
        assert client.get("/dashboard/summary", headers=_auth_headers(comp_tok)).json()["total_products"] == 0
        assert client.post("/api/businesses/switch", headers=_auth_headers(comp_tok), json={"business_id": biz1_id}).status_code == 403
        assert client.get("/api/products/", headers=_auth_headers(comp_tok, biz1_id)).status_code == 403
        # Retailer cannot access Supplier Portal
        assert client.get("/api/supplier-portal/purchase-orders", headers=_auth_headers(r_tok)).status_code == 403

        # 6. Supplier Workspace Onboarding + Explicit PO Sharing Collaboration
        client.post(
            "/api/auth/register",
            json={
                "name": "Supplier Owner",
                "email": "vendor@mills.in",
                "password": "Password123!",
                "role": "supplier",
                "business_name": "Bharat Mills Supplier Hub",
                "business_type": "supplier",
            },
        )
        sup_tok = client.post("/api/auth/login", json={"email": "vendor@mills.in", "password": "Password123!"}).json()["access_token"]
        sup_biz = client.get("/api/businesses/current", headers=_auth_headers(sup_tok)).json()["business"]
        sup_onb = client.get("/api/onboarding/progress", headers=_auth_headers(sup_tok)).json()
        # Supplier onboarding skips inventory/product/opening stock steps
        assert sup_onb["applicable_steps"] == [1, 2, 3, 4, 5, 9, 10]

        # Before explicit sharing -> supplier portal sees 0 orders and 404 on direct ID
        assert client.get("/api/supplier-portal/purchase-orders", headers=_auth_headers(sup_tok)).json() == []
        assert client.get(f"/api/supplier-portal/purchase-orders/{po['id']}", headers=_auth_headers(sup_tok)).status_code == 404

        # Link buyer's supplier vendor to supplier workspace & send PO (stock must STILL stay 23)
        assert (
            client.patch(
                f"/api/suppliers/{supp_id}/link-workspace",
                headers=_auth_headers(r_tok),
                json={"supplier_business_id": biz1_id},  # not a supplier-type business -> 400
            ).status_code
            == 400
        )
        link_res = client.patch(
            f"/api/suppliers/{supp_id}/link-workspace",
            headers=_auth_headers(r_tok),
            json={"supplier_business_id": sup_biz["id"]},
        )
        assert link_res.status_code == 200

        client.post(f"/api/purchase-orders/{po['id']}/send", headers=_auth_headers(r_tok))
        assert client.get(f"/api/products/{ramesh_prod_id}", headers=_auth_headers(r_tok)).json()["data"]["current_stock"] == 23
        # Still unshared until explicitly shared
        assert client.get("/api/supplier-portal/purchase-orders", headers=_auth_headers(sup_tok)).json() == []

        share_res = client.post(f"/api/purchase-orders/{po['id']}/share", headers=_auth_headers(r_tok))
        assert share_res.status_code == 200
        assert share_res.json()["shared_with_supplier"] is True

        # Supplier sees ONLY shared PO and cannot access buyer inventory/sales/products/forecasts/suppliers
        sup_orders = client.get("/api/supplier-portal/purchase-orders", headers=_auth_headers(sup_tok)).json()
        assert len(sup_orders) == 1
        assert sup_orders[0]["id"] == po["id"]
        assert client.get("/api/products/", headers=_auth_headers(sup_tok)).status_code == 403
        assert client.get("/api/sales/", headers=_auth_headers(sup_tok)).status_code == 403
        assert client.get("/api/inventory/positions", headers=_auth_headers(sup_tok)).status_code == 403
        assert client.get("/api/suppliers/", headers=_auth_headers(sup_tok)).status_code == 403
        assert client.get("/api/purchase-orders/", headers=_auth_headers(sup_tok)).status_code == 403
        assert client.get(f"/api/forecast/{ramesh_prod_id}", headers=_auth_headers(sup_tok)).status_code == 403

        # Supplier updates acknowledgement & dispatch status; buyer receives goods -> stock increases ONLY on receipt
        ack = client.post(
            f"/api/supplier-portal/purchase-orders/{po['id']}/status",
            headers=_auth_headers(sup_tok),
            json={"supplier_status": "ACKNOWLEDGED", "notes": "Confirmed stock ready"},
        )
        assert ack.status_code == 200
        assert ack.json()["supplier_status"] == "ACKNOWLEDGED"
        assert len(ack.json()["actions"]) == 1

        recv = client.post(f"/api/purchase-orders/{po['id']}/receive", headers=_auth_headers(r_tok))
        assert recv.status_code == 200
        assert client.get(f"/api/products/{ramesh_prod_id}", headers=_auth_headers(r_tok)).json()["data"]["current_stock"] == 43
    finally:
        app.dependency_overrides.clear()
