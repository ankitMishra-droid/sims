"""Persistent tenant-scoped stock alert dismissal, cooldown suppression, and read tracking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models.alerts import StockAlertState
from ..models.products import Product
from .inventory_service import InventoryService

_SEVERITY_RANK = {
    "LOW": 1,
    "MEDIUM": 2,
    "LOW_STOCK": 2,
    "HIGH": 3,
    "OUT_OF_STOCK": 4,
    "CRITICAL": 4,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StockAlertService:
    """Manages active/read/dismissed state transitions for tenant operational stock alerts."""

    @staticmethod
    def build_alert_key(alert_type: str, product_id: int) -> str:
        return f"{alert_type.strip().lower()}:{product_id}"

    @classmethod
    def list_alerts(
        cls,
        db: Session,
        business_id: int,
        *,
        include_dismissed: bool = False,
    ) -> Dict[str, Any]:
        now = _utcnow()
        low_products: List[Product] = InventoryService.get_low_stock_products(db, business_id)
        incoming_map = InventoryService.get_incoming_stock_map(
            db, business_id, [p.id for p in low_products]
        )

        states: Dict[str, StockAlertState] = {
            row.alert_key: row
            for row in db.query(StockAlertState)
            .filter(StockAlertState.business_id == business_id)
            .all()
        }

        active_alerts: List[Dict[str, Any]] = []
        dismissed_alerts: List[Dict[str, Any]] = []
        state_dirty = False

        for prod in low_products:
            severity = "OUT_OF_STOCK" if prod.current_stock == 0 else "LOW_STOCK"
            alert_type = "OUT_OF_STOCK" if prod.current_stock == 0 else "LOW_STOCK"
            alert_key = cls.build_alert_key("low_stock", prod.id)
            st = states.get(alert_key)

            if st and st.status == "DISMISSED":
                suppressed = st.dismissed_until is None or st.dismissed_until > now
                prev_rank = _SEVERITY_RANK.get((st.severity_snapshot or "").upper(), 0)
                curr_rank = _SEVERITY_RANK.get(severity, 0)
                stock_dropped = (
                    st.stock_snapshot is not None and prod.current_stock < st.stock_snapshot
                )
                escalated = curr_rank > prev_rank or stock_dropped
                if escalated or not suppressed:
                    st.status = "ACTIVE"
                    st.is_read = False
                    st.read_at = None
                    st.dismissed_until = None
                    state_dirty = True

            item = {
                "alert_key": alert_key,
                "alert_type": alert_type,
                "severity": severity,
                "product_id": prod.id,
                "sku": prod.sku,
                "name": prod.name,
                "unit": prod.unit,
                "supplier_id": prod.supplier_id,
                "current_stock": prod.current_stock,
                "incoming_stock": incoming_map.get(prod.id, 0),
                "reorder_level": prod.reorder_level,
                "status": st.status if st else "ACTIVE",
                "is_read": st.is_read if st else False,
                "read_at": st.read_at.isoformat() if st and st.read_at else None,
                "dismissed_at": st.dismissed_at.isoformat() if st and st.dismissed_at else None,
                "dismissed_until": st.dismissed_until.isoformat() if st and st.dismissed_until else None,
            }

            if st and st.status == "DISMISSED":
                dismissed_alerts.append(item)
            else:
                active_alerts.append(item)

        if state_dirty:
            db.commit()

        unread_count = sum(1 for a in active_alerts if not a["is_read"])
        visible = active_alerts + dismissed_alerts if include_dismissed else active_alerts
        return {
            "alerts": visible,
            "unread_count": unread_count,
            "active_count": len(active_alerts),
            "dismissed_count": len(dismissed_alerts),
        }

    @classmethod
    def mark_read(
        cls,
        db: Session,
        business_id: int,
        user_id: int,
        *,
        alert_key: Optional[str] = None,
        mark_all: bool = False,
        product_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = _utcnow()
        keys_to_mark: List[tuple[str, Optional[int], Optional[str], Optional[int]]] = []

        if mark_all:
            low_products = InventoryService.get_low_stock_products(db, business_id)
            for prod in low_products:
                sev = "OUT_OF_STOCK" if prod.current_stock == 0 else "LOW_STOCK"
                keys_to_mark.append(
                    (cls.build_alert_key("low_stock", prod.id), prod.id, sev, prod.current_stock)
                )
        elif alert_key:
            keys_to_mark.append((alert_key.strip(), product_id, None, None))
        elif product_id is not None:
            keys_to_mark.append((cls.build_alert_key("low_stock", product_id), product_id, None, None))

        updated = 0
        for key, pid, sev, stock in keys_to_mark:
            row = (
                db.query(StockAlertState)
                .filter(
                    StockAlertState.business_id == business_id,
                    StockAlertState.alert_key == key,
                )
                .first()
            )
            if not row:
                row = StockAlertState(
                    business_id=business_id,
                    alert_key=key,
                    alert_type="LOW_STOCK",
                    product_id=pid,
                    status="READ",
                    is_read=True,
                    read_at=now,
                    severity_snapshot=sev,
                    stock_snapshot=stock,
                    actioned_by_user_id=user_id,
                )
                db.add(row)
                updated += 1
            else:
                if row.status != "DISMISSED":
                    row.status = "READ"
                row.is_read = True
                row.read_at = now
                row.actioned_by_user_id = user_id
                updated += 1

        db.commit()
        return {"updated": updated, "is_read": True}

    @classmethod
    def dismiss_alert(
        cls,
        db: Session,
        business_id: int,
        user_id: int,
        *,
        alert_key: str,
        alert_type: str = "LOW_STOCK",
        product_id: Optional[int] = None,
        severity: Optional[str] = None,
        current_stock: Optional[int] = None,
        cooldown_days: int = 7,
        notes: Optional[str] = None,
    ) -> StockAlertState:
        now = _utcnow()
        clean_key = alert_key.strip()[:120]
        resolved_stock = current_stock
        resolved_sev = severity

        if product_id is not None and (resolved_stock is None or resolved_sev is None):
            prod = (
                db.query(Product)
                .filter(Product.id == product_id, Product.business_id == business_id)
                .first()
            )
            if prod:
                resolved_stock = prod.current_stock if resolved_stock is None else resolved_stock
                if resolved_sev is None:
                    resolved_sev = "OUT_OF_STOCK" if prod.current_stock == 0 else "LOW_STOCK"

        row = (
            db.query(StockAlertState)
            .filter(
                StockAlertState.business_id == business_id,
                StockAlertState.alert_key == clean_key,
            )
            .first()
        )
        until = now + timedelta(days=max(1, min(cooldown_days, 90)))
        if not row:
            row = StockAlertState(
                business_id=business_id,
                alert_key=clean_key,
                alert_type=alert_type.strip().upper()[:32] or "LOW_STOCK",
                product_id=product_id,
                status="DISMISSED",
                is_read=True,
                read_at=now,
                dismissed_at=now,
                dismissed_until=until,
                severity_snapshot=resolved_sev,
                stock_snapshot=resolved_stock,
                actioned_by_user_id=user_id,
                notes=(notes or "").strip()[:500] or None,
            )
            db.add(row)
        else:
            row.status = "DISMISSED"
            row.is_read = True
            row.read_at = row.read_at or now
            row.dismissed_at = now
            row.dismissed_until = until
            row.severity_snapshot = resolved_sev or row.severity_snapshot
            row.stock_snapshot = resolved_stock if resolved_stock is not None else row.stock_snapshot
            row.actioned_by_user_id = user_id
            if notes is not None:
                row.notes = notes.strip()[:500] or None

        db.commit()
        db.refresh(row)
        return row

    @classmethod
    def reopen_alert(cls, db: Session, business_id: int, *, alert_key: str) -> Dict[str, Any]:
        row = (
            db.query(StockAlertState)
            .filter(
                StockAlertState.business_id == business_id,
                StockAlertState.alert_key == alert_key.strip(),
            )
            .first()
        )
        if row:
            row.status = "ACTIVE"
            row.dismissed_until = None
            row.is_read = False
            row.read_at = None
            db.commit()
        return {"alert_key": alert_key, "status": "ACTIVE"}
