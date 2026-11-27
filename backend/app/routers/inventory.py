from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import schemas
from ..dependencies.authorization import BusinessContext, require_business_roles
from ..services.inventory_service import InventoryService

router = APIRouter(prefix="/api/inventory", tags=["Inventory"])

READ_ROLES = ["admin", "manager", "analyst", "staff"]
WRITE_ROLES = ["admin", "manager"]


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
        allow_negative=bool(ctx.business.allow_negative_stock),
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
