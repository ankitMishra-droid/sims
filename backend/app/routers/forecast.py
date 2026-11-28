from datetime import date
import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..models.products import Product
from ..ml.forecasting_service import ForecastingService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/forecast",
    tags=["Demand Forecasting Intelligence"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]


def _verify_product_tenant(db: Session, product_id: int, business_id: int) -> None:
    prod = (
        db.query(Product)
        .filter(Product.id == product_id, Product.business_id == business_id)
        .first()
    )
    if not prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in workspace")


@router.get("/{product_id}")
def get_product_demand_forecast(
    product_id: int,
    horizon_days: Annotated[int, Query(ge=7, le=90, description="Forecast horizon in days (7-90)")] = 30,
    model: Annotated[str, Query(description="Model choice: auto, arima, xgboost, random_forest, lstm")] = "auto",
    history_days: Annotated[Optional[int], Query(ge=0, le=3653, description="History window days for chart (0 = all up to 10Y)")] = 180,
    history_start_date: Annotated[Optional[date], Query(description="Custom history chart start date (YYYY-MM-DD)")] = None,
    history_end_date: Annotated[Optional[date], Query(description="Custom history chart end date (YYYY-MM-DD)")] = None,
    history_resolution: Annotated[str, Query(pattern="^(auto|daily|weekly|monthly)$")] = "auto",
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Generate multi-day demand forecast for specified product."""
    _verify_product_tenant(db, product_id, ctx.business_id)
    try:
        forecast = ForecastingService.generate_product_forecast(
            db=db,
            product_id=product_id,
            horizon_days=horizon_days,
            model_choice=model,
            business_id=ctx.business_id,
            history_days=history_days,
            history_start_date=history_start_date,
            history_end_date=history_end_date,
            history_resolution=history_resolution,
        )
        return {"status": "success", "data": forecast}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("Forecasting error business_id=%s product_id=%s", ctx.business_id, product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate demand forecast.",
        )


@router.get("/compare/{product_id}")
def compare_forecasting_models(
    product_id: int,
    test_days: Annotated[int, Query(ge=3, le=60, description="Rolling-origin evaluation window in days")] = 14,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Evaluate and benchmark candidate forecasting models on specified product."""
    _verify_product_tenant(db, product_id, ctx.business_id)
    try:
        comparison = ForecastingService.compare_models_for_product(
            db=db,
            product_id=product_id,
            test_days=test_days,
            business_id=ctx.business_id,
        )
        return {"status": "success", "data": comparison}
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forecast comparison data not found.")
    except Exception:
        logger.exception("Model comparison error business_id=%s product_id=%s", ctx.business_id, product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compare forecasting models.",
        )
