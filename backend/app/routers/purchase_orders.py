from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..services.procurement_service import ProcurementService

router = APIRouter(
    prefix="/api/purchase-orders",
    tags=["Purchase Orders"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]
MANAGE_ROLES = ["admin", "manager"]
RECEIVE_ROLES = ["admin", "manager", "staff"]


@router.post("/", response_model=schemas.PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    payload: schemas.PurchaseOrderCreate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    return ProcurementService.create_purchase_order(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        payload=payload,
    )


@router.get("/", response_model=list[schemas.PurchaseOrderOut])
def get_purchase_orders(
    status_filter: Annotated[Optional[str], Query(alias="status")] = None,
    supplier_id: Annotated[Optional[int], Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return ProcurementService.list_purchase_orders(
        db=db,
        business_id=ctx.business_id,
        status_filter=status_filter,
        supplier_id=supplier_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{order_id}", response_model=schemas.PurchaseOrderOut)
def get_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return ProcurementService.get_purchase_order(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
    )


@router.put("/{order_id}", response_model=schemas.PurchaseOrderOut)
def update_purchase_order(
    order_id: int,
    payload: schemas.PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    return ProcurementService.update_draft_purchase_order(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
        payload=payload,
    )


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    ProcurementService.delete_draft_purchase_order(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{order_id}/send", response_model=schemas.PurchaseOrderOut)
def send_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    return ProcurementService.send_purchase_order(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
    )


@router.post("/{order_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    return ProcurementService.cancel_purchase_order(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
    )


@router.post("/{order_id}/receive", response_model=schemas.PurchaseOrderOut)
def receive_purchase_order(
    order_id: int,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(RECEIVE_ROLES)),
):
    return ProcurementService.receive_goods(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        order_id=order_id,
        items_to_receive=None,
        idempotency_key=idempotency_key,
    )


@router.post("/{order_id}/partially_receive", response_model=schemas.PurchaseOrderOut)
def partially_receive_purchase_order(
    order_id: int,
    payload: schemas.ReceiveItem,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(RECEIVE_ROLES)),
):
    return ProcurementService.receive_goods(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        order_id=order_id,
        items_to_receive=[payload],
        idempotency_key=idempotency_key or payload.idempotency_key,
        notes=payload.notes,
    )


@router.post("/{order_id}/receipts", response_model=schemas.PurchaseOrderOut)
def create_goods_receipt(
    order_id: int,
    payload: schemas.ReceivePurchaseOrder,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(RECEIVE_ROLES)),
):
    return ProcurementService.receive_goods(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        order_id=order_id,
        items_to_receive=payload.items,
        idempotency_key=idempotency_key or payload.idempotency_key,
        notes=payload.notes,
    )


@router.get("/{order_id}/receipts", response_model=list[schemas.GoodsReceiptOut])
def list_goods_receipts(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return ProcurementService.list_receipts(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
    )


@router.post("/{order_id}/share", response_model=schemas.PurchaseOrderOut)
def share_purchase_order_with_supplier(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    return ProcurementService.set_supplier_share(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
        share=True,
    )


@router.post("/{order_id}/unshare", response_model=schemas.PurchaseOrderOut)
def unshare_purchase_order_with_supplier(
    order_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    return ProcurementService.set_supplier_share(
        db=db,
        business_id=ctx.business_id,
        order_id=order_id,
        share=False,
    )
