import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db
from app.main import app
from app.services.procurement_service import ProcurementService


def _make_client():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), testing_session, engine


def _headers(token: str, biz_id: int | None = None) -> dict[str, str]:
    hdrs = {"Authorization": f"Bearer {token}"}
    if biz_id is not None:
        hdrs["X-Business-Id"] = str(biz_id)
    return hdrs


def _register_owner(client: TestClient, email: str, biz_name: str, btype: str = "retailer"):
    reg = client.post(
        "/api/auth/register",
        json={
            "name": biz_name,
            "email": email,
            "password": "Password123!",
            "role": "supplier" if btype == "supplier" else "owner",
            "business_name": biz_name,
            "business_type": btype,
        },
    )
    assert reg.status_code == 201, reg.text
    tok = client.post("/api/auth/login", json={"email": email, "password": "Password123!"}).json()["access_token"]
    ws = client.get("/api/businesses/current", headers=_headers(tok)).json()
    return tok, ws["business"]["id"]


def test_stock_alerts_read_dismiss_cooldown_and_reescalation():
    client, _session_maker, _engine = _make_client()
    try:
        tok_a, _ = _register_owner(client, "alerts_a@sims.in", "Alerts Mart A")
        tok_b, _ = _register_owner(client, "alerts_b@sims.in", "Alerts Mart B")

        p1 = client.post(
            "/api/products/",
            headers=_headers(tok_a),
            json={"sku": "LOW-01", "name": "Low Stock Item", "current_stock": 3, "reorder_level": 10},
        ).json()["data"]
        p2 = client.post(
            "/api/products/",
            headers=_headers(tok_a),
            json={"sku": "LOW-02", "name": "Another Low Item", "current_stock": 2, "reorder_level": 10},
        ).json()["data"]

        # 1. Both alerts visible & unread initially; tenant B sees zero alerts
        alerts_res = client.get("/api/inventory/alerts", headers=_headers(tok_a))
        assert alerts_res.status_code == 200
        body = alerts_res.json()
        assert body["active_count"] == 2
        assert body["unread_count"] == 2
        assert client.get("/api/inventory/alerts", headers=_headers(tok_b)).json()["active_count"] == 0

        # 2. Mark single alert read -> persists across subsequent reloads
        read_res = client.post(
            "/api/inventory/alerts/read",
            headers=_headers(tok_a),
            json={"alert_key": f"low_stock:{p1['id']}", "product_id": p1["id"]},
        )
        assert read_res.status_code == 200
        after_read = client.get("/api/inventory/alerts", headers=_headers(tok_a)).json()
        assert after_read["unread_count"] == 1
        row_p1 = next(a for a in after_read["alerts"] if a["product_id"] == p1["id"])
        assert row_p1["is_read"] is True

        # 3. Dismiss p1 -> disappears from default active list and stays suppressed
        dis_res = client.post(
            "/api/inventory/alerts/dismiss",
            headers=_headers(tok_a),
            json={
                "alert_key": f"low_stock:{p1['id']}",
                "product_id": p1["id"],
                "severity": "LOW_STOCK",
                "current_stock": 3,
                "cooldown_days": 7,
            },
        )
        assert dis_res.status_code == 200
        after_dismiss = client.get("/api/inventory/alerts", headers=_headers(tok_a)).json()
        assert after_dismiss["active_count"] == 1
        assert after_dismiss["dismissed_count"] == 1
        assert all(a["product_id"] != p1["id"] for a in after_dismiss["alerts"])

        # Can inspect dismissed when include_dismissed=true
        all_alerts = client.get("/api/inventory/alerts?include_dismissed=true", headers=_headers(tok_a)).json()
        assert len(all_alerts["alerts"]) == 2

        # 4. If stock drops further (or escalates to OUT_OF_STOCK), alert re-activates automatically
        adj = client.post(
            "/api/inventory/adjust",
            headers=_headers(tok_a),
            json={"product_id": p1["id"], "quantity_delta": -3, "reason": "shrinkage"},
        )
        assert adj.status_code == 200
        re_escalated = client.get("/api/inventory/alerts", headers=_headers(tok_a)).json()
        assert re_escalated["active_count"] == 2
        row_p1_esc = next(a for a in re_escalated["alerts"] if a["product_id"] == p1["id"])
        assert row_p1_esc["severity"] == "OUT_OF_STOCK"
        assert row_p1_esc["is_read"] is False

        # 5. Reopen explicitly works after dismiss
        client.post(
            "/api/inventory/alerts/dismiss",
            headers=_headers(tok_a),
            json={"alert_key": f"low_stock:{p2['id']}", "product_id": p2["id"]},
        )
        client.post(
            "/api/inventory/alerts/reopen",
            headers=_headers(tok_a),
            json={"alert_key": f"low_stock:{p2['id']}"},
        )
        assert client.get("/api/inventory/alerts", headers=_headers(tok_a)).json()["active_count"] == 2
    finally:
        app.dependency_overrides.clear()


