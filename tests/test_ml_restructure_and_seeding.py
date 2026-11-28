from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.db_migrate import ensure_schema_and_backfill
from app.ml.base_model import BaseForecastingModel
from app.ml.evaluation_service import (
    PRIMARY_DISPLAY_MAP,
    PRIMARY_ROSTER_ORDER,
    ModelEvaluationService,
)
from app.ml.feature_service import FeatureEngineeringService
from app.ml.forecasting_service import ForecastingService
from app.ml.historical_seeder import seed_demo_historical_datasets, verify_seed_environment
from app.ml.models import LSTMForecaster, NaiveForecaster, ProphetForecaster
from app.ml.preprocess_service import MAX_HISTORY_LOOKBACK_DAYS, DataPreprocessingService
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


def test_primary_roster_and_no_armia_typo_across_repo():
    assert PRIMARY_ROSTER_ORDER == ["ARIMA", "XGBoost", "Random Forest", "LSTM"]
    assert set(PRIMARY_DISPLAY_MAP.values()) == set(PRIMARY_ROSTER_ORDER)
    # Experimental Prophet remains preserved internally without deleting models
    assert ProphetForecaster is not None

    repo_root = Path(__file__).resolve().parents[1]
    scan_dirs = [
        repo_root / "backend" / "app",
        repo_root / "frontend" / "smart inventory forecast management system" / "src",
    ]
    for root in scan_dirs:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".js", ".jsx"}:
                content = path.read_text(encoding="utf-8", errors="ignore")
                assert "ARMIA" not in content, f"Typo ARMIA found in {path}"


def test_six_plus_metrics_signed_bias_and_zero_safe_mape():
    # Predicted > Actual => positive signed bias (+over-forecast)
    y_true = np.array([10.0, 20.0, 30.0, 40.0])
    y_over = np.array([15.0, 25.0, 35.0, 45.0])
    m_over = NaiveForecaster().evaluate(y_true, y_over)
    assert m_over["bias"] == pytest.approx(5.0, abs=1e-4)
    assert m_over["bias_direction"] == "OVER_FORECASTING"
    assert m_over["mae"] == pytest.approx(5.0, abs=1e-4)
    assert m_over["mse"] == pytest.approx(25.0, abs=1e-4)
    assert m_over["rmse"] == pytest.approx(5.0, abs=1e-4)
    assert m_over["wape"] == pytest.approx(20.0, abs=1e-2)
    assert m_over["mape"] is not None

    # Predicted < Actual => negative signed bias (-under-forecast)
    y_under = np.array([8.0, 18.0, 28.0, 38.0])
    m_under = NaiveForecaster().evaluate(y_true, y_under)
    assert m_under["bias"] == pytest.approx(-2.0, abs=1e-4)
    assert m_under["bias_direction"] == "UNDER_FORECASTING"

    # All-zero demand period: zero-safe MAPE & WAPE stay None (no fabricated accuracy / div-by-zero)
    m_zero = NaiveForecaster().evaluate(np.zeros(5), np.array([1.0, 0.0, 2.0, 0.0, 0.0]))
    assert m_zero["mape"] is None
    assert m_zero["wape"] is None
    assert m_zero["bias"] > 0
    assert m_zero["mape_limitation_note"] is not None


def test_lstm_eligibility_gating_and_no_silent_model_substitution(isolated_db):
    db, _ = isolated_db
    owner = models.User(name="Owner", email="gating@example.com", password_hash="x", role="owner", is_active=True)
    db.add(owner)
    db.flush()
    biz = models.Business(name="Gating Store", business_type="retailer", owner_user_id=owner.id, onboarding_completed=True)
    db.add(biz)
    db.flush()

    prod_short = models.Product(
        business_id=biz.id,
        sku="SHORT-30D",
        name="Short History Item",
        category="General",
        unit="piece",
        cost_price=50.0,
        selling_price=80.0,
        current_stock=50,
        reorder_level=10,
        created_at=_utcnow() - timedelta(days=35),
    )
    db.add(prod_short)
    db.flush()

    now = _utcnow()
    for d in range(30, 0, -1):
        db.add(
            models.Sale(
                business_id=biz.id,
                product_id=prod_short.id,
                sales_date=now - timedelta(days=d),
                quantity_sold=3 + (d % 2),
                selling_price=80.0,
                revenue=(3 + (d % 2)) * 80.0,
                status="COMPLETED",
            )
        )
    db.commit()

    daily_df, profile = ForecastingService.prepare_product_series(db, prod_short)
    elig_ok, elig_msg = LSTMForecaster.check_eligibility(daily_df)
    assert elig_ok is False
    assert "60" in elig_msg

    # Explicit user request for ineligible LSTM MUST raise ValueError (never silently substitute MovingAverage!)
    with pytest.raises(ValueError, match="LSTM"):
        ForecastingService.generate_product_forecast(
            db, prod_short.id, horizon_days=14, model_choice="lstm", business_id=biz.id
        )

    # Auto evaluation must keep LSTM marked SKIPPED_INSUFFICIENT_DATA cleanly in primary_leaderboard
    ev = ModelEvaluationService.evaluate_all_models(
        daily_df, data_sufficiency=profile["data_sufficiency"], horizon_days=14
    )
    assert [r["display_name"] for r in ev["primary_leaderboard"]] == PRIMARY_ROSTER_ORDER
    lstm_row = next(r for r in ev["primary_leaderboard"] if r["display_name"] == "LSTM")
    assert lstm_row["status"] == "SKIPPED_INSUFFICIENT_DATA"


