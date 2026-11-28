from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.core.security import create_access_token
from app.database import get_db
from app.db_migrate import ensure_schema_and_backfill
from app.main import app
from app.ml.base_model import BaseForecastingModel
from app.ml.decision_service import InventoryDecisionService
from app.ml.evaluation_service import ModelEvaluationService
from app.ml.feature_service import FeatureEngineeringService
from app.ml.forecasting_service import ForecastingService
from app.ml.ingestion_service import DataIngestionService
from app.ml.lead_time_service import SupplierLeadTimeService
from app.ml.preprocess_service import DataPreprocessingService
from app.ml.recommendation_service import RecommendationLifecycleService
from app.ml.models import CrostonSBAForecaster, NaiveForecaster
from app.services.procurement_service import ProcurementService
from app.services.sales_service import SalesService


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def isolated_db():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_schema_and_backfill(eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = Session()
    try:
        yield db, eng
    finally:
        db.close()
        eng.dispose()


def _seed_two_tenants(db):
    u1 = models.User(name="Owner A", email="ownera@example.com", password_hash="x", role="owner", is_active=True)
    u2 = models.User(name="Owner B", email="ownerb@example.com", password_hash="x", role="owner", is_active=True)
    u_staff = models.User(name="Staff A", email="staffa@example.com", password_hash="x", role="staff", is_active=True)
    u_sup = models.User(name="Sup Portal", email="sup@example.com", password_hash="x", role="supplier", is_active=True)
    db.add_all([u1, u2, u_staff, u_sup])
    db.flush()

    b1 = models.Business(name="Tenant A Retail", business_type="retailer", owner_user_id=u1.id, onboarding_completed=True)
    b2 = models.Business(name="Tenant B Wholesale", business_type="wholesaler", owner_user_id=u2.id, onboarding_completed=True)
    b_sup = models.Business(name="Supplier Co", business_type="supplier", owner_user_id=u_sup.id, onboarding_completed=True)
    db.add_all([b1, b2, b_sup])
    db.flush()

    setattr(u1, "active_business_id", b1.id)
    setattr(u2, "active_business_id", b2.id)
    setattr(u_staff, "active_business_id", b1.id)
    setattr(u_sup, "active_business_id", b_sup.id)

    db.add_all([
        models.BusinessMember(business_id=b1.id, user_id=u1.id, role="owner", is_active=True),
        models.BusinessMember(business_id=b1.id, user_id=u_staff.id, role="staff", is_active=True),
        models.BusinessMember(business_id=b2.id, user_id=u2.id, role="owner", is_active=True),
        models.BusinessMember(business_id=b_sup.id, user_id=u_sup.id, role="owner", is_active=True),
    ])

    sup1 = models.Supplier(business_id=b1.id, name="Reliable Foods", lead_time_days=5, is_active=True)
    sup2 = models.Supplier(business_id=b2.id, name="B Vendor", lead_time_days=8, is_active=True)
    db.add_all([sup1, sup2])
    db.flush()

    # Tenant A: Established brisk product, Cold-start product, Stagnant overstock product
    old_created = _utcnow() - timedelta(days=75)
    p_brisk = models.Product(
        business_id=b1.id,
        sku="A-BRISK-01",
        name="Basmati Rice 5kg",
        category="Grains",
        unit="bag",
        cost_price=300.0,
        selling_price=420.0,
        current_stock=12,
        reorder_level=15,
        min_order_quantity=10,
        order_pack_size=5,
        review_period_days=7,
        service_level_target=0.95,
        supplier_id=sup1.id,
        created_at=old_created,
    )
    p_cold = models.Product(
        business_id=b1.id,
        sku="A-COLD-02",
        name="New Saffron Tin",
        category="Spices",
        unit="tin",
        cost_price=500.0,
        selling_price=800.0,
        current_stock=0,
        reorder_level=5,
        supplier_id=sup1.id,
        created_at=_utcnow() - timedelta(days=2),
    )
    p_over = models.Product(
        business_id=b1.id,
        sku="A-OVER-03",
        name="Excess Ceramic Jar",
        category="Kitchen",
        unit="piece",
        cost_price=100.0,
        selling_price=180.0,
        current_stock=350,
        reorder_level=10,
        supplier_id=sup1.id,
        created_at=old_created,
    )
    p_b = models.Product(
        business_id=b2.id,
        sku="B-ONLY-01",
        name="Tenant B Steel Rod",
        category="Hardware",
        unit="piece",
        cost_price=200.0,
        selling_price=300.0,
        current_stock=5,
        reorder_level=10,
        supplier_id=sup2.id,
        created_at=old_created,
    )
    db.add_all([p_brisk, p_cold, p_over, p_b])
    db.flush()

    now = _utcnow()
    # Add 70 days of sales for p_brisk + 1 cancelled outlier + 2 same-day sales
    for d_back in range(70, 0, -1):
        dt = now - timedelta(days=d_back)
        qty = 4 + (1 if d_back % 3 == 0 else 0)
        db.add(
            models.Sale(
                business_id=b1.id,
                product_id=p_brisk.id,
                sales_date=dt,
                quantity_sold=qty,
                selling_price=420.0,
                revenue=qty * 420.0,
                status="COMPLETED",
            )
        )
    # Same-day extra completed sale + massive cancelled sale (must be excluded!)
    db.add(
        models.Sale(
            business_id=b1.id,
            product_id=p_brisk.id,
            sales_date=now - timedelta(days=1),
            quantity_sold=2,
            selling_price=420.0,
            revenue=840.0,
            status="COMPLETED",
        )
    )
    db.add(
        models.Sale(
            business_id=b1.id,
            product_id=p_brisk.id,
            sales_date=now - timedelta(days=2),
            quantity_sold=500,
            selling_price=420.0,
            revenue=210000.0,
            status="CANCELLED",
        )
    )
    # Tenant B sales that must NEVER pollute Tenant A
    for d_back in range(20, 0, -1):
        db.add(
            models.Sale(
                business_id=b2.id,
                product_id=p_b.id,
                sales_date=now - timedelta(days=d_back),
                quantity_sold=25,
                selling_price=300.0,
                revenue=7500.0,
                status="COMPLETED",
            )
        )

    db.commit()
    return {
        "u1": u1,
        "u2": u2,
        "u_staff": u_staff,
        "u_sup": u_sup,
        "b1": b1,
        "b2": b2,
        "sup1": sup1,
        "p_brisk": p_brisk,
        "p_cold": p_cold,
        "p_over": p_over,
        "p_b": p_b,
    }


def test_ingestion_excludes_cancelled_and_isolates_tenant_and_trailing_zeros(isolated_db):
    db, _ = isolated_db
    env = _seed_two_tenants(db)

    raw_a = DataIngestionService.load_from_database(db, business_id=env["b1"].id, product_id=env["p_brisk"].id)
    assert not raw_a.empty
    assert (raw_a["business_id"] == env["b1"].id).all()
    assert raw_a["quantity"].max() <= 10  # 500-unit CANCELLED sale strictly excluded!

    # Cross-tenant guard: asking for Tenant B's product under Tenant A business_id returns empty
    raw_cross = DataIngestionService.load_from_database(db, business_id=env["b1"].id, product_id=env["p_b"].id)
    assert raw_cross.empty

    # Stagnant product whose last sale was 40 days ago MUST carry trailing zero days up to cutoff_date
    today = _utcnow().date()
    old_only_df = pd.DataFrame([{"date": today - timedelta(days=40), "product_id": 999, "quantity": 20, "total_amount": 200}])
    daily_stagnant = DataPreprocessingService.prepare_daily_series(
        old_only_df,
        product_id=999,
        as_of_date=today,
        product_created_at=today - timedelta(days=40),
    )
    assert len(daily_stagnant) == 41
    assert daily_stagnant["raw_demand"].iloc[-1] == 0.0
    assert abs(daily_stagnant["raw_demand"].mean() - (20.0 / 41.0)) < 0.01


def test_feature_engineering_zero_future_leakage_and_zero_safe_metrics():
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    base_df = pd.DataFrame({"date": dates, "demand": [float((i % 5) + 1) for i in range(30)]})
    perturbed_df = base_df.copy()
    perturbed_df.loc[15:, "demand"] = 999.0  # Massive spike strictly in future

    feat_base = FeatureEngineeringService.create_features(base_df)
    feat_perturbed = FeatureEngineeringService.create_features(perturbed_df)
    feature_cols = FeatureEngineeringService.get_feature_columns()

    # Every row t < 15 MUST have identical features when only t >= 15 changes (zero bfill/lookahead leak)
    pd.testing.assert_frame_equal(
        feat_base.loc[:14, feature_cols],
        feat_perturbed.loc[:14, feature_cols],
    )
    assert feat_base[feature_cols].isna().sum().sum() == 0

    # Zero-safe evaluation must return mape=None (never fabricated 0.0) when all y_true == 0
    m = NaiveForecaster().evaluate(np.zeros(7), np.array([1.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0]))
    assert m["mape"] is None
    assert m["wape"] is None
    assert m["mae"] > 0.0


def test_cold_start_limited_and_intermittent_sufficiencies_and_rolling_cv(isolated_db):
    db, _ = isolated_db
    env = _seed_two_tenants(db)

    # 1. Cold-start SKU (0 sales, no initial estimate) -> no crash, honest 0 demand, ColdStartEstimator
    f_cold = ForecastingService.generate_product_forecast(
        db, env["p_cold"].id, horizon_days=14, business_id=env["b1"].id
    )
    assert f_cold["is_cold_start"] is True
    assert f_cold["data_sufficiency"] == "NEW"
    assert f_cold["model_used"] == "ColdStartEstimator"
    assert f_cold["expected_total_demand"] == 0.0

    # Configure explicit initial_daily_demand -> uses configured value instead of dummy constant
    env["p_cold"].initial_daily_demand = 2.0
    db.commit()
    f_cold_est = ForecastingService.generate_product_forecast(
        db, env["p_cold"].id, horizon_days=14, business_id=env["b1"].id
    )
    assert f_cold_est["avg_predicted_daily_demand"] == 2.0
    assert f_cold_est["expected_total_demand"] == 28.0

    # 2. Intermittent demand -> CrostonSBA & LIMITED sufficiency gating
    sparse_dates = pd.date_range("2026-08-01", periods=21, freq="D")
    limited_df = pd.DataFrame({"date": sparse_dates, "demand": [3.0 if i % 4 == 0 else 0.0 for i in range(21)]})
    ev_lim = ModelEvaluationService.evaluate_all_models(
        limited_df, data_sufficiency="LIMITED", max_folds=2
    )
    skipped = {r["model_name"] for r in ev_lim["leaderboard"] if r["status"] == "SKIPPED_INSUFFICIENT_DATA"}
    assert "LSTMSequenceNetwork" in skipped
    assert "XGBoost" in skipped
    assert ev_lim["champion_model"] != "Naive"

    # 3. Established/Seasonal SKU -> persists forecast & evaluation, cache hit on repeat read, invalidates on new sale
    f1 = ForecastingService.generate_product_forecast(
        db, env["p_brisk"].id, horizon_days=30, business_id=env["b1"].id
    )
    assert f1["cached"] is False
    assert f1["data_sufficiency"] == "SEASONAL"
    assert f1["avg_predicted_daily_demand"] > 2.0

    f2 = ForecastingService.generate_product_forecast(
        db, env["p_brisk"].id, horizon_days=30, business_id=env["b1"].id
    )
    assert f2["cached"] is True

    # Record a real new sale -> cache must invalidate automatically
    SalesService.create_sale(
        db=db,
        business_id=env["b1"].id,
        user_id=env["u1"].id,
        allow_negative_stock=False,
        payload=schemas.SaleCreate(product_id=env["p_brisk"].id, quantity_sold=1),
    )
    f3 = ForecastingService.generate_product_forecast(
        db, env["p_brisk"].id, horizon_days=30, business_id=env["b1"].id
    )
    assert f3["cached"] is False


def test_empirical_supplier_lead_time_and_moq_pack_and_inventory_position(isolated_db):
    db, _ = isolated_db
    env = _seed_two_tenants(db)
    sup1 = env["sup1"]
    p_brisk = env["p_brisk"]

    # Initially no PO receipts -> falls back cleanly to supplier_default = 5.0d
    lt_default = SupplierLeadTimeService.get_supplier_lead_time_stats(db, env["b1"].id, sup1.id)
    assert lt_default["lead_time_source"] == "supplier_default"
    assert lt_default["effective_lead_time_days"] == 5.0

    # Create 2 completed POs with 6-day and 8-day real receipt intervals (1 late out of 2)
    now = _utcnow()
    for idx, (lead_d, exp_d) in enumerate([(6, 5), (8, 10)], start=1):
        sent = now - timedelta(days=30 - idx * 10)
        rec_dt = sent + timedelta(days=lead_d)
        po = models.PurchaseOrder(
            business_id=env["b1"].id,
            order_number=f"PO-HIST-{idx}",
            supplier_id=sup1.id,
            status=models.PurchaseOrderStatus.RECEIVED,
            total_amount=3000.0,
            order_date=sent,
            sent_at=sent,
            expected_delivery_date=sent + timedelta(days=exp_d),
            received_at=rec_dt,
        )
        db.add(po)
        db.flush()
        db.add(
            models.GoodsReceipt(
                receipt_number=f"GR-HIST-{idx}",
                business_id=env["b1"].id,
                purchase_order_id=po.id,
                received_at=rec_dt,
            )
        )
    db.commit()

    lt_emp = SupplierLeadTimeService.get_supplier_lead_time_stats(db, env["b1"].id, sup1.id)
    assert lt_emp["lead_time_source"] == "po_receipt_history"
    assert lt_emp["effective_lead_time_days"] == 7.0
    assert round(lt_emp["lead_time_std_days"], 2) == round(float(np.std([6.0, 8.0], ddof=1)), 2)
    assert lt_emp["on_time_delivery_rate"] == 0.5

    # DRAFT PO must NOT count toward incoming stock; SENT & PARTIALLY_RECEIVED DO
    draft_po = ProcurementService.create_purchase_order(
        db,
        env["b1"].id,
        env["u1"].id,
        schemas.PurchaseOrderCreate(
            supplier_id=sup1.id,
            items=[schemas.PurchaseOrderItemCreate(product_id=p_brisk.id, ordered_quantity=25, unit_cost=300.0)],
        ),
    )
    m_with_draft = InventoryDecisionService.calculate_product_decision_metrics(
        db, p_brisk.id, business_id=env["b1"].id
    )
    assert m_with_draft["incoming_stock"] == 0
    assert m_with_draft["inventory_position"] == p_brisk.current_stock

    # Respects MOQ=10 and Pack=5 constraints
    if m_with_draft["recommended_order_quantity"] > 0:
        assert m_with_draft["recommended_order_quantity"] >= 10
        assert m_with_draft["recommended_order_quantity"] % 5 == 0

    # Send the draft PO -> incoming increases by 25, reducing or clearing further order need
    ProcurementService.send_purchase_order(db, env["b1"].id, draft_po.id)
    m_with_sent = InventoryDecisionService.calculate_product_decision_metrics(
        db, p_brisk.id, business_id=env["b1"].id
    )
    assert m_with_sent["incoming_stock"] == 25
    assert m_with_sent["inventory_position"] == p_brisk.current_stock + 25


def test_recommendation_lifecycle_dedup_and_po_confirmation_never_mutates_stock(isolated_db):
    db, _ = isolated_db
    env = _seed_two_tenants(db)
    p_brisk = env["p_brisk"]
    initial_stock = p_brisk.current_stock

    # Sync twice -> strictly deduplicated open recommendations
    recs1 = RecommendationLifecycleService.sync_workspace_recommendations(db, env["b1"].id)
    recs2 = RecommendationLifecycleService.sync_workspace_recommendations(db, env["b1"].id)
    assert len(recs1) == len(recs2)
    reorder_rec = next(r for r in recs2 if r["product_id"] == p_brisk.id and r["recommendation_type"] == "REORDER_NOW")
    assert reorder_rec["suggested_order_qty"] >= 10

    # Accept then Convert to DRAFT PO -> stock MUST NOT change; converts idempotently
    accepted = RecommendationLifecycleService.accept_recommendation(
        db, env["b1"].id, env["u1"].id, reorder_rec["id"], adjusted_order_qty=30
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["adjusted_order_qty"] == 30

    conv = RecommendationLifecycleService.convert_recommendation_to_po(
        db, env["b1"].id, env["u1"].id, reorder_rec["id"], ordered_quantity=30
    )
    assert conv["status"] == "success"
    po_id = conv["purchase_order_id"]

    db.refresh(p_brisk)
    assert p_brisk.current_stock == initial_stock  # Strictly unchanged on Draft PO creation!

    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    assert po.status == models.PurchaseOrderStatus.DRAFT

    # Duplicate conversion attempt returns 409 Conflict
    with pytest.raises(Exception) as exc_info:
        RecommendationLifecycleService.convert_recommendation_to_po(
            db, env["b1"].id, env["u1"].id, reorder_rec["id"]
        )
    assert "409" in str(exc_info.value)


def test_intelligence_api_tenant_isolation_and_rbac(isolated_db):
    db, _ = isolated_db
    env = _seed_two_tenants(db)

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        client = TestClient(app)
        tok_a = create_access_token({"sub": str(env["u1"].id), "token_version": 1})
        tok_b = create_access_token({"sub": str(env["u2"].id), "token_version": 1})
        tok_staff = create_access_token({"sub": str(env["u_staff"].id), "token_version": 1})
        tok_sup = create_access_token({"sub": str(env["u_sup"].id), "token_version": 1})

        hdr_a = {"Authorization": f"Bearer {tok_a}", "X-Business-Id": str(env["b1"].id)}
        hdr_b = {"Authorization": f"Bearer {tok_b}", "X-Business-Id": str(env["b2"].id)}
        hdr_staff = {"Authorization": f"Bearer {tok_staff}", "X-Business-Id": str(env["b1"].id)}
        hdr_sup = {"Authorization": f"Bearer {tok_sup}"}

        # Owner A loads overview, forecasts, recommendations
        ov_res = client.get("/api/intelligence/overview", headers=hdr_a)
        assert ov_res.status_code == 200
        assert ov_res.json()["data"]["total_active_products"] == 3

        # Overstock alert detects Excess Ceramic Jar (p_over)
        over_res = client.get("/api/intelligence/overstock-risks", headers=hdr_a)
        assert over_res.status_code == 200
        assert any(item["product_id"] == env["p_over"].id for item in over_res.json()["data"])

        # Tenant B cannot read Tenant A's product forecast or evaluation
        cross_f = client.get(f"/api/intelligence/forecasts/{env['p_brisk'].id}", headers=hdr_b)
        assert cross_f.status_code == 404
        cross_e = client.get(f"/api/intelligence/evaluations/{env['p_brisk'].id}", headers=hdr_b)
        assert cross_e.status_code == 404

        # Supplier role cannot access retailer intelligence
        sup_res = client.get("/api/intelligence/overview", headers=hdr_sup)
        assert sup_res.status_code == 403

        # Staff role cannot convert recommendation to PO
        rec_list = client.get("/api/intelligence/recommendations?status=OPEN", headers=hdr_a).json()["data"]
        rec_id = next(r["id"] for r in rec_list if r["product_id"] == env["p_brisk"].id)

        staff_conv = client.post(
            f"/api/intelligence/recommendations/{rec_id}/convert-to-po",
            json={"ordered_quantity": 20, "confirmed": True},
            headers=hdr_staff,
        )
        assert staff_conv.status_code == 403

        # Owner must pass confirmed=true
        unconfirmed = client.post(
            f"/api/intelligence/recommendations/{rec_id}/convert-to-po",
            json={"ordered_quantity": 20, "confirmed": False},
            headers=hdr_a,
        )
        assert unconfirmed.status_code == 400
    finally:
        app.dependency_overrides.clear()
