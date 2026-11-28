from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..services.sales_service import SalesService

router = APIRouter(
    prefix="/api/sales",
    tags=["Sales"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]
CREATE_ROLES = ["admin", "manager", "staff"]
MANAGE_ROLES = ["admin", "manager"]


@router.post("/", response_model=schemas.SaleResponse)
def create_sale(
    sale: schemas.SaleCreate,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(CREATE_ROLES)),
):
    db_sale = SalesService.create_sale(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        allow_negative_stock=ctx.business.allow_negative_stock,
        payload=sale,
        idempotency_key=idempotency_key,
    )
    return {"data": db_sale, "message": "Product sold"}


@router.get("/", response_model=schemas.SaleListResponse)
def get_sales(
    product_id: Annotated[Optional[int], Query()] = None,
    start_date: Annotated[Optional[str], Query()] = None,
    end_date: Annotated[Optional[str], Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, total = SalesService.list_sales(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )
    return {"data": items, "total": total, "message": "Sales fetched successfully"}


@router.get("/product/{product_id}", response_model=schemas.SaleResponse)
def get_sale_by_product(
    product_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, _ = SalesService.list_sales(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        limit=1,
    )
    if not items:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Sale not found for product")
    return {"data": items[0], "message": "Sale product fetched"}


@router.get("/date/{date}", response_model=schemas.SaleListResponse)
def get_sales_by_date(
    date: str,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, total = SalesService.list_sales(
        db=db,
        business_id=ctx.business_id,
        start_date=date,
        end_date=date,
        limit=1000,
    )
    return {"data": items, "total": total, "message": "Sales fetched"}


@router.get("/date-range/", response_model=schemas.SaleListResponse)
def get_sales_by_date_range(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, total = SalesService.list_sales(
        db=db,
        business_id=ctx.business_id,
        start_date=start_date,
        end_date=end_date,
        limit=2000,
    )
    return {"data": items, "total": total, "message": "Sales fetched"}


@router.get("/product-date-range/", response_model=schemas.SaleListResponse)
def get_sales_by_product_and_date_range(
    product_id: int,
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, total = SalesService.list_sales(
        db=db,
        business_id=ctx.business_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        limit=2000,
    )
    return {"data": items, "total": total, "message": "Sales fetched"}


@router.get("/{sale_id}", response_model=schemas.SaleResponse)
def get_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    sale = SalesService.get_sale(db=db, business_id=ctx.business_id, sale_id=sale_id)
    return {"data": sale, "message": "Sale fetched successfully"}


@router.post("/{sale_id}/cancel", response_model=schemas.SaleResponse)
def cancel_sale(
    sale_id: int,
    payload: schemas.SaleCancelRequest = schemas.SaleCancelRequest(),
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(MANAGE_ROLES)),
):
    sale = SalesService.cancel_sale(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        sale_id=sale_id,
        reason=payload.reason,
    )
    return {"data": sale, "message": "Sale cancelled and stock restored"}