def test_csv_product_import_quotes_duplicates_validation_and_opening_stock():
    client, _session_maker, _engine = _make_client()
    try:
        tok, _ = _register_owner(client, "csv@sims.in", "CSV Mart")
        client.post("/api/suppliers/", headers=_headers(tok), json={"name": "Prime Foods"})

        csv_bytes = (
            '\ufeffsku,name,category,unit,cost_price,selling_price,current_stock,reorder_level,supplier_name\n'
            'IMP-01,"Basmati, Reserve 5kg",Grains,bag,320,399,18,5,Prime Foods\n'
            'IMP-02,Olive Oil 1L,Grocery,bottle,450,560,0,4,\n'
            'IMP-01,"Duplicate Row",Grains,bag,300,350,5,5,\n'
            'BAD-NEG,"Bad Negative Stock",General,piece,10,20,-3,5,\n'
        ).encode("utf-8")

        res = client.post(
            "/api/products/import-csv",
            headers=_headers(tok),
            files={"file": ("catalog.csv", csv_bytes, "text/csv")},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["created_count"] == 2
        assert data["skipped_count"] == 1
        assert data["error_count"] == 2
        assert set(data["created_skus"]) == {"IMP-01", "IMP-02"}

        prods = client.get("/api/products/", headers=_headers(tok)).json()["data"]
        p1 = next(p for p in prods if p["sku"] == "IMP-01")
        assert p1["name"] == "Basmati, Reserve 5kg"
        assert p1["current_stock"] == 18

        logs = client.get(f"/api/inventory/logs/{p1['id']}", headers=_headers(tok)).json()
        assert any(l["movement_type"] == "OPENING_STOCK" and l["stock_in"] == 18 for l in logs)
    finally:
        app.dependency_overrides.clear()


def test_supplier_portal_list_eliminates_n_plus_one_queries():
    client, session_maker, engine = _make_client()
    try:
        buyer_tok, _ = _register_owner(client, "buyer_q@sims.in", "Buyer Corp")
        sup_tok, sup_biz_id = _register_owner(client, "sup_q@sims.in", "Vendor Hub", btype="supplier")

        supp = client.post("/api/suppliers/", headers=_headers(buyer_tok), json={"name": "Vendor Hub"}).json()["data"]
        client.patch(
            f"/api/suppliers/{supp['id']}/link-workspace",
            headers=_headers(buyer_tok),
            json={"supplier_business_id": sup_biz_id},
        )
        prod_ids = []
        for idx in range(5):
            prod = client.post(
                "/api/products/",
                headers=_headers(buyer_tok),
                json={"sku": f"Q-SKU-{idx}", "name": f"Item {idx}", "supplier_id": supp["id"]},
            ).json()["data"]
            prod_ids.append(prod["id"])

        for pid in prod_ids:
            po = client.post(
                "/api/purchase-orders/",
                headers=_headers(buyer_tok),
                json={
                    "supplier_id": supp["id"],
                    "items": [{"product_id": pid, "ordered_quantity": 10, "unit_cost": 25.0}],
                },
            ).json()
            client.post(f"/api/purchase-orders/{po['id']}/send", headers=_headers(buyer_tok))
            client.post(f"/api/purchase-orders/{po['id']}/share", headers=_headers(buyer_tok))

        # Count SQL statements executed by ProcurementService.list_supplier_portal_orders for 5 shared POs
        query_count = 0

        def _count_queries(conn, cursor, statement, parameters, context, executemany):
            nonlocal query_count
            query_count += 1

        event.listen(engine, "before_cursor_execute", _count_queries)
        try:
            with session_maker() as db:
                rows = ProcurementService.list_supplier_portal_orders(db, sup_biz_id)
                assert len(rows) == 5
        finally:
            event.remove(engine, "before_cursor_execute", _count_queries)

        # Constant query count (main join + selectinload items + selectinload actions + 1 batch Product query <= 5)
        assert query_count <= 5, f"Expected <=5 queries for 5 POs, got {query_count}"
    finally:
        app.dependency_overrides.clear()
