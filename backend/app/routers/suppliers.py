from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types
from ..services.supplier_service import SupplierService

router = APIRouter(
    prefix="/api/suppliers",
    tags=["Suppliers"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]
WRITE_ROLES = ["admin", "manager"]


@router.post("/", response_model=schemas.SupplierCreateResponse)
def create_supplier(
    payload: schemas.SupplierCreate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    supplier = SupplierService.create_supplier(
        db=db,
        business_id=ctx.business_id,
        payload=payload,
    )
    return {"data": supplier, "message": "Supplier created successfully"}


@router.get("/", response_model=schemas.SupplierListResponse)
def get_suppliers(
    search: Annotated[Optional[str], Query()] = None,
    is_active: Annotated[Optional[bool], Query()] = True,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    items, total = SupplierService.list_suppliers(
        db=db,
        business_id=ctx.business_id,
        search=search,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    return {"data": items, "total": total, "message": "All suppliers fetched"}


@router.get("/{supplier_id}", response_model=schemas.SupplierResponse)
def get_supplier_by_id(
    supplier_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    supplier = SupplierService.get_supplier(
        db=db,
        business_id=ctx.business_id,
        supplier_id=supplier_id,
    )
    return {"data": supplier, "message": "Supplier fetched successfully"}


@router.put("/{supplier_id}", response_model=schemas.SupplierResponse)
def update_supplier(
    supplier_id: int,
    payload: schemas.SupplierUpdate,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    supplier = SupplierService.update_supplier(
        db=db,
        business_id=ctx.business_id,
        supplier_id=supplier_id,
        payload=payload,
    )
    return {"data": supplier, "message": "Supplier updated"}


@router.patch("/{supplier_id}", response_model=schemas.SupplierResponse)
def deactivate_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    supplier = SupplierService.set_active_status(
        db=db,
        business_id=ctx.business_id,
        supplier_id=supplier_id,
        is_active=False,
    )
    return {"data": supplier, "message": "Supplier deactivated"}


@router.patch("/{supplier_id}/activate", response_model=schemas.SupplierResponse)
def activate_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    supplier = SupplierService.set_active_status(
        db=db,
        business_id=ctx.business_id,
        supplier_id=supplier_id,
        is_active=True,
    )
    return {"data": supplier, "message": "Supplier activated successfully"}


@router.patch("/{supplier_id}/link-workspace", response_model=schemas.SupplierResponse)
def link_supplier_workspace(
    supplier_id: int,
    payload: schemas.SupplierLinkWorkspaceRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(WRITE_ROLES)),
):
    supplier = SupplierService.link_workspace(
        db=db,
        business_id=ctx.business_id,
        supplier_id=supplier_id,
        supplier_business_id=payload.supplier_business_id,
    )
    return {"data": supplier, "message": "Supplier workspace link updated"}
