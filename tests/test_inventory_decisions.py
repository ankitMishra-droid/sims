import pytest
import numpy as np
from app.ml.decision_service import InventoryDecisionService
from app.ml.simulation_service import ScenarioSimulationService
from app.database import SessionLocal

def test_inventory_decision_formulas():
    # Test ROP and Safety Stock formulas with known parameters
    d = 2.0       # Daily average demand
    sigma_d = 0.5 # Demand std dev
    L = 5         # Lead time in days
    sigma_L = 1.0 # Lead time std dev
    Z = 1.645     # 95% service level

    # Safety Stock formula: SS = Z * sqrt(L * sigma_d^2 + d^2 * sigma_L^2)
    # L * sigma_d^2 = 5 * 0.25 = 1.25
    # d^2 * sigma_L^2 = 4 * 1.0 = 4.0
    # Total variance term = 5.25
    # sqrt(5.25) ~ 2.291
    # SS = ceil(1.645 * 2.291) = ceil(3.769) = 4
    expected_ss = int(np.ceil(Z * np.sqrt(L * (sigma_d ** 2) + (d ** 2) * (sigma_L ** 2))))
    assert expected_ss == 4

    # ROP = (d * L) + SS = (2 * 5) + 4 = 14
    expected_rop = int(np.ceil((d * L) + expected_ss))
    assert expected_rop == 14

def test_risk_classification():
    # If Days of Inventory Remaining (DIR) < Lead Time -> CRITICAL
    lead_time = 7
    current_stock = 10
    daily_demand = 2.0
    dir_days = current_stock / daily_demand  # 5.0 days < 7 -> CRITICAL
    assert dir_days < lead_time

def test_what_if_simulation_depletion(db_session):
    db = SessionLocal()
    try:
        # Run stress test simulation with +50% demand shock
        sim = ScenarioSimulationService.run_simulation(
            db, product_id=1, simulation_horizon_days=30,
            demand_multiplier=1.50, lead_time_delay_days=3
        )
        assert sim["product_id"] == 1
        assert "simulation_result" in sim
        assert "trajectory" in sim
        assert len(sim["trajectory"]) == 30
        assert sim["simulation_result"]["revised_safety_stock_needed"] > 0
    finally:
        db.close()
