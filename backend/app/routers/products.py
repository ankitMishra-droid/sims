from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..schemas import product_schema
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles
from ..services.product_service import ProductService

router = APIRouter(prefix="/api/products", tags=["Products"])

READ_ROLES = ["admin", "manager", "analyst", "staff"]
WRITE_ROLES = ["admin", "manager"]


@router.post("/", response_model=product_schema.ProductResponse)
def create_product(
    product: product_schema.ProductCreate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    db_product = ProductService.create_product(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        payload=product,
    )
    return {"data": db_product, "message": "Product added successfully"}


@router.get("/", response_model=product_schema.ProductListResponse)
def get_all_products(
    search: Annotated[Optional[str], Query()] = None,
    category: Annotated[Optional[str], Query()] = None,
    is_active: Annotated[Optional[bool], Query()] = True,
    stock_status: Annotated[Optional[str], Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, total = ProductService.list_products(
        db=db,
        business_id=ctx.business_id,
        search=search,
        category=category,
        is_active=is_active,
        stock_status=stock_status,
        skip=skip,
        limit=limit,
    )
    return {"data": items, "total": total, "message": "All products fetched successfully"}


@router.get("/{product_id}", response_model=product_schema.ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    product = ProductService.get_product(db=db, business_id=ctx.business_id, product_id=product_id)
    return {"data": product, "message": "Product fetched successfully"}


@router.put("/{product_id}", response_model=product_schema.ProductResponse)
def update_product(
    product_id: int,
    updated: product_schema.ProductUpdate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    product = ProductService.update_product(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        payload=updated,
    )
    return {"data": product, "message": "Product updated successfully"}


@router.patch("/deactivate/{product_id}", response_model=product_schema.ProductResponse)
def deactivate_product(
    product_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    product = ProductService.set_active_status(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        is_active=False,
    )
    return {"data": product, "message": "Product deactivated"}


@router.patch("/activate/{product_id}", response_model=product_schema.ProductResponse)
def activate_product(
    product_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    product = ProductService.set_active_status(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        is_active=True,
    )
    return {"data": product, "message": "Product activated"}
