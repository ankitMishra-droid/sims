import logging
from typing import Dict, List, Optional
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from . import stock_service

logger = logging.getLogger("sims.inventory")


class InventoryService:
    @staticmethod
    def get_incoming_stock_map(
        db: Session,
        business_id: int,
        product_ids: Optional[List[int]] = None,
    ) -> Dict[int, int]:
        """
        Compute outstanding incoming stock from valid open POs (SENT or PARTIALLY_RECEIVED).
        Excludes DRAFT, CANCELLED, and already-received quantities.
        """
        query = (
            db.query(
                models.PurchaseOrderItem.product_id,
                func.coalesce(
                    func.sum(
                        models.PurchaseOrderItem.ordered_quantity
                        - models.PurchaseOrderItem.received_quantity
                    ),
                    0,
                ).label("incoming_qty"),
            )
            .join(
                models.PurchaseOrder,
                models.PurchaseOrder.id == models.PurchaseOrderItem.purchase_order_id,
            )
            .filter(
                models.PurchaseOrder.business_id == business_id,
                models.PurchaseOrder.status.in_(
                    [
                        models.PurchaseOrderStatus.SENT,
                        models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
                    ]
                ),
            )
        )
        if product_ids is not None:
            if not product_ids:
                return {}
            query = query.filter(models.PurchaseOrderItem.product_id.in_(product_ids))

        rows = query.group_by(models.PurchaseOrderItem.product_id).all()
        return {pid: max(0, qty or 0) for pid, qty in rows}

    @classmethod
    def get_inventory_positions(
        cls,
        db: Session,
        business_id: int,
        product_id: Optional[int] = None,
    ) -> List[dict]:
        query = db.query(models.Product).filter(
            models.Product.business_id == business_id,
            models.Product.is_active.is_(True),
        )
        if product_id is not None:
            query = query.filter(models.Product.id == product_id)

        products = query.order_by(models.Product.id.asc()).all()
        if product_id is not None and not products:
            raise HTTPException(status_code=404, detail="Product not found")

        incoming_map = cls.get_incoming_stock_map(
            db, business_id, [p.id for p in products]
        )
        results = []
        for p in products:
            on_hand = p.current_stock or 0
            incoming = incoming_map.get(p.id, 0)
            reserved = 0  # Reservations not yet implemented
            available = on_hand - reserved
            inv_pos = on_hand + incoming - reserved
            unit_cost = float(p.cost_price or 0.0)
            results.append(
                {
                    "product_id": p.id,
                    "sku": p.sku,
                    "name": p.name,
                    "on_hand_stock": on_hand,
                    "incoming_stock": incoming,
                    "reserved_stock": reserved,
                    "available_stock": available,
                    "inventory_position": inv_pos,
                    "reorder_level": p.reorder_level or 0,
                    "unit_cost": round(unit_cost, 2),
                    "inventory_value": round(on_hand * unit_cost, 2),
                    "reservations_supported": False,
                }
            )
        return results

    @classmethod
    def stock_in(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        payload: schemas.StockInCreate,
    ) -> dict:
        try:
            product, _log = stock_service.apply_stock_movement(
                db,
                business_id=business_id,
                product_id=payload.product_id,
                delta=payload.quantity,
                movement_type=stock_service.MovementType.STOCK_ADJUSTMENT,
                reason=payload.reason,
                user_id=user_id,
                reference_type="manual_stock_in",
            )
            db.commit()
            db.refresh(product)
            return {
                "message": "Stock added successfully",
                "product_id": product.id,
                "added_quantity": payload.quantity,
                "current_stock": product.current_stock,
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Failed stock_in product_id=%s", payload.product_id)
            raise HTTPException(status_code=500, detail="Failed to add stock.")

    @classmethod
    def adjust_stock(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        allow_negative: bool,
        payload: schemas.StockAdjustmentCreate,
    ) -> dict:
        allowed_types = {
            stock_service.MovementType.STOCK_ADJUSTMENT.value,
            stock_service.MovementType.OPENING_STOCK.value,
            stock_service.MovementType.RETURN.value,
            stock_service.MovementType.REVERSAL.value,
        }
        mtype = payload.movement_type.upper()
        if mtype not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Unsupported adjustment movement_type '{payload.movement_type}'")

        try:
            product, log = stock_service.apply_stock_movement(
                db,
                business_id=business_id,
                product_id=payload.product_id,
                delta=payload.quantity_delta,
                movement_type=mtype,
                reason=payload.reason,
                user_id=user_id,
                reference_type="stock_adjustment",
                allow_negative=allow_negative,
            )
            db.commit()
            db.refresh(product)
            db.refresh(log)
            return {
                "message": "Stock adjusted successfully",
                "product_id": product.id,
                "previous_stock": log.previous_stock,
                "quantity_delta": payload.quantity_delta,
                "current_stock": product.current_stock,
                "log_id": log.id,
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Failed adjust_stock product_id=%s", payload.product_id)
            raise HTTPException(status_code=500, detail="Failed to adjust stock.")

    @staticmethod
    def get_logs(
        db: Session,
        business_id: int,
        product_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[models.InventoryLog]:
        stock_service.get_product_or_404(db, product_id, business_id=business_id)
        return (
            db.query(models.InventoryLog)
            .filter(
                models.InventoryLog.business_id == business_id,
                models.InventoryLog.product_id == product_id,
            )
            .order_by(models.InventoryLog.timestamp.desc(), models.InventoryLog.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_low_stock_products(db: Session, business_id: int) -> List[models.Product]:
        return (
            db.query(models.Product)
            .filter(
                models.Product.business_id == business_id,
                models.Product.is_active.is_(True),
                models.Product.current_stock <= models.Product.reorder_level,
            )
            .order_by(models.Product.current_stock.asc())
            .all()
        )
