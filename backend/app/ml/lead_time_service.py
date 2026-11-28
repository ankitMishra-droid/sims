from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session

from ..models.purchase_order import GoodsReceipt, PurchaseOrder, PurchaseOrderStatus
from ..models.supplier import Supplier


class SupplierLeadTimeService:
    """
    Computes empirical supplier lead-time mean, variability (sigma_L),
    on-time/late delivery performance, and partial-delivery signals from
    actual PurchaseOrder & GoodsReceipt history within a single business workspace.
    """

    DEFAULT_LEAD_TIME_DAYS = 7.0

    @classmethod
    def get_supplier_lead_time_stats(
        cls,
        db: Session,
        business_id: int,
        supplier_id: Optional[int],
    ) -> Dict[str, Any]:
        if not supplier_id:
            return {
                "supplier_id": None,
                "supplier_name": "Unassigned",
                "configured_lead_time_days": int(cls.DEFAULT_LEAD_TIME_DAYS),
                "effective_lead_time_days": cls.DEFAULT_LEAD_TIME_DAYS,
                "lead_time_std_days": round(cls.DEFAULT_LEAD_TIME_DAYS * 0.20, 2),
                "lead_time_source": "system_default",
                "sample_count": 0,
                "partial_po_count": 0,
                "open_po_count": 0,
                "late_delivery_count": 0,
                "on_time_delivery_rate": None,
                "late_delivery_rate": None,
                "delay_risk": "UNKNOWN",
            }

        supplier = (
            db.query(Supplier)
            .filter(Supplier.id == supplier_id, Supplier.business_id == business_id)
            .first()
        )
        if not supplier:
            return {
                "supplier_id": supplier_id,
                "supplier_name": "Unknown Supplier",
                "configured_lead_time_days": int(cls.DEFAULT_LEAD_TIME_DAYS),
                "effective_lead_time_days": cls.DEFAULT_LEAD_TIME_DAYS,
                "lead_time_std_days": round(cls.DEFAULT_LEAD_TIME_DAYS * 0.20, 2),
                "lead_time_source": "system_default",
                "sample_count": 0,
                "partial_po_count": 0,
                "open_po_count": 0,
                "late_delivery_count": 0,
                "on_time_delivery_rate": None,
                "late_delivery_rate": None,
                "delay_risk": "UNKNOWN",
            }

        configured = float(supplier.lead_time_days or cls.DEFAULT_LEAD_TIME_DAYS)

        pos = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.business_id == business_id,
                PurchaseOrder.supplier_id == supplier_id,
                PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
            )
            .order_by(PurchaseOrder.order_date.asc())
            .all()
        )
        po_ids = [po.id for po in pos]
        receipts_by_po: Dict[int, List[GoodsReceipt]] = {}
        if po_ids:
            receipts = (
                db.query(GoodsReceipt)
                .filter(
                    GoodsReceipt.business_id == business_id,
                    GoodsReceipt.purchase_order_id.in_(po_ids),
                )
                .order_by(GoodsReceipt.received_at.asc())
                .all()
            )
            for r in receipts:
                receipts_by_po.setdefault(r.purchase_order_id, []).append(r)

        completed_lead_days: List[float] = []
        partial_first_days: List[float] = []
        expected_checked = 0
        late_count = 0
        partial_po_count = 0
        open_po_count = 0

        for po in pos:
            if po.status in (PurchaseOrderStatus.SENT, PurchaseOrderStatus.PARTIALLY_RECEIVED):
                open_po_count += 1
            if po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED:
                partial_po_count += 1

            start_ts = po.sent_at or po.order_date
            if not start_ts:
                continue

            po_receipts = receipts_by_po.get(po.id, [])
            if po.status == PurchaseOrderStatus.RECEIVED:
                end_ts = po.received_at or (po_receipts[-1].received_at if po_receipts else None)
                if end_ts and end_ts >= start_ts:
                    lead_days = max(0.0, (end_ts - start_ts).total_seconds() / 86400.0)
                    completed_lead_days.append(lead_days)
                    if po.expected_delivery_date:
                        expected_checked += 1
                        if end_ts.date() > po.expected_delivery_date.date():
                            late_count += 1
            elif po_receipts:
                first_ts = po_receipts[0].received_at
                if first_ts and first_ts >= start_ts:
                    partial_first_days.append(max(0.0, (first_ts - start_ts).total_seconds() / 86400.0))

        # Only override manual supplier lead_time_days when meaningful multi-hour/multi-day empirical receipts exist
        meaningful_completed = [d for d in completed_lead_days if d >= 0.25]
        sample_count = len(meaningful_completed)

        if sample_count >= 2:
            effective = float(np.mean(meaningful_completed))
            std_days = float(np.std(meaningful_completed, ddof=1))
            source = "po_receipt_history"
        elif sample_count == 1:
            effective = float(meaningful_completed[0])
            std_days = max(0.5, round(effective * 0.15, 2))
            source = "single_po_receipt"
        elif len(partial_first_days) >= 1 and any(d >= 0.25 for d in partial_first_days):
            valid_partial = [d for d in partial_first_days if d >= 0.25]
            effective = float(np.mean(valid_partial))
            std_days = float(np.std(valid_partial, ddof=1)) if len(valid_partial) >= 2 else max(0.5, round(effective * 0.20, 2))
            source = "partial_receipt_history"
            sample_count = len(valid_partial)
        else:
            effective = configured
            std_days = max(0.5, round(configured * 0.20, 2))
            source = "supplier_default"

        on_time_rate = (
            round((expected_checked - late_count) / expected_checked, 4)
            if expected_checked > 0
            else None
        )
        late_rate = (
            round(late_count / expected_checked, 4)
            if expected_checked > 0
            else None
        )

        delay_risk = "LOW"
        if late_rate is not None and expected_checked >= 2 and late_rate >= 0.30:
            delay_risk = "HIGH"
        elif sample_count >= 2 and effective > configured * 1.25:
            delay_risk = "ELEVATED"
        elif sample_count == 0:
            delay_risk = "ESTIMATED"

        return {
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "configured_lead_time_days": int(supplier.lead_time_days or cls.DEFAULT_LEAD_TIME_DAYS),
            "effective_lead_time_days": round(effective, 2),
            "lead_time_std_days": round(max(0.0, std_days), 2),
            "lead_time_source": source,
            "sample_count": sample_count,
            "completed_po_count": len(completed_lead_days),
            "partial_po_count": partial_po_count,
            "open_po_count": open_po_count,
            "expected_checked_count": expected_checked,
            "late_delivery_count": late_count,
            "on_time_delivery_rate": on_time_rate,
            "late_delivery_rate": late_rate,
            "delay_risk": delay_risk,
        }

    @classmethod
    def get_all_suppliers_lead_time_report(
        cls,
        db: Session,
        business_id: int,
    ) -> List[Dict[str, Any]]:
        suppliers = (
            db.query(Supplier)
            .filter(Supplier.business_id == business_id, Supplier.is_active.is_(True))
            .order_by(Supplier.name.asc())
            .all()
        )
        return [
            cls.get_supplier_lead_time_stats(db, business_id, s.id)
            for s in suppliers
        ]
