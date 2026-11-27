import pytest
from app.database import SessionLocal, engine
from app.db_migrate import ensure_schema_and_backfill
from app.dependencies.authorization import BusinessContext
from app.models.business import Business, BusinessMember
from app.models.users import User
from app.routers.analytics import get_product_anomalies
from app.routers.decision import get_all_reorder_recommendations, get_single_product_decision
from app.routers.forecast import get_product_demand_forecast
from app.routers.products import get_all_products
from app.routers.simulator import ScenarioSimulationRequest, run_scenario_simulation


@pytest.fixture
def db():
    ensure_schema_and_backfill(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def ctx(db):
    user = db.query(User).order_by(User.id.asc()).first()
    business = db.query(Business).order_by(Business.id.asc()).first()
    membership = (
        db.query(BusinessMember)
        .filter(
            BusinessMember.business_id == business.id,
            BusinessMember.user_id == user.id,
        )
        .first()
    )
    return BusinessContext(
        user=user,
        business=business,
        membership=membership,
        business_id=business.id,
        role=membership.role,
    )


def test_api_products(db, ctx):
    res = get_all_products(db=db, ctx=ctx)
    assert "data" in res
    assert len(res["data"]) >= 21


def test_api_forecast(db, ctx):
    res = get_product_demand_forecast(product_id=1, horizon_days=14, model="auto", db=db, ctx=ctx)
    assert res["status"] == "success"
    data = res["data"]
    assert data["product_id"] == 1
    assert "forecast_series" in data
    assert len(data["forecast_series"]) == 14


def test_api_decision_recommendations(db, ctx):
    res = get_all_reorder_recommendations(service_level=0.95, db=db, ctx=ctx)
    assert res["status"] == "success"
    assert res["total_count"] >= 21
    assert len(res["data"]) >= 21


def test_api_single_product_decision(db, ctx):
    res = get_single_product_decision(product_id=1, service_level=0.95, db=db, ctx=ctx)
    assert res["status"] == "success"
    data = res["data"]
    assert "safety_stock" in data
    assert "reorder_point" in data
    assert "days_inventory_remaining" in data
    assert "incoming_stock" in data
    assert "inventory_position" in data


def test_api_simulator(db, ctx):
    req = ScenarioSimulationRequest(
        product_id=1,
        simulation_horizon_days=30,
        demand_multiplier=1.25,
        lead_time_delay_days=3,
        service_level=0.95,
        planned_restock_qty=0,
        restock_day=14,
    )
    res = run_scenario_simulation(req=req, db=db, ctx=ctx)
    assert res["status"] == "success"
    data = res["data"]
    assert "simulation_result" in data
    assert "trajectory" in data
    assert len(data["trajectory"]) == 30


def test_api_anomalies(db, ctx):
    res = get_product_anomalies(product_id=1, lookback_days=90, sensitivity="medium", db=db, ctx=ctx)
    assert res["status"] == "success"
    assert "anomalies" in res["data"]
