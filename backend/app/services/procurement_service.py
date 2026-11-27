import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from . import stock_service

logger = logging.getLogger("sims.procurement")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ProcurementService:
    @staticmethod
    def _validate_and_merge_items(
        db: Session,
        business_id: int,
        items: List[schemas.PurchaseOrderItemCreate],
    ) -> Tuple[List[dict], float]:
        merged: Dict[int, dict] = {}
        for item in items:
            if item.product_id in merged:
                if abs(float(merged[item.product_id]["unit_cost"]) - float(item.unit_cost)) > 1e-6:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Duplicate product_id {item.product_id} with conflicting unit_cost",
                    )
                merged[item.product_id]["ordered_quantity"] += item.ordered_quantity
            else:
                merged[item.product_id] = {
                    "product_id": item.product_id,
                    "ordered_quantity": item.ordered_quantity,
                    "unit_cost": round(float(item.unit_cost), 2),
                }

        product_ids = set(merged.keys())
        products = (
            db.query(models.Product)
            .filter(
                models.Product.id.in_(product_ids),
                models.Product.business_id == business_id,
                models.Product.is_active.is_(True),
            )
            .all()
        )
        if len(products) != len(product_ids):
            raise HTTPException(
                status_code=404,
                detail="One or more active products were not found in this workspace",
            )

        total_amount = round(
            sum(v["ordered_quantity"] * v["unit_cost"] for v in merged.values()),
            2,
        )
        return list(merged.values()), total_amount

    @classmethod
    def create_purchase_order(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        payload: schemas.PurchaseOrderCreate,
    ) -> models.PurchaseOrder:
        supplier = (
            db.query(models.Supplier)
            .filter(
                models.Supplier.id == payload.supplier_id,
                models.Supplier.business_id == business_id,
                models.Supplier.is_active.is_(True),
            )
            .first()
        )
        if not supplier:
            raise HTTPException(status_code=404, detail="Active supplier not found")

        merged_items, total_amount = cls._validate_and_merge_items(db, business_id, payload.items)

        try:
            order = models.PurchaseOrder(
                business_id=business_id,
                supplier_id=payload.supplier_id,
                expected_delivery_date=payload.expected_delivery_date,
                notes=payload.notes,
                status=models.PurchaseOrderStatus.DRAFT,
                total_amount=total_amount,
                created_by=user_id,
            )
            for item in merged_items:
                order.items.append(
                    models.PurchaseOrderItem(
                        product_id=item["product_id"],
                        ordered_quantity=item["ordered_quantity"],
                        received_quantity=0,
                        unit_cost=item["unit_cost"],
                    )
                )

            db.add(order)
            db.flush()
            order.order_number = f"PO-{order.id:04d}"
            db.commit()
            db.refresh(order)
            logger.info("PurchaseOrder created id=%s business_id=%s status=DRAFT", order.id, business_id)
            return order
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Failed creating purchase order business_id=%s", business_id)
            raise HTTPException(status_code=500, detail=f"Failed to create purchase order: {exc}")

    @staticmethod
    def list_purchase_orders(
        db: Session,
        business_id: int,
        *,
        status_filter: Optional[str] = None,
        supplier_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[models.PurchaseOrder]:
        query = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.business_id == business_id)
        if status_filter and status_filter.upper() != "ALL":
            try:
                status_enum = models.PurchaseOrderStatus(status_filter.upper())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid PO status filter '{status_filter}'")
            query = query.filter(models.PurchaseOrder.status == status_enum)
        if supplier_id is not None:
            query = query.filter(models.PurchaseOrder.supplier_id == supplier_id)
        return (
            query.order_by(models.PurchaseOrder.order_date.desc(), models.PurchaseOrder.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_purchase_order(db: Session, business_id: int, order_id: int) -> models.PurchaseOrder:
        order = (
            db.query(models.PurchaseOrder)
            .filter(
                models.PurchaseOrder.id == order_id,
                models.PurchaseOrder.business_id == business_id,
            )
            .first()
        )
        if not order:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        return order

    @classmethod
    def update_draft_purchase_order(
        cls,
        db: Session,
        business_id: int,
        order_id: int,
        payload: schemas.PurchaseOrderUpdate,
    ) -> models.PurchaseOrder:
        order = cls.get_purchase_order(db, business_id, order_id)
        if order.status != models.PurchaseOrderStatus.DRAFT:
            raise HTTPException(
                status_code=400,
                detail="Only DRAFT purchase orders can be updated",
            )

        updates = payload.model_dump(exclude_unset=True)
        try:
            if "expected_delivery_date" in updates:
                order.expected_delivery_date = updates["expected_delivery_date"]
            if "notes" in updates:
                order.notes = updates["notes"]
            if payload.items is not None:
                if not payload.items:
                    raise HTTPException(status_code=400, detail="Purchase order must contain at least one item")
                merged_items, total_amount = cls._validate_and_merge_items(db, business_id, payload.items)
                order.items.clear()
                db.flush()
                for item in merged_items:
                    order.items.append(
                        models.PurchaseOrderItem(
                            product_id=item["product_id"],
                            ordered_quantity=item["ordered_quantity"],
                            received_quantity=0,
                            unit_cost=item["unit_cost"],
                        )
                    )
                order.total_amount = total_amount

            db.commit()
            db.refresh(order)
            return order
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to update purchase order: {exc}")

    @classmethod
    def delete_draft_purchase_order(cls, db: Session, business_id: int, order_id: int) -> None:
        order = cls.get_purchase_order(db, business_id, order_id)
        if order.status not in (models.PurchaseOrderStatus.DRAFT, models.PurchaseOrderStatus.CANCELLED):
            raise HTTPException(
                status_code=400,
                detail="Only DRAFT or CANCELLED purchase orders can be deleted",
            )
        db.delete(order)
        db.commit()

    @classmethod
    def send_purchase_order(cls, db: Session, business_id: int, order_id: int) -> models.PurchaseOrder:
        order = cls.get_purchase_order(db, business_id, order_id)
        if order.status != models.PurchaseOrderStatus.DRAFT:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot send purchase order in status '{order.status.value}'",
            )
        if not order.items:
            raise HTTPException(status_code=400, detail="Cannot send an empty purchase order")
        order.status = models.PurchaseOrderStatus.SENT
        order.sent_at = _utcnow()
        db.commit()
        db.refresh(order)
        return order

    @classmethod
    def cancel_purchase_order(cls, db: Session, business_id: int, order_id: int) -> models.PurchaseOrder:
        order = cls.get_purchase_order(db, business_id, order_id)
        if order.status == models.PurchaseOrderStatus.CANCELLED:
            raise HTTPException(status_code=400, detail="Purchase order is already cancelled")
        if order.status in (
            models.PurchaseOrderStatus.RECEIVED,
            models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel a purchase order that has already received stock",
            )
        order.status = models.PurchaseOrderStatus.CANCELLED
        order.cancelled_at = _utcnow()
        db.commit()
        db.refresh(order)
        return order

    @classmethod
    def receive_goods(
        cls,
        db: Session,
        business_id: int,
        user_id: Optional[int],
        order_id: int,
        items_to_receive: Optional[List[schemas.ReceiveItem]] = None,
        idempotency_key: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> models.PurchaseOrder:
        """
        Authoritative transactional goods receipt handler (supports full or partial line receipts).
        """
        effective_idem = (idempotency_key or "").strip() or None
        if effective_idem:
            existing_receipt = (
                db.query(models.GoodsReceipt)
                .filter(
                    models.GoodsReceipt.business_id == business_id,
                    models.GoodsReceipt.idempotency_key == effective_idem,
                )
                .first()
            )
            if existing_receipt:
                return cls.get_purchase_order(db, business_id, order_id)

        order = cls.get_purchase_order(db, business_id, order_id)
        if order.status == models.PurchaseOrderStatus.CANCELLED:
            raise HTTPException(status_code=400, detail="Cannot receive a cancelled purchase order")
        if order.status == models.PurchaseOrderStatus.RECEIVED:
            raise HTTPException(status_code=400, detail="Purchase order has already been fully received")
        if order.status == models.PurchaseOrderStatus.DRAFT:
            raise HTTPException(
                status_code=400,
                detail="Purchase order must be sent before receiving goods",
            )

        # Build receipt lines
        if items_to_receive is None:
            requested_lines = [
                (item, max(0, item.ordered_quantity - item.received_quantity))
                for item in order.items
                if (item.ordered_quantity - item.received_quantity) > 0
            ]
            if not requested_lines:
                raise HTTPException(status_code=400, detail="No remaining quantities to receive")
        else:
            item_map = {item.id: item for item in order.items}
            merged_qty: Dict[int, int] = {}
            for req_item in items_to_receive:
                if req_item.purchase_order_item_id not in item_map:
                    raise HTTPException(status_code=404, detail="Purchase order item not found")
                merged_qty[req_item.purchase_order_item_id] = (
                    merged_qty.get(req_item.purchase_order_item_id, 0) + req_item.received_quantity
                )
            requested_lines = [(item_map[item_id], qty) for item_id, qty in merged_qty.items()]

        try:
            receipt = models.GoodsReceipt(
                receipt_number=f"GR-TMP-{order.id}",
                business_id=business_id,
                purchase_order_id=order.id,
                received_by=user_id,
                idempotency_key=effective_idem,
                notes=notes,
            )
            db.add(receipt)
            db.flush()
            receipt.receipt_number = f"GR-{receipt.id:05d}"

            for order_item, qty_to_receive in requested_lines:
                remaining = order_item.ordered_quantity - order_item.received_quantity
                if qty_to_receive <= 0:
                    raise HTTPException(status_code=400, detail="Received quantity must be greater than 0")
                if qty_to_receive > remaining:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Only {remaining} units are remaining for item #{order_item.id}",
                    )

                # Concurrency-safe update preventing over-receipt
                upd = db.execute(
                    update(models.PurchaseOrderItem)
                    .where(
                        models.PurchaseOrderItem.id == order_item.id,
                        models.PurchaseOrderItem.purchase_order_id == order.id,
                        (models.PurchaseOrderItem.ordered_quantity - models.PurchaseOrderItem.received_quantity)
                        >= qty_to_receive,
                    )
                    .values(received_quantity=models.PurchaseOrderItem.received_quantity + qty_to_receive)
                )
                if upd.rowcount == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient remaining quantity on item #{order_item.id}",
                    )

                db.add(
                    models.GoodsReceiptItem(
                        goods_receipt_id=receipt.id,
                        purchase_order_item_id=order_item.id,
                        product_id=order_item.product_id,
                        quantity_received=qty_to_receive,
                    )
                )

                reason_str = (
                    "purchase_order_received"
                    if items_to_receive is None
                    else "purchase_order_partially_received"
                )
                stock_service.increase_stock(
                    db=db,
                    product_id=order_item.product_id,
                    quantity=qty_to_receive,
                    reason=reason_str,
                    reference_type="goods_receipt",
                    reference_id=receipt.id,
                    business_id=business_id,
                    user_id=user_id,
                    movement_type=stock_service.MovementType.PURCHASE_RECEIPT,
                )

            db.expire(order)
            refreshed_order = cls.get_purchase_order(db, business_id, order.id)
            all_received = all(
                itm.received_quantity == itm.ordered_quantity for itm in refreshed_order.items
            )
            if all_received:
                refreshed_order.status = models.PurchaseOrderStatus.RECEIVED
                refreshed_order.received_at = _utcnow()
            else:
                refreshed_order.status = models.PurchaseOrderStatus.PARTIALLY_RECEIVED

            db.commit()
            db.refresh(refreshed_order)
            logger.info(
                "GoodsReceipt recorded id=%s po_id=%s status=%s",
                receipt.id,
                refreshed_order.id,
                refreshed_order.status.value,
            )
            return refreshed_order
        except IntegrityError:
            db.rollback()
            if effective_idem:
                existing_receipt = (
                    db.query(models.GoodsReceipt)
                    .filter(
                        models.GoodsReceipt.business_id == business_id,
                        models.GoodsReceipt.idempotency_key == effective_idem,
                    )
                    .first()
                )
                if existing_receipt:
                    return cls.get_purchase_order(db, business_id, order_id)
            raise HTTPException(status_code=400, detail="Duplicate or conflicting goods receipt")
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Failed receiving goods po_id=%s", order_id)
            raise HTTPException(status_code=500, detail=f"Failed to receive goods: {exc}")

    @classmethod
    def list_receipts(cls, db: Session, business_id: int, order_id: int) -> List[models.GoodsReceipt]:
        cls.get_purchase_order(db, business_id, order_id)
        return (
            db.query(models.GoodsReceipt)
            .filter(
                models.GoodsReceipt.business_id == business_id,
                models.GoodsReceipt.purchase_order_id == order_id,
            )
            .order_by(models.GoodsReceipt.received_at.desc(), models.GoodsReceipt.id.desc())
            .all()
        )

    @classmethod
    def set_supplier_share(
        cls,
        db: Session,
        business_id: int,
        order_id: int,
        share: bool,
    ) -> models.PurchaseOrder:
        order = cls.get_purchase_order(db, business_id, order_id)
        if share:
            if order.status == models.PurchaseOrderStatus.CANCELLED:
                raise HTTPException(status_code=400, detail="Cannot share a cancelled purchase order.")
            supplier = (
                db.query(models.Supplier)
                .filter(models.Supplier.id == order.supplier_id, models.Supplier.business_id == business_id)
                .first()
            )
            if not supplier or not supplier.linked_business_id:
                raise HTTPException(
                    status_code=400,
                    detail="Link this supplier record to an active supplier workspace before sharing purchase orders.",
                )
            order.shared_with_supplier = True
            order.shared_at = order.shared_at or _utcnow()
            if not order.supplier_status:
                order.supplier_status = "PENDING_ACKNOWLEDGEMENT"
        else:
            order.shared_with_supplier = False
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def _serialize_supplier_portal_order(db: Session, po: models.PurchaseOrder, buyer: models.Business) -> dict:
        items = []
        prod_ids = [item.product_id for item in po.items]
        prod_map = {}
        if prod_ids:
            prods = db.query(models.Product).filter(models.Product.id.in_(prod_ids)).all()
            prod_map = {p.id: p for p in prods}
        for item in po.items:
            p = prod_map.get(item.product_id)
            items.append(
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "sku": p.sku if p else None,
                    "product_name": p.name if p else None,
                    "ordered_quantity": item.ordered_quantity,
                    "received_quantity": item.received_quantity,
                    "unit_cost": float(item.unit_cost),
                }
            )
        actions = (
            db.query(models.PurchaseOrderSupplierAction)
            .filter(models.PurchaseOrderSupplierAction.purchase_order_id == po.id)
            .order_by(models.PurchaseOrderSupplierAction.created_at.desc())
            .all()
        )
        return {
            "id": po.id,
            "order_number": po.order_number,
            "buyer_business_id": buyer.id,
            "buyer_business_name": buyer.name,
            "status": po.status.value if hasattr(po.status, "value") else str(po.status),
            "supplier_status": po.supplier_status,
            "supplier_notes": po.supplier_notes,
            "total_amount": float(po.total_amount or 0),
            "order_date": po.order_date,
            "expected_delivery_date": po.expected_delivery_date,
            "shared_at": po.shared_at,
            "supplier_acknowledged_at": po.supplier_acknowledged_at,
            "supplier_dispatched_at": po.supplier_dispatched_at,
            "items": items,
            "actions": actions,
        }

    @classmethod
    def list_supplier_portal_orders(cls, db: Session, supplier_business_id: int) -> List[dict]:
        rows = (
            db.query(models.PurchaseOrder, models.Business)
            .join(models.Supplier, models.Supplier.id == models.PurchaseOrder.supplier_id)
            .join(models.Business, models.Business.id == models.PurchaseOrder.business_id)
            .filter(
                models.Supplier.linked_business_id == supplier_business_id,
                models.PurchaseOrder.shared_with_supplier.is_(True),
            )
            .order_by(models.PurchaseOrder.order_date.desc(), models.PurchaseOrder.id.desc())
            .all()
        )
        return [cls._serialize_supplier_portal_order(db, po, buyer) for po, buyer in rows]

    @classmethod
    def get_supplier_portal_order(cls, db: Session, supplier_business_id: int, order_id: int) -> dict:
        row = (
            db.query(models.PurchaseOrder, models.Business)
            .join(models.Supplier, models.Supplier.id == models.PurchaseOrder.supplier_id)
            .join(models.Business, models.Business.id == models.PurchaseOrder.business_id)
            .filter(
                models.PurchaseOrder.id == order_id,
                models.Supplier.linked_business_id == supplier_business_id,
                models.PurchaseOrder.shared_with_supplier.is_(True),
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Shared purchase order not found")
        po, buyer = row
        return cls._serialize_supplier_portal_order(db, po, buyer)

    @classmethod
    def update_supplier_portal_status(
        cls,
        db: Session,
        supplier_business_id: int,
        user_id: int,
        order_id: int,
        new_status: str,
        notes: Optional[str] = None,
    ) -> dict:
        allowed = {"ACKNOWLEDGED", "DISPATCHED", "ISSUE_REPORTED"}
        norm = str(new_status or "").strip().upper()
        if norm not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"supplier_status must be one of: {', '.join(sorted(allowed))}",
            )

        row = (
            db.query(models.PurchaseOrder, models.Business)
            .join(models.Supplier, models.Supplier.id == models.PurchaseOrder.supplier_id)
            .join(models.Business, models.Business.id == models.PurchaseOrder.business_id)
            .filter(
                models.PurchaseOrder.id == order_id,
                models.Supplier.linked_business_id == supplier_business_id,
                models.PurchaseOrder.shared_with_supplier.is_(True),
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Shared purchase order not found")

        po, buyer = row
        if po.status in (models.PurchaseOrderStatus.RECEIVED, models.PurchaseOrderStatus.CANCELLED):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot update supplier status for {po.status.value} purchase order.",
            )

        po.supplier_status = norm
        if notes is not None:
            po.supplier_notes = notes.strip() or None
        now = _utcnow()
        if norm == "ACKNOWLEDGED":
            po.supplier_acknowledged_at = now
        elif norm == "DISPATCHED":
            po.supplier_dispatched_at = now

        db.add(
            models.PurchaseOrderSupplierAction(
                purchase_order_id=po.id,
                supplier_business_id=supplier_business_id,
                user_id=user_id,
                action=norm,
                notes=notes.strip() if notes else None,
            )
        )
        db.commit()
        db.refresh(po)
        return cls._serialize_supplier_portal_order(db, po, buyer)
