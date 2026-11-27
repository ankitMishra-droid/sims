from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import (
    BusinessContext,
    require_business_types,
    require_permission,
)
from ..schemas.business_schema import (
    SupplierPortalOrderOut,
    SupplierPortalStatusUpdateRequest,
)
from ..services.procurement_service import ProcurementService

router = APIRouter(prefix="/api/supplier-portal", tags=["Supplier Collaboration Portal"])


@router.get("/purchase-orders", response_model=list[SupplierPortalOrderOut])
def list_shared_purchase_orders(
    ctx: BusinessContext = Depends(require_permission("supplier_portal.read")),
    _: BusinessContext = Depends(require_business_types(["supplier"])),
    db: Session = Depends(get_db),
):
    """List only purchase orders explicitly shared with the active supplier workspace."""
    return ProcurementService.list_supplier_portal_orders(db, ctx.business_id)


@router.get("/purchase-orders/{order_id}", response_model=SupplierPortalOrderOut)
def get_shared_purchase_order(
    order_id: int,
    ctx: BusinessContext = Depends(require_permission("supplier_portal.read")),
    _: BusinessContext = Depends(require_business_types(["supplier"])),
    db: Session = Depends(get_db),
):
    """Retrieve a single explicitly shared purchase order without leaking buyer internal data."""
    return ProcurementService.get_supplier_portal_order(db, ctx.business_id, order_id)


@router.post("/purchase-orders/{order_id}/status", response_model=SupplierPortalOrderOut)
def update_supplier_order_status(
    order_id: int,
    payload: SupplierPortalStatusUpdateRequest,
    ctx: BusinessContext = Depends(require_permission("supplier_portal.update_status")),
    _: BusinessContext = Depends(require_business_types(["supplier"])),
    db: Session = Depends(get_db),
):
    """Record supplier-side acknowledgement/dispatch status while blocking quantity/stock edits."""
    return ProcurementService.update_supplier_portal_status(
        db=db,
        supplier_business_id=ctx.business_id,
        user_id=ctx.user.id,
        order_id=order_id,
        new_status=payload.supplier_status,
        notes=payload.notes,
    )
