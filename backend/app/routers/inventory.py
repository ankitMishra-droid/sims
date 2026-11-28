from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import schemas
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..services.alert_service import StockAlertService
from ..services.inventory_service import InventoryService

router = APIRouter(
    prefix="/api/inventory",
    tags=["Inventory"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]
WRITE_ROLES = ["admin", "manager"]
ALERT_MANAGE_ROLES = ["admin", "manager", "analyst"]


@router.post("/stock-in")
def add_stock(
    stock: schemas.StockInCreate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    return InventoryService.stock_in(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        payload=stock,
    )


@router.post("/adjust")
def adjust_stock(
    adjustment: schemas.StockAdjustmentCreate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    return InventoryService.adjust_stock(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        allow_negative=ctx.business.allow_negative_stock,
        payload=adjustment,
    )


@router.get("/positions", response_model=list[schemas.InventoryPositionOut])
def get_all_inventory_positions(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return InventoryService.get_inventory_positions(db=db, business_id=ctx.business_id)


@router.get("/positions/{product_id}", response_model=schemas.InventoryPositionOut)
def get_product_inventory_position(
    product_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    positions = InventoryService.get_inventory_positions(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
    )
    if not positions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product inventory position not found",
        )
    return positions[0]


@router.get("/logs/{product_id}", response_model=list[schemas.InventoryLogOut])
def get_inventory_logs(
    product_id: int,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return InventoryService.get_logs(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        skip=skip,
        limit=limit,
    )


@router.get("/low-stock", response_model=schemas.LowStockResponse)
def get_low_stock_products(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    low_stock_products = InventoryService.get_low_stock_products(
        db=db,
        business_id=ctx.business_id,
    )
    return {
        "data": low_stock_products,
        "message": "Low stock products fetched successfully",
    }


@router.get("/alerts")
def list_stock_alerts(
    include_dismissed: Annotated[bool, Query()] = False,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return StockAlertService.list_alerts(
        db=db,
        business_id=ctx.business_id,
        include_dismissed=include_dismissed,
    )


@router.post("/alerts/read")
def mark_stock_alerts_read(
    payload: schemas.StockAlertReadRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    return StockAlertService.mark_read(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        alert_key=payload.alert_key,
        product_id=payload.product_id,
        mark_all=payload.mark_all,
    )


@router.post("/alerts/dismiss")
def dismiss_stock_alert(
    payload: schemas.StockAlertDismissRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(ALERT_MANAGE_ROLES)),
):
    row = StockAlertService.dismiss_alert(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        alert_key=payload.alert_key,
        alert_type=payload.alert_type,
        product_id=payload.product_id,
        severity=payload.severity,
        current_stock=payload.current_stock,
        cooldown_days=payload.cooldown_days,
        notes=payload.notes,
    )
    return {
        "alert_key": row.alert_key,
        "status": row.status,
        "dismissed_until": row.dismissed_until.isoformat() if row.dismissed_until else None,
    }


@router.post("/alerts/reopen")
def reopen_stock_alert(
    payload: schemas.StockAlertReopenRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(ALERT_MANAGE_ROLES)),
):
    return StockAlertService.reopen_alert(
        db=db,
        business_id=ctx.business_id,
        alert_key=payload.alert_key,
    )
