import logging
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..models.products import Product
from ..ml.anomaly_service import AnomalyDetectionService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/analytics",
    tags=["Inventory Analytics & Anomaly Detection"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]


@router.get("/anomalies/{product_id}")
def get_product_anomalies(
    product_id: int,
    lookback_days: Annotated[int, Query(ge=14, le=365, description="Lookback window in days")] = 90,
    sensitivity: Annotated[str, Query(description="Sensitivity: low, medium, high")] = "medium",
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Detect anomalous demand spikes and inventory drops."""
    prod = (
        db.query(Product)
        .filter(Product.id == product_id, Product.business_id == ctx.business_id)
        .first()
    )
    if not prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in workspace")

    z_map = {"low": 3.0, "medium": 2.5, "high": 2.0}
    z_threshold = z_map.get(sensitivity.lower(), 2.5)

    try:
        report = AnomalyDetectionService.detect_anomalies(
            db=db,
            product_id=product_id,
            lookback_days=lookback_days,
            z_threshold=z_threshold,
            business_id=ctx.business_id,
        )
        return {"status": "success", "data": report}
    except Exception:
        logger.exception("Anomaly detection error business_id=%s product_id=%s", ctx.business_id, product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute anomaly detection report.",
        )
