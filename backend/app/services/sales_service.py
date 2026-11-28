import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from . import stock_service

logger = logging.getLogger("sims.sales")


class SalesService:
    @classmethod
    def create_sale(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        allow_negative_stock: bool,
        payload: schemas.SaleCreate,
        idempotency_key: Optional[str] = None,
    ) -> models.Sale:
        effective_idem = (idempotency_key or payload.idempotency_key or "").strip() or None
        if effective_idem:
            existing_sale = (
                db.query(models.Sale)
                .filter(
                    models.Sale.business_id == business_id,
                    models.Sale.idempotency_key == effective_idem,
                )
                .first()
            )
            if existing_sale:
                return existing_sale

        product = (
            db.query(models.Product)
            .filter(
                models.Product.id == payload.product_id,
                models.Product.business_id == business_id,
                models.Product.is_active.is_(True),
            )
            .first()
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Backend authoritative pricing & total calculation
        unit_price = (
            float(payload.selling_price)
            if payload.selling_price is not None
            else float(product.selling_price or 0.0)
        )
        if unit_price < 0:
            raise HTTPException(status_code=400, detail="Selling price cannot be negative")

        revenue = round(unit_price * payload.quantity_sold, 2)

        try:
            db_sale = models.Sale(
                business_id=business_id,
                product_id=product.id,
                quantity_sold=payload.quantity_sold,
                selling_price=unit_price,
                revenue=revenue,
                status="COMPLETED",
                created_by=user_id,
                idempotency_key=effective_idem,
                notes=payload.notes,
            )
            db.add(db_sale)
            db.flush()

            stock_service.decrease_stock(
                db=db,
                product_id=product.id,
                quantity=payload.quantity_sold,
                reason="sale",
                reference_type="sale",
                reference_id=db_sale.id,
                business_id=business_id,
                user_id=user_id,
                movement_type=stock_service.MovementType.SALE,
                allow_negative=allow_negative_stock,
            )

            db.commit()
            db.refresh(db_sale)
            logger.info(
                "Sale recorded id=%s business_id=%s product_id=%s qty=%s",
                db_sale.id,
                business_id,
                product.id,
                payload.quantity_sold,
            )
            return db_sale
        except IntegrityError:
            db.rollback()
            if effective_idem:
                existing_sale = (
                    db.query(models.Sale)
                    .filter(
                        models.Sale.business_id == business_id,
                        models.Sale.idempotency_key == effective_idem,
                    )
                    .first()
                )
                if existing_sale:
                    return existing_sale
            raise HTTPException(status_code=400, detail="Duplicate or invalid sale transaction")
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Failed creating sale product_id=%s", payload.product_id)
            raise HTTPException(status_code=500, detail="Failed to record sale.")

    @classmethod
    def cancel_sale(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        sale_id: int,
        reason: str = "sale_cancelled",
    ) -> models.Sale:
        sale = (
            db.query(models.Sale)
            .filter(
                models.Sale.id == sale_id,
                models.Sale.business_id == business_id,
            )
            .first()
        )
        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")
        if sale.status == "CANCELLED":
            raise HTTPException(status_code=400, detail="Sale is already cancelled")

        try:
            sale.status = "CANCELLED"
            stock_service.increase_stock(
                db=db,
                product_id=sale.product_id,
                quantity=sale.quantity_sold,
                reason=reason,
                reference_type="sale",
                reference_id=sale.id,
                business_id=business_id,
                user_id=user_id,
                movement_type=stock_service.MovementType.REVERSAL,
            )
            db.commit()
            db.refresh(sale)
            return sale
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Failed cancelling sale id=%s", sale_id)
            raise HTTPException(status_code=500, detail="Failed to cancel sale.")

    @staticmethod
    def list_sales(
        db: Session,
        business_id: int,
        *,
        product_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 500,
    ) -> Tuple[List[models.Sale], int]:
        query = db.query(models.Sale).filter(models.Sale.business_id == business_id)
        if product_id is not None:
            query = query.filter(models.Sale.product_id == product_id)
        if start_date:
            try:
                dt_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if dt_start.tzinfo is not None:
                    dt_start = dt_start.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format (expected ISO date)")
            query = query.filter(models.Sale.sales_date >= dt_start)
        if end_date:
            try:
                dt_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if dt_end.tzinfo is not None:
                    dt_end = dt_end.astimezone(timezone.utc).replace(tzinfo=None)
                if len(end_date) == 10:
                    dt_end = dt_end.replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format (expected ISO date)")
            query = query.filter(models.Sale.sales_date <= dt_end)

        total = query.count()
        items = (
            query.order_by(models.Sale.sales_date.desc(), models.Sale.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    @staticmethod
    def get_sale(db: Session, business_id: int, sale_id: int) -> models.Sale:
        sale = (
            db.query(models.Sale)
            .filter(
                models.Sale.id == sale_id,
                models.Sale.business_id == business_id,
            )
            .first()
        )
        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")
        return sale
