import csv
from io import StringIO
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
        on_hand = product.current_stock or 0
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
            "reorder_level": product.reorder_level or 0,
            "min_order_quantity": product.min_order_quantity or 1,
            "order_pack_size": product.order_pack_size or 1,
            "max_stock_level": getattr(product, "max_stock_level", None),
            "review_period_days": product.review_period_days or 7,
            "service_level_target": float(getattr(product, "service_level_target", 0.95) or 0.95),
            "initial_daily_demand": getattr(product, "initial_daily_demand", None),
            "supplier_id": product.supplier_id,
            "is_active": product.is_active,
            "incoming_stock": incoming,
            "reserved_stock": reserved,
            "available_stock": on_hand - reserved,
            "inventory_position": on_hand + incoming - reserved,
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
        except Exception:
            db.rollback()
            logger.exception("Failed creating product business_id=%s", business_id)
            raise HTTPException(status_code=500, detail="Failed to create product.")

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
        except Exception:
            db.rollback()
            logger.exception("Failed updating product id=%s", product_id)
            raise HTTPException(status_code=500, detail="Failed to update product.")

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

    @classmethod
    def import_products_csv(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        raw_bytes: bytes,
        *,
        max_rows: int = 2000,
    ) -> dict:
        if not raw_bytes or not raw_bytes.strip():
            raise HTTPException(status_code=400, detail="Uploaded CSV file is empty.")

        text = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="Unable to decode CSV file text.")

        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV header row is missing.")

        normalized_fields = [str(f or "").strip().lower() for f in reader.fieldnames]
        if "sku" not in normalized_fields or "name" not in normalized_fields:
            raise HTTPException(status_code=400, detail="CSV must contain required 'sku' and 'name' headers.")

        existing_skus = {
            row[0].strip().lower()
            for row in db.query(models.Product.sku)
            .filter(models.Product.business_id == business_id)
            .all()
            if row[0]
        }
        suppliers = (
            db.query(models.Supplier)
            .filter(models.Supplier.business_id == business_id)
            .all()
        )
        sup_by_id = {s.id: s.id for s in suppliers}
        sup_by_name = {s.name.strip().lower(): s.id for s in suppliers if s.name}

        created_skus: List[str] = []
        skipped_count = 0
        errors: List[dict] = []

        for idx, raw_row in enumerate(reader, start=2):
            if idx - 1 > max_rows:
                errors.append({"row": idx, "sku": None, "reason": f"Exceeded maximum {max_rows} rows per CSV upload."})
                break

            row = {str(k or "").strip().lower(): (str(v).strip() if v is not None else "") for k, v in raw_row.items()}
            if not any(row.values()):
                continue

            sku = row.get("sku", "")
            name = row.get("name", "")
            if not sku or not name:
                errors.append({"row": idx, "sku": sku or None, "reason": "Missing SKU or product name."})
                continue

            sku_key = sku.lower()
            if sku_key in existing_skus:
                skipped_count += 1
                errors.append({"row": idx, "sku": sku, "reason": "Duplicate SKU already exists in workspace."})
                continue

            sup_id = None
            raw_sup_id = row.get("supplier_id", "")
            raw_sup_name = row.get("supplier_name", "")
            if raw_sup_id:
                try:
                    cand = int(raw_sup_id)
                    if cand not in sup_by_id:
                        errors.append({"row": idx, "sku": sku, "reason": f"Supplier ID {cand} not found in workspace."})
                        continue
                    sup_id = cand
                except ValueError:
                    errors.append({"row": idx, "sku": sku, "reason": "Invalid supplier_id."})
                    continue
            elif raw_sup_name:
                sup_id = sup_by_name.get(raw_sup_name.lower())
                if sup_id is None:
                    errors.append({"row": idx, "sku": sku, "reason": f"Supplier '{raw_sup_name}' not found."})
                    continue

            try:
                payload = schemas.ProductCreate(
                    sku=sku,
                    name=name,
                    category=row.get("category") or "General",
                    unit=row.get("unit") or "piece",
                    cost_price=float(row.get("cost_price") or 0),
                    selling_price=float(row.get("selling_price") or 0),
                    current_stock=int(float(row.get("current_stock") or 0)),
                    reorder_level=int(float(row.get("reorder_level") or 10)),
                    supplier_id=sup_id,
                )
            except Exception as exc:
                errors.append({"row": idx, "sku": sku, "reason": str(exc).splitlines()[0][:180]})
                continue

            try:
                with db.begin_nested():
                    prod = models.Product(
                        business_id=business_id,
                        **payload.model_dump(),
                        is_active=True,
                    )
                    db.add(prod)
                    db.flush()
                    stock_service.record_opening_stock(db, product=prod, user_id=user_id)
                existing_skus.add(sku_key)
                created_skus.append(payload.sku)
            except Exception:
                errors.append({"row": idx, "sku": sku, "reason": "Database constraint prevented importing row."})

        db.commit()
        return {
            "created_count": len(created_skus),
            "skipped_count": skipped_count,
            "error_count": len(errors),
            "created_skus": created_skus,
            "errors": errors,
            "message": f"Imported {len(created_skus)} products ({skipped_count} duplicate SKUs skipped).",
        }
