from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models,schemas
from ..database import get_db

router = APIRouter(prefix="/api/suppliers", tags=["Suppliers"])

# create supplier
@router.post("/", response_model=schemas.SupplierCreateResponse)
def create_supplier(payload: schemas.SupplierCreate, db: Session = Depends(get_db)):
    existing_supplier = db.query(models.Supplier).filter(models.Supplier.email == payload.email or models.Supplier.name == payload.name).first()

    if existing_supplier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Supplier with this email or name already exists"
        )

    supplier = models.Supplier(**payload.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)

    return {
        "data": supplier,
        "message": "supplier created successfully"
    }

# get supplier 
@router.get("/", response_model=schemas.SupplierListResponse)
def get_suppliers(db: Session = Depends(get_db)):
    supplier_details = db.query(models.Supplier).filter(models.Supplier.is_active.is_(True)).order_by(models.Supplier.name).all()

    if not supplier_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active suppliers found"
        )

    return {
        "data": supplier_details,
        "message": "all suppliers detail fetched"
    }

# get specific supplier by their id
@router.get("/{supplier_id}", response_model=schemas.SupplierResponse)
def get_spplier_by_id(supplier_id: int, db: Session = Depends(get_db)):
    supplier = db.query(models.Supplier).filter(models.Supplier.id == supplier_id).first()

    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found"
        )

    return {
        "data": supplier,
        "message": "supplier detail fetched successfully"
    }

# update supplier by id
@router.put("/{supplier_id}", response_model=schemas.SupplierResponse)
def update_supplier(supplier_id: int, payload: schemas.SupplierUpdate, db: Session = Depends(get_db)):
    supplier = db.query(models.Supplier).filter(models.Supplier.id == supplier_id).first()

    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found"
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)

    db.commit()
    db.refresh(supplier)

    return {
        "data": supplier,
        "message": "supplier updated"
    }

# deactivate supplier
@router.patch("/{supplier_id}", response_model=schemas.SupplierResponse)
def deactivate_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = db.query(models.Supplier).filter(models.Supplier.id == supplier_id).first()

    if not supplier:
        raise(HTTPException(status_code=404, detail="supplier not found"))

    if not supplier.is_active:
        raise(HTTPException(status_code=400, detail="supplier is already deactivated"))

    supplier.is_active = False
    
    db.commit()
    db.refresh(supplier)

    return {
        "data": supplier,
        "message": "supplier deactivated"
    }

# activate supplier
@router.patch("/{supplier_id}/activate", response_model=schemas.SupplierResponse)
def activate_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = (
        db.query(models.Supplier)
        .filter(models.Supplier.id == supplier_id)
        .first()
    )

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )

    if supplier.is_active:
        raise HTTPException(
            status_code=400,
            detail="Supplier is already active"
        )

    supplier.is_active = True

    db.commit()
    db.refresh(supplier)

    return {
        "data": supplier,
        "message": "Supplier activated successfully"
    }
