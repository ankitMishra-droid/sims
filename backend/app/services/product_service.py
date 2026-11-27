import logging
from typing import Dict, List, Optional, Tuple
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas
from . import stock_service
from .inventory_service import InventoryService

logger = logging.getLogger("sims.products")


class ProductService:
    @staticmethod
    def _attach_position(product: models.Product, incoming: int) -> dict:
        on_hand = int(product.current_stock or 0)
        reserved = 0
        return {
            "id": product.id,
            "business_id": product.business_id,
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "unit": product.unit,
            "cost_price": float(product.cost_price or 0.0),
            "selling_price": float(product.selling_price or 0.0),
            "current_stock": on_hand,
            "reorder_level": int(product.reorder_level or 0),
            "supplier_id": product.supplier_id,
            "is_active": bool(product.is_active),
            "incoming_stock": int(incoming),
            "reserved_stock": reserved,
            "available_stock": on_hand - reserved,
            "inventory_position": on_hand + int(incoming) - reserved,
        }

    @classmethod
    def list_products(
        cls,
        db: Session,
        business_id: int,
        *,
        search: Optional[str] = None,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
        stock_status: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> Tuple[List[dict], int]:
        query = db.query(models.Product).filter(models.Product.business_id == business_id)

        if is_active is not None:
            query = query.filter(models.Product.is_active == is_active)

        if category and category.upper() != "ALL":
            query = query.filter(models.Product.category == category)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    models.Product.name.ilike(term),
                    models.Product.sku.ilike(term),
                    models.Product.category.ilike(term),
                )
            )

        if stock_status:
            norm = stock_status.upper()
            if norm == "OUT":
                query = query.filter(models.Product.current_stock == 0)
            elif norm == "LOW":
                query = query.filter(
                    models.Product.current_stock <= models.Product.reorder_level,
                    models.Product.current_stock > 0,
                )
            elif norm == "HEALTHY":
                query = query.filter(models.Product.current_stock > models.Product.reorder_level)

        total = query.count()
        items = query.order_by(models.Product.id.asc()).offset(skip).limit(limit).all()
        incoming_map = InventoryService.get_incoming_stock_map(
            db, business_id, [p.id for p in items]
        )
        return [cls._attach_position(p, incoming_map.get(p.id, 0)) for p in items], total

    @classmethod
    def get_product(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
        *,
        include_inactive: bool = False,
    ) -> dict:
        query = db.query(models.Product).filter(
            models.Product.id == product_id,
            models.Product.business_id == business_id,
        )
        if not include_inactive:
            query = query.filter(models.Product.is_active.is_(True))
        product = query.first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        incoming_map = InventoryService.get_incoming_stock_map(db, business_id, [product.id])
        return cls._attach_position(product, incoming_map.get(product.id, 0))

    @classmethod
    def create_product(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        payload: schemas.ProductCreate,
    ) -> dict:
        existing = (
            db.query(models.Product)
            .filter(
                models.Product.business_id == business_id,
                models.Product.sku == payload.sku,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="SKU already exists")

        if payload.supplier_id is not None:
            supplier = (
                db.query(models.Supplier)
                .filter(
                    models.Supplier.id == payload.supplier_id,
                    models.Supplier.business_id == business_id,
                )
                .first()
            )
            if not supplier:
                raise HTTPException(status_code=404, detail="Supplier not found in workspace")

        try:
            db_product = models.Product(
                business_id=business_id,
                **payload.model_dump(),
                is_active=True,
            )
            db.add(db_product)
            db.flush()

            stock_service.record_opening_stock(db, product=db_product, user_id=user_id)
            db.commit()
            db.refresh(db_product)
            logger.info("Product created id=%s business_id=%s sku=%s", db_product.id, business_id, db_product.sku)
            return cls._attach_position(db_product, 0)
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Failed creating product business_id=%s", business_id)
            raise HTTPException(status_code=500, detail=f"Failed to create product: {exc}")

    @classmethod
    def update_product(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
        payload: schemas.ProductUpdate,
    ) -> dict:
        product = (
            db.query(models.Product)
            .filter(
                models.Product.id == product_id,
                models.Product.business_id == business_id,
            )
            .first()
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        updates = payload.model_dump(exclude_unset=True)
        if "sku" in updates and updates["sku"] != product.sku:
            dup = (
                db.query(models.Product)
                .filter(
                    models.Product.business_id == business_id,
                    models.Product.sku == updates["sku"],
                    models.Product.id != product_id,
                )
                .first()
            )
            if dup:
                raise HTTPException(status_code=400, detail="SKU already exists")

        if "supplier_id" in updates and updates["supplier_id"] is not None:
            supplier = (
                db.query(models.Supplier)
                .filter(
                    models.Supplier.id == updates["supplier_id"],
                    models.Supplier.business_id == business_id,
                )
                .first()
            )
            if not supplier:
                raise HTTPException(status_code=404, detail="Supplier not found in workspace")

        try:
            for key, value in updates.items():
                setattr(product, key, value)
            db.commit()
            db.refresh(product)
            incoming_map = InventoryService.get_incoming_stock_map(db, business_id, [product.id])
            return cls._attach_position(product, incoming_map.get(product.id, 0))
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Failed updating product id=%s", product_id)
            raise HTTPException(status_code=500, detail=f"Failed to update product: {exc}")

    @classmethod
    def set_active_status(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
        is_active: bool,
    ) -> dict:
        product = (
            db.query(models.Product)
            .filter(
                models.Product.id == product_id,
                models.Product.business_id == business_id,
            )
            .first()
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        product.is_active = is_active
        db.commit()
        db.refresh(product)
        incoming_map = InventoryService.get_incoming_stock_map(db, business_id, [product.id])
        return cls._attach_position(product, incoming_map.get(product.id, 0))
