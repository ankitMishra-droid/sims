from datetime import datetime
import logging
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..ml.decision_service import InventoryDecisionService
from ..models.products import Product
from ..services.procurement_service import ProcurementService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/decision",
    tags=["Inventory Decision Engine"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]
PO_WRITE_ROLES = ["admin", "manager"]


class ConvertToPOItem(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)


class ConvertToPORequest(BaseModel):
    supplier_id: int
    items: List[ConvertToPOItem]
    expected_delivery_date: Optional[str] = None
    notes: Optional[str] = "Auto-generated from ML Smart Reorder Planner"


@router.get("/recommendations")
def get_all_reorder_recommendations(
    service_level: Annotated[float, Query(ge=0.80, le=0.999, description="Target service level probability")] = 0.95,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Retrieve smart reorder recommendations across all inventory products in the workspace."""
    try:
        recommendations = InventoryDecisionService.get_all_recommendations(
            db=db,
            service_level=service_level,
            business_id=ctx.business_id,
        )
        return {
            "status": "success",
            "service_level": service_level,
            "total_count": len(recommendations),
            "data": recommendations,
        }
    except Exception:
        logger.exception("Decision engine error business_id=%s", ctx.business_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute reorder recommendations.",
        )


@router.get("/product/{product_id}")
def get_single_product_decision(
    product_id: int,
    service_level: Annotated[float, Query(ge=0.80, le=0.999)] = 0.95,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    """Retrieve detailed ROP, Safety Stock, EOQ, and risk analysis for one product."""
    prod = (
        db.query(Product)
        .filter(Product.id == product_id, Product.business_id == ctx.business_id)
        .first()
    )
    if not prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in workspace")

    try:
        decision = InventoryDecisionService.calculate_product_decision_metrics(
            db=db,
            product_id=product_id,
            service_level=service_level,
            business_id=ctx.business_id,
        )
        return {"status": "success", "data": decision}
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product decision data not found.")
    except Exception:
        logger.exception("Decision analysis error business_id=%s product_id=%s", ctx.business_id, product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute product decision analysis.",
        )


@router.post("/convert-to-po", status_code=status.HTTP_201_CREATED)
def convert_recommendation_to_purchase_order(
    req: ConvertToPORequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(PO_WRITE_ROLES)),
):
    """1-Click creation of a draft purchase order directly from reorder recommendations."""
    if not req.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must supply at least one product item.")

    expected_date = None
    if req.expected_delivery_date:
        try:
            expected_date = datetime.strptime(req.expected_delivery_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid expected_delivery_date (YYYY-MM-DD)")

    product_ids = [itm.product_id for itm in req.items]
    products = (
        db.query(Product)
        .filter(Product.id.in_(product_ids), Product.business_id == ctx.business_id)
        .all()
    )
    product_map: dict[int, Product] = {p.id: p for p in products}

    po_items = []
    for itm in req.items:
        prod = product_map.get(itm.product_id)
        if not prod:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product ID {itm.product_id} not found in workspace",
            )
        po_items.append(
            schemas.PurchaseOrderItemCreate(
                product_id=prod.id,
                ordered_quantity=itm.quantity,
                unit_cost=float(prod.cost_price or 0.0),
            )
        )

    po_payload = schemas.PurchaseOrderCreate(
        supplier_id=req.supplier_id,
        expected_delivery_date=expected_date,
        notes=req.notes,
        items=po_items,
    )
    po = ProcurementService.create_purchase_order(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        payload=po_payload,
    )

    return {
        "status": "success",
        "message": f"Purchase order '{po.order_number}' created successfully.",
        "purchase_order_id": po.id,
        "order_number": po.order_number,
        "total_amount": round(float(po.total_amount or 0), 2),
    }
