from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db
from app.dependencies.authorization import BusinessContext
from app.main import app
from app.ml.decision_service import InventoryDecisionService
from app.ml.recommendation_service import RecommendationLifecycleService
from app.routers.decision import get_all_reorder_recommendations
from app.routers.forecast import get_product_demand_forecast
from app.routers.intelligence import get_product_intelligence_forecast
from app.routers.inventory import get_product_inventory_position
from app.services.inventory_service import InventoryService


def _make_test_env():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal, engine


def _register_and_login(client: TestClient, email: str, biz_name: str):
    reg = client.post(
        "/api/auth/register",
        json={
            "name": "Regression Owner",
            "email": email,
            "password": "Password123!",
            "business_name": biz_name,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    data = login.json()
    return {
        "Authorization": f"Bearer {data['access_token']}",
    }, data["user"]["active_business_id"]


def test_direct_router_calls_resolve_clean_query_defaults():
    client, SessionLocal, _engine = _make_test_env()
    try:
        hdrs, biz_id = _register_and_login(client, "query_defaults@sims.in", "Defaults Store")
        prod = client.post(
            "/api/products/",
            headers=hdrs,
            json={"sku": "QDEF-1", "name": "Query Test Item", "cost_price": 20.0, "selling_price": 30.0, "current_stock": 25},
        ).json()["data"]
        client.post(
            "/api/sales/",
            headers=hdrs,
            json={"product_id": prod["id"], "quantity_sold": 2},
        )

        with SessionLocal() as db:
            user = db.query(models.User).filter(models.User.email == "query_defaults@sims.in").first()
            biz = db.query(models.Business).filter(models.Business.id == biz_id).first()
            membership = (
                db.query(models.BusinessMember)
                .filter(models.BusinessMember.business_id == biz_id)
                .first()
            )
            assert user is not None and biz is not None and membership is not None
            ctx = BusinessContext(
                user=user,
                business=biz,
                membership=membership,
                business_id=biz_id,
                role="owner",
            )

            res_forecast = get_product_demand_forecast(product_id=prod["id"], db=db, ctx=ctx)
            assert res_forecast["status"] == "success"
            assert res_forecast["data"]["horizon_days"] == 30

            res_intel = get_product_intelligence_forecast(product_id=prod["id"], db=db, ctx=ctx)
            assert res_intel["status"] == "success"
            assert res_intel["data"]["horizon_days"] == 30

            res_decision = get_all_reorder_recommendations(db=db, ctx=ctx)
            assert res_decision["status"] == "success"
            assert isinstance(res_decision["service_level"], float)
    finally:
        app.dependency_overrides.clear()


def test_inventory_position_raises_404_instead_of_index_error(monkeypatch):
    client, SessionLocal, _engine = _make_test_env()
    try:
        _hdrs, biz_id = _register_and_login(client, "inv404@sims.in", "Inv404 Store")
        monkeypatch.setattr(InventoryService, "get_inventory_positions", lambda **kwargs: [])

        with SessionLocal() as db:
            user = db.query(models.User).filter(models.User.email == "inv404@sims.in").first()
            biz = db.query(models.Business).filter(models.Business.id == biz_id).first()
            membership = (
                db.query(models.BusinessMember)
                .filter(models.BusinessMember.business_id == biz_id)
                .first()
            )
            assert user is not None and biz is not None and membership is not None
            ctx = BusinessContext(
                user=user,
                business=biz,
                membership=membership,
                business_id=biz_id,
                role="owner",
            )

            with pytest.raises(HTTPException) as exc_info:
                get_product_inventory_position(product_id=99999, db=db, ctx=ctx)
            assert exc_info.value.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_dashboard_metrics_query_consolidation_and_case_insensitive_cancelled_sales():
    client, SessionLocal, engine = _make_test_env()
    try:
        hdrs, biz_id = _register_and_login(client, "dash_opt@sims.in", "Dash Opt Store")
        sup = client.post("/api/suppliers/", headers=hdrs, json={"name": "Dash Supplier"}).json()["data"]
        p1 = client.post(
            "/api/products/",
            headers=hdrs,
            json={
                "sku": "DASH-1",
                "name": "Active Item",
                "cost_price": 10.0,
                "selling_price": 20.0,
                "current_stock": 5,
                "reorder_level": 10,
                "supplier_id": sup["id"],
            },
        ).json()["data"]
        p2 = client.post(
            "/api/products/",
            headers=hdrs,
            json={
                "sku": "DASH-2",
                "name": "Healthy Item",
                "cost_price": 15.0,
                "selling_price": 30.0,
                "current_stock": 50,
                "reorder_level": 10,
                "supplier_id": sup["id"],
            },
        ).json()["data"]

        with SessionLocal() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add_all(
                [
                    models.Sale(
                        business_id=biz_id,
                        product_id=p1["id"],
                        sales_date=now,
                        quantity_sold=2,
                        selling_price=20.0,
                        revenue=40.0,
                        status="COMPLETED",
                    ),
                    models.Sale(
                        business_id=biz_id,
                        product_id=p2["id"],
                        sales_date=now - timedelta(days=3),
                        quantity_sold=1,
                        selling_price=30.0,
                        revenue=30.0,
                        status="cancelled",
                    ),
                    models.Sale(
                        business_id=biz_id,
                        product_id=p2["id"],
                        sales_date=now - timedelta(days=10),
                        quantity_sold=3,
                        selling_price=30.0,
                        revenue=90.0,
                        status="CANCELLED",
                    ),
                ]
            )
            db.commit()

        sql_statements = []

        def _track(conn, cursor, statement, parameters, context, executemany):
            sql_statements.append(statement)

        event.listen(engine, "before_cursor_execute", _track)
        try:
            summary_res = client.get("/dashboard/summary", headers=hdrs)
            assert summary_res.status_code == 200
            summary_selects = [s for s in sql_statements if s.lstrip().upper().startswith("SELECT")]
            # auth user lookup + business lookup + member lookup + 2 consolidated summary queries
            assert any("COUNT(" in s.upper() and "SUM(" in s.upper() for s in summary_selects)
            dash = summary_res.json()
            assert dash["total_products"] == 2
            assert dash["low_stock_products"] == 1
            assert dash["total_sales"] == 1
            assert dash["total_revenue"] == 40.0

            sql_statements.clear()
            sales_m_res = client.get("/dashboard/sales-metrics", headers=hdrs)
            assert sales_m_res.status_code == 200
            sm_data = sales_m_res.json()
            assert sm_data["sales_count_today"] == 1
            assert sm_data["sales_count_this_week"] == 1
            assert sm_data["sales_count_this_month"] == 1
            assert sm_data["todays_revenue"] == 40.0
            sale_selects = [s for s in sql_statements if "FROM sales" in s]
            assert len(sale_selects) == 1, f"Expected single-pass sales metrics query, got {len(sale_selects)}"
        finally:
            event.remove(engine, "before_cursor_execute", _track)

        root_res = client.get("/")
        assert root_res.status_code == 200
        assert "4-Algorithm Demand Forecasting (ARIMA, XGBoost, Random Forest, LSTM)" in root_res.json()["features"]
    finally:
        app.dependency_overrides.clear()


def test_intelligence_overview_single_decision_pass_and_constant_rec_queries(monkeypatch):
    client, SessionLocal, engine = _make_test_env()
    try:
        hdrs, biz_id = _register_and_login(client, "intel_opt@sims.in", "Intel Opt Store")
        sup = client.post("/api/suppliers/", headers=hdrs, json={"name": "Opt Vendor"}).json()["data"]
        for i in range(6):
            client.post(
                "/api/products/",
                headers=hdrs,
                json={
                    "sku": f"OPT-{i}",
                    "name": f"Opt Item {i}",
                    "cost_price": 10.0,
                    "selling_price": 20.0,
                    "current_stock": 2,
                    "reorder_level": 10,
                    "supplier_id": sup["id"],
                },
            )

        orig_get_all = InventoryDecisionService.get_all_recommendations
        call_count = 0

        def _counting_get_all(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return orig_get_all(*args, **kwargs)

        monkeypatch.setattr(InventoryDecisionService, "get_all_recommendations", _counting_get_all)
        ov = client.get("/api/intelligence/overview?sync=true", headers=hdrs)
        assert ov.status_code == 200
        assert call_count == 1, f"Expected 1 decision evaluation pass during sync=true overview, got {call_count}"

        # Now verify sync_workspace_recommendations executes constant queries on replenishment_recommendations
        rec_selects = []

        def _track_rec(conn, cursor, statement, parameters, context, executemany):
            if "FROM replenishment_recommendations" in statement and statement.lstrip().upper().startswith("SELECT"):
                rec_selects.append(statement)

        with SessionLocal() as db:
            decisions = orig_get_all(db=db, business_id=biz_id)
            event.listen(engine, "before_cursor_execute", _track_rec)
            try:
                RecommendationLifecycleService.sync_workspace_recommendations(
                    db=db,
                    business_id=biz_id,
                    decisions=decisions,
                )
            finally:
                event.remove(engine, "before_cursor_execute", _track_rec)
            # 1 prefetch SELECT + 1 list_recommendations SELECT = 2 (not 2*N + 2)
            assert len(rec_selects) == 2, f"Expected constant 2 SELECT queries on recommendations, got {len(rec_selects)}"
    finally:
        app.dependency_overrides.clear()
