import logging
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..models.products import Product
from ..ml.simulation_service import ScenarioSimulationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/simulator",
    tags=["What-If Scenario Simulation"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]


class ScenarioSimulationRequest(BaseModel):
    product_id: int
    simulation_horizon_days: int = Field(60, ge=14, le=120)
    demand_multiplier: float = Field(1.0, ge=0.2, le=3.0)
    lead_time_delay_days: int = Field(0, ge=0, le=60)
    service_level: float = Field(0.95, ge=0.80, le=0.999)
    planned_restock_qty: int = Field(0, ge=0)
    restock_day: int = Field(14, ge=1, le=120)


@router.post("/scenario")
def run_scenario_simulation(
    req: ScenarioSimulationRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Run interactive What-If stress test under dynamic demand and lead time shocks."""
    prod = (
        db.query(Product)
        .filter(Product.id == req.product_id, Product.business_id == ctx.business_id)
        .first()
    )
    if not prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in workspace")

    try:
        result = ScenarioSimulationService.run_simulation(
            db=db,
            product_id=req.product_id,
            simulation_horizon_days=req.simulation_horizon_days,
            demand_multiplier=req.demand_multiplier,
            lead_time_delay_days=req.lead_time_delay_days,
            service_level=req.service_level,
            planned_restock_qty=req.planned_restock_qty,
            restock_day=req.restock_day,
            business_id=ctx.business_id,
        )
        return {"status": "success", "data": result}
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation product data not found.")
    except Exception:
        logger.exception("Simulation error business_id=%s product_id=%s", ctx.business_id, req.product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run scenario simulation.",
        )