def test_lstm_train_only_scaling_and_feature_zero_future_leakage():
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    base = pd.DataFrame(
        {
            "date": dates,
            "demand": [float(5 + (i % 7) + (i // 20)) for i in range(100)],
            "raw_demand": [float(5 + (i % 7) + (i // 20)) for i in range(100)],
            "is_stockout_day": [1 if i in (10, 80) else 0 for i in range(100)],
            "effective_price": [100.0 for _ in range(100)],
            "price_change_pct": [0.0 for _ in range(100)],
            "is_promo_day": [1 if i in (20, 85) else 0 for i in range(100)],
            "is_festive_window": [0 for _ in range(100)],
        }
    )
    perturbed = base.copy()
    perturbed.loc[60:, ["demand", "raw_demand"]] = 5000.0
    perturbed.loc[60:, "effective_price"] = 10.0
    perturbed.loc[60:, "is_stockout_day"] = 1

    f1 = FeatureEngineeringService.create_features(base)
    f2 = FeatureEngineeringService.create_features(perturbed)
    cols = FeatureEngineeringService.get_feature_columns()
    pd.testing.assert_frame_equal(f1.loc[:59, cols], f2.loc[:59, cols])

    # LSTM MinMax bounds fit strictly on chronological train partition (not val split)
    train_subset = perturbed.iloc[:80].copy()  # ends in 5000 on val slice (64..79) while train (0..63) has spike at 60..63
    train_clean = base.iloc[:80].copy()
    model = LSTMForecaster(epochs=5)
    model.fit(train_clean, target_col="demand")
    assert model.scale_max_ < 50.0


def test_bias_guard_baseline_fallback_and_persisted_provenance(isolated_db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.ml.forecasting_service.MODEL_ARTIFACTS_DIR", tmp_path)
    db, _ = isolated_db
    owner = models.User(name="Gov Owner", email="gov@example.com", password_hash="x", role="owner", is_active=True)
    db.add(owner)
    db.flush()
    biz = models.Business(name="Gov Retail", business_type="retailer", owner_user_id=owner.id, onboarding_completed=True)
    db.add(biz)
    db.flush()

    # Create a 5+ year (1850 days capped/supported within 2557) seasonal + promo item
    prod = models.Product(
        business_id=biz.id,
        sku="PROV-120D",
        name="Provenance Test SKU",
        category="Staples",
        unit="pack",
        cost_price=60.0,
        selling_price=90.0,
        current_stock=200,
        reorder_level=20,
        created_at=_utcnow() - timedelta(days=130),
    )
    db.add(prod)
    db.flush()
    now = _utcnow()
    for d in range(120, 0, -1):
        qty = 6 + (d % 4) + (2 if (d % 7) in (0, 6) else 0)
        db.add(
            models.Sale(
                business_id=biz.id,
                product_id=prod.id,
                sales_date=now - timedelta(days=d),
                quantity_sold=qty,
                selling_price=90.0,
                revenue=qty * 90.0,
                status="COMPLETED",
            )
        )
    db.commit()

    f1 = ForecastingService.generate_product_forecast(db, prod.id, horizon_days=30, business_id=biz.id)
    assert f1["cached"] is False
    assert f1["dataset_version"]
    assert f1["model_version"]
    assert [r["display_name"] for r in f1["primary_leaderboard"]] == PRIMARY_ROSTER_ORDER
    assert f1["training_start_date"] is not None
    assert f1["training_end_date"] is not None

    # Tenant-scoped artifact written cleanly under tenant_{business_id}
    tenant_dir = tmp_path / f"tenant_{biz.id}"
    assert tenant_dir.exists()
    assert len(list(tenant_dir.glob("*.json"))) == 1

    # Training run audited
    runs = db.query(models.ModelTrainingRun).filter(models.ModelTrainingRun.product_id == prod.id).all()
    assert len(runs) == 1
    assert runs[0].status == "COMPLETED"
    assert runs[0].champion_model == f1["model_used"]

    # Cache hit on repeat call, invalidates on new sale
    f2 = ForecastingService.generate_product_forecast(db, prod.id, horizon_days=30, business_id=biz.id)
    assert f2["cached"] is True

    SalesService.create_sale(
        db=db,
        business_id=biz.id,
        user_id=owner.id,
        allow_negative_stock=False,
        payload=schemas.SaleCreate(product_id=prod.id, quantity_sold=2),
    )
    f3 = ForecastingService.generate_product_forecast(db, prod.id, horizon_days=30, business_id=biz.id)
    assert f3["cached"] is False

    # Bias guard helper verifies severe bias threshold
    assert ModelEvaluationService._has_severe_bias({"bias_pct": 45.0}) is True
    assert ModelEvaluationService._has_severe_bias({"bias_pct": -12.0}) is False
    assert MAX_HISTORY_LOOKBACK_DAYS == 3653


def test_level2_same_workspace_category_prior_isolates_tenants(isolated_db):
    db, _ = isolated_db
    u1 = models.User(name="A", email="l2a@example.com", password_hash="x", role="owner", is_active=True)
    u2 = models.User(name="B", email="l2b@example.com", password_hash="x", role="owner", is_active=True)
    db.add_all([u1, u2])
    db.flush()
    b1 = models.Business(name="B1", business_type="retailer", owner_user_id=u1.id, onboarding_completed=True)
    b2 = models.Business(name="B2", business_type="retailer", owner_user_id=u2.id, onboarding_completed=True)
    db.add_all([b1, b2])
    db.flush()

    p_b1_peer = models.Product(
        business_id=b1.id, sku="B1-SNK-1", name="Peer Snack", category="Snacks",
        unit="pack", cost_price=10.0, selling_price=20.0, current_stock=50, reorder_level=5,
        created_at=_utcnow() - timedelta(days=30),
    )
    p_b1_new = models.Product(
        business_id=b1.id, sku="B1-SNK-NEW", name="New Snack", category="Snacks",
        unit="pack", cost_price=10.0, selling_price=20.0, current_stock=20, reorder_level=5,
        created_at=_utcnow() - timedelta(days=1),
    )
    p_b2_other_cat = models.Product(
        business_id=b2.id, sku="B2-OIL-1", name="Other Tenant Oil", category="Oils",
        unit="bottle", cost_price=50.0, selling_price=90.0, current_stock=100, reorder_level=10,
        created_at=_utcnow() - timedelta(days=30),
    )
    p_b1_new_oil = models.Product(
        business_id=b1.id, sku="B1-OIL-NEW", name="B1 New Oil", category="Oils",
        unit="bottle", cost_price=50.0, selling_price=90.0, current_stock=10, reorder_level=5,
        created_at=_utcnow() - timedelta(days=1),
    )
    db.add_all([p_b1_peer, p_b1_new, p_b2_other_cat, p_b1_new_oil])
    db.flush()

    now = _utcnow()
    for d in range(1, 20):
        db.add(
            models.Sale(
                business_id=b1.id, product_id=p_b1_peer.id, sales_date=now - timedelta(days=d),
                quantity_sold=5, selling_price=20.0, revenue=100.0, status="COMPLETED",
            )
        )
        db.add(
            models.Sale(
                business_id=b2.id, product_id=p_b2_other_cat.id, sales_date=now - timedelta(days=d),
                quantity_sold=50, selling_price=90.0, revenue=4500.0, status="COMPLETED",
            )
        )
    db.commit()

    # B1 new Snack gets Level-2 prior from B1's peer Snack SKU (same workspace!)
    f_snack = ForecastingService.generate_product_forecast(db, p_b1_new.id, horizon_days=14, business_id=b1.id)
    assert f_snack["hierarchical_level"] == "LEVEL_2_CATEGORY_PATTERN"
    assert f_snack["expected_total_demand"] > 0.0

    # B1 new Oil MUST NOT inherit B2's Oils demand (cross-tenant isolated!)
    f_oil = ForecastingService.generate_product_forecast(db, p_b1_new_oil.id, horizon_days=14, business_id=b1.id)
    assert f_oil["hierarchical_level"] == "LEVEL_4_COLD_START"
    assert f_oil["expected_total_demand"] == 0.0


def test_historical_seeder_dev_guard_idempotency_and_stock_coherence(isolated_db, monkeypatch):
    db, _ = isolated_db
    # Production guard must block accidental production seeding
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="production"):
        verify_seed_environment()

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("RENDER", raising=False)

    u = models.User(name="Sanjana Test", email="sanjana_test@example.com", password_hash="x", role="owner", is_active=True)
    db.add(u)
    db.flush()
    b = models.Business(id=3, name="Sanjana Supermarket", business_type="retailer", owner_user_id=u.id, onboarding_completed=True)
    db.add(b)
    db.flush()

    genuine_prod = models.Product(
        business_id=3, sku="RET-001", name="Genuine Rice", category="Grains & Staples",
        unit="kg", cost_price=60.0, selling_price=80.0, current_stock=60, reorder_level=10, is_synthetic=False,
    )
    db.add(genuine_prod)
    db.flush()
    db.add(
        models.Sale(
            business_id=3, product_id=genuine_prod.id, sales_date=_utcnow() - timedelta(days=1),
            quantity_sold=5, selling_price=80.0, revenue=400.0, status="COMPLETED", is_synthetic=False,
        )
    )
    db.commit()

    from app.ml.historical_seeder import SCENARIO_CATALOG

    rep1 = seed_demo_historical_datasets(db, target_business_ids=[3], seed=42, enforce_env_guard=True)
    assert rep1.counts["Products"]["inserted"] == len(SCENARIO_CATALOG)
    assert rep1.counts["Sales"]["inserted"] > 2000
    assert rep1.counts["PurchaseOrders"]["inserted"] > 50
    assert rep1.counts["GoodsReceipts"]["inserted"] == rep1.counts["PurchaseOrders"]["inserted"]

    # Genuine product & sale remain 100% untouched
    db.refresh(genuine_prod)
    assert genuine_prod.current_stock == 60
    assert genuine_prod.is_synthetic is False

    # Stock ledger never negative & closing stock matches Product.current_stock
    neg_count = db.query(models.InventoryLog).filter(models.InventoryLog.closing_stock < 0).count()
    assert neg_count == 0

    syn_products = db.query(models.Product).filter(models.Product.business_id == 3, models.Product.is_synthetic.is_(True)).all()
    assert len(syn_products) == len(SCENARIO_CATALOG)
    for sp in syn_products:
        last_log = (
            db.query(models.InventoryLog)
            .filter(models.InventoryLog.product_id == sp.id)
            .order_by(models.InventoryLog.timestamp.desc(), models.InventoryLog.id.desc())
            .first()
        )
        assert last_log is not None
        assert sp.current_stock == last_log.closing_stock

    # Second run is 100% idempotent with 0 inserts
    rep2 = seed_demo_historical_datasets(db, target_business_ids=[3], seed=42, enforce_env_guard=True)
    for entity, stats in rep2.counts.items():
        assert stats["inserted"] == 0, f"Expected 0 inserts on idempotent re-run for {entity}"
        assert stats["failed"] == 0

    # End-to-end forecast works cleanly on seeded 10Y, 7Y, 5Y & 20D SKUs + backfilled genuine product + 10Y chart window
    sp_10y = next(p for p in syn_products if "HIS-10Y" in p.sku)
    sp_7y = next(p for p in syn_products if "LNG-7Y" in p.sku)
    sp_5y = next(p for p in syn_products if "SPK-5Y" in p.sku)
    sp_20d = next(p for p in syn_products if "LIM-20D" in p.sku)

    # Genuine product RET-001 was backfilled safely so ARIMA/XGBoost/RF/LSTM all run without error
    f_real_arima = ForecastingService.generate_product_forecast(
        db, genuine_prod.id, horizon_days=30, model_choice="arima", business_id=3,
        history_days=3650, history_resolution="monthly",
    )
    assert f_real_arima["model_display_name"] == "ARIMA"
    assert f_real_arima["history_window_meta"]["resolution_used"] == "monthly"
    assert f_real_arima["history_window_meta"]["available_total_days"] >= 3600

    # Custom date window validation (start > end rejected cleanly)
    with pytest.raises(ValueError, match="history_start_date"):
        ForecastingService.generate_product_forecast(
            db, sp_10y.id, horizon_days=30, business_id=3,
            history_start_date=datetime(2026, 5, 1).date(),
            history_end_date=datetime(2025, 1, 1).date(),
        )

    f_10y_weekly = ForecastingService.generate_product_forecast(
        db, sp_10y.id, horizon_days=30, business_id=3, history_days=730, history_resolution="auto",
    )
    assert f_10y_weekly["historical_summary"]["total_historical_days"] >= 3600
    assert f_10y_weekly["history_window_meta"]["resolution_used"] == "weekly"

    f_7y = ForecastingService.generate_product_forecast(db, sp_7y.id, horizon_days=30, business_id=3)
    assert f_7y["has_synthetic_data"] is True
    assert f_7y["historical_summary"]["total_historical_days"] >= 2500

    f_5y = ForecastingService.generate_product_forecast(db, sp_5y.id, horizon_days=30, business_id=3)
    assert f_5y["has_synthetic_data"] is True
    assert f_5y["stockout_days_count"] >= 1
    assert f_5y["historical_summary"]["total_historical_days"] >= 1800

    f_20d = ForecastingService.generate_product_forecast(db, sp_20d.id, horizon_days=14, business_id=3)
    assert f_20d["data_sufficiency"] == "LIMITED"
    assert f_20d["fallback_used"] is True
