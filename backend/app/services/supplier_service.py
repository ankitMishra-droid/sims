import logging
from typing import List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas

logger = logging.getLogger("sims.suppliers")


class SupplierService:
    @staticmethod
    def list_suppliers(
        db: Session,
        business_id: int,
        *,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 200,
    ) -> Tuple[List[models.Supplier], int]:
        query = db.query(models.Supplier).filter(models.Supplier.business_id == business_id)
        if is_active is not None:
            query = query.filter(models.Supplier.is_active == is_active)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    models.Supplier.name.ilike(term),
                    models.Supplier.contact_person.ilike(term),
                    models.Supplier.email.ilike(term),
                    models.Supplier.phone.ilike(term),
                )
            )

        total = query.count()
        items = query.order_by(models.Supplier.name.asc()).offset(skip).limit(limit).all()
        return items, total

    @staticmethod
    def get_supplier(db: Session, business_id: int, supplier_id: int) -> models.Supplier:
        supplier = (
            db.query(models.Supplier)
            .filter(
                models.Supplier.id == supplier_id,
                models.Supplier.business_id == business_id,
            )
            .first()
        )
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
        return supplier

    @staticmethod
    def create_supplier(
        db: Session,
        business_id: int,
        payload: schemas.SupplierCreate,
    ) -> models.Supplier:
        # Check duplicate name within tenant; only check email if email was provided (prevent NULL == NULL)
        filters = [models.Supplier.name == payload.name]
        if payload.email:
            filters.append(models.Supplier.email == payload.email)

        existing = (
            db.query(models.Supplier)
            .filter(
                models.Supplier.business_id == business_id,
                or_(*filters),
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supplier with this name or email already exists",
            )

        try:
            supplier = models.Supplier(business_id=business_id, **payload.model_dump())
            db.add(supplier)
            db.commit()
            db.refresh(supplier)
            logger.info("Supplier created id=%s business_id=%s", supplier.id, business_id)
            return supplier
        except Exception:
            db.rollback()
            logger.exception("Failed creating supplier business_id=%s", business_id)
            raise HTTPException(status_code=500, detail="Failed to create supplier.")

    @classmethod
    def update_supplier(
        cls,
        db: Session,
        business_id: int,
        supplier_id: int,
        payload: schemas.SupplierUpdate,
    ) -> models.Supplier:
        supplier = cls.get_supplier(db, business_id, supplier_id)
        updates = payload.model_dump(exclude_unset=True)

        if "name" in updates and updates["name"] != supplier.name:
            dup_name = (
                db.query(models.Supplier)
                .filter(
                    models.Supplier.business_id == business_id,
                    models.Supplier.name == updates["name"],
                    models.Supplier.id != supplier_id,
                )
                .first()
            )
            if dup_name:
                raise HTTPException(status_code=400, detail="Supplier name already exists")

        if "email" in updates and updates["email"]:
            dup_email = (
                db.query(models.Supplier)
                .filter(
                    models.Supplier.business_id == business_id,
                    models.Supplier.email == str(updates["email"]),
                    models.Supplier.id != supplier_id,
                )
                .first()
            )
            if dup_email:
                raise HTTPException(status_code=400, detail="Supplier email already exists")

        try:
            for field, value in updates.items():
                setattr(supplier, field, value)
            db.commit()
            db.refresh(supplier)
            return supplier
        except Exception:
            db.rollback()
            logger.exception("Failed updating supplier id=%s business_id=%s", supplier_id, business_id)
            raise HTTPException(status_code=500, detail="Failed to update supplier.")

    @classmethod
    def set_active_status(
        cls,
        db: Session,
        business_id: int,
        supplier_id: int,
        is_active: bool,
    ) -> models.Supplier:
        supplier = cls.get_supplier(db, business_id, supplier_id)
        if supplier.is_active == is_active:
            state_str = "active" if is_active else "deactivated"
            raise HTTPException(status_code=400, detail=f"Supplier is already {state_str}")
        supplier.is_active = is_active
        db.commit()
        db.refresh(supplier)
        return supplier

    @classmethod
    def link_workspace(
        cls,
        db: Session,
        business_id: int,
        supplier_id: int,
        supplier_business_id: Optional[int],
    ) -> models.Supplier:
        supplier = cls.get_supplier(db, business_id, supplier_id)
        if supplier_business_id is None:
            supplier.linked_business_id = None
            db.commit()
            db.refresh(supplier)
            return supplier

        target_biz = (
            db.query(models.Business)
            .filter(
                models.Business.id == supplier_business_id,
                models.Business.is_active.is_(True),
            )
            .first()
        )
        if not target_biz or target_biz.business_type.lower() != "supplier":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target workspace must be an active supplier-type business.",
            )
        supplier.linked_business_id = target_biz.id
        db.commit()
        db.refresh(supplier)
        return supplier
