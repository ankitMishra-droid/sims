from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles
from ..models.products import Product
from ..ml.forecasting_service import ForecastingService

router = APIRouter(
    prefix="/api/forecast",
    tags=["Demand Forecasting Intelligence"],
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
    horizon_days: int = Query(30, ge=7, le=90, description="Forecast horizon in days (7-90)"),
    model: str = Query("auto", description="Model choice: auto, arima, prophet, random_forest, xgboost, lstm"),
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
        )
        return {"status": "success", "data": forecast}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Forecasting error: {str(e)}")


@router.get("/compare/{product_id}")
def compare_forecasting_models(
    product_id: int,
    test_days: int = Query(30, ge=7, le=60, description="Walk-forward test evaluation window in days"),
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Evaluate and benchmark all 5 forecasting models on specified product."""
    _verify_product_tenant(db, product_id, ctx.business_id)
    try:
        comparison = ForecastingService.compare_models_for_product(
            db=db,
            product_id=product_id,
            test_days=test_days,
        )
        return {"status": "success", "data": comparison}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Model comparison error: {str(e)}")
