from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..models.business import Business, BusinessOnboardingProgress
from ..models.inventory import InventoryLog
from ..models.products import Product
from ..models.supplier import Supplier
from . import stock_service
from .auth import normalize_language_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


RETAILER_STEPS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
SUPPLIER_STEPS = [1, 2, 3, 4, 5, 9, 10]
OPTIONAL_STEPS = {6, 7, 8, 9}


def applicable_steps_for_type(business_type: str) -> List[int]:
    if (business_type or "").lower() == "supplier":
        return list(SUPPLIER_STEPS)
    return list(RETAILER_STEPS)


def _load_json_list(raw: Optional[str]) -> List[int]:
    try:
        val = json.loads(raw or "[]")
        return [int(x) for x in val] if isinstance(val, list) else []
    except Exception:
        return []


def _load_json_dict(raw: Optional[str]) -> Dict[str, Any]:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


class OnboardingService:
    @staticmethod
    def _serialize(progress: BusinessOnboardingProgress, business: Business) -> dict:
        return {
            "business_id": business.id,
            "business_type": business.business_type,
            "current_step": progress.current_step,
            "completed_steps": _load_json_list(progress.completed_steps_json),
            "skipped_steps": _load_json_list(progress.skipped_steps_json),
            "step_data": _load_json_dict(progress.step_data_json),
            "is_completed": progress.is_completed or business.onboarding_completed,
            "applicable_steps": applicable_steps_for_type(business.business_type),
        }

    @classmethod
    def get_progress(cls, db: Session, business: Business, user_id: int) -> dict:
        progress = (
            db.query(BusinessOnboardingProgress)
            .filter(BusinessOnboardingProgress.business_id == business.id)
            .first()
        )
        if not progress:
            progress = BusinessOnboardingProgress(
                business_id=business.id,
                user_id=user_id,
                current_step=10 if business.onboarding_completed else 1,
                completed_steps_json=json.dumps(
                    applicable_steps_for_type(business.business_type) if business.onboarding_completed else []
                ),
                skipped_steps_json="[]",
                step_data_json="{}",
                is_completed=business.onboarding_completed,
            )
            db.add(progress)
            db.commit()
            db.refresh(progress)
        return cls._serialize(progress, business)

    @classmethod
    def save_step(
        cls,
        db: Session,
        business: Business,
        user: models.User,
        req: schemas.OnboardingStepSaveRequest,
    ) -> dict:
        progress = (
            db.query(BusinessOnboardingProgress)
            .filter(BusinessOnboardingProgress.business_id == business.id)
            .first()
        )
        if not progress:
            progress = BusinessOnboardingProgress(
                business_id=business.id,
                user_id=user.id,
                current_step=1,
                completed_steps_json="[]",
                skipped_steps_json="[]",
                step_data_json="{}",
                is_completed=False,
            )
            db.add(progress)
            db.flush()

        completed = set(_load_json_list(progress.completed_steps_json))
        skipped = set(_load_json_list(progress.skipped_steps_json))
        step_data = _load_json_dict(progress.step_data_json)
        action = (req.action or "complete").strip().lower()
        step = req.step

        steps = applicable_steps_for_type(business.business_type)

        if action == "back":
            if step in steps:
                idx = steps.index(step)
                progress.current_step = steps[max(0, idx - 1)]
            else:
                progress.current_step = max(1, step - 1)
            db.commit()
            db.refresh(progress)
            return cls._serialize(progress, business)

        if action == "skip":
            if step not in OPTIONAL_STEPS:
                raise HTTPException(status_code=400, detail=f"Step {step} is required and cannot be skipped.")
            skipped.add(step)
            completed.discard(step)
        else:
            # action == "complete"
            skipped.discard(step)
            payload = req.data or {}
            if step == 2:
                btype = str(payload.get("business_type", "")).strip().lower()
                if btype not in {"retailer", "wholesaler", "supplier"}:
                    raise HTTPException(status_code=400, detail="Select retailer, wholesaler, or supplier.")
                current_btype = (business.business_type or "").strip().lower()
                if btype != current_btype and ("supplier" in {btype, current_btype}):
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot switch between buyer and supplier workspace types.",
                    )
                business.business_type = btype
                steps = applicable_steps_for_type(btype)
                step_data["business_type"] = btype

            elif step == 3:
                lang = normalize_language_code(payload.get("language"))
                user.preferred_language = lang
                business.default_language = lang
                step_data["language"] = lang

            elif step == 4:
                biz_name = str(payload.get("name", business.name or "")).strip()
                if len(biz_name) < 2:
                    raise HTTPException(status_code=400, detail="Business name must be at least 2 characters.")
                business.name = biz_name
                if "contact_email" in payload:
                    business.contact_email = str(payload["contact_email"]).strip() or None
                if "contact_phone" in payload:
                    business.contact_phone = str(payload["contact_phone"]).strip() or None
                if "address" in payload:
                    business.address = str(payload["address"]).strip() or None
                if "gstin_or_tax_id" in payload:
                    business.gstin_or_tax_id = str(payload["gstin_or_tax_id"]).strip() or None
                step_data["profile"] = {
                    "name": business.name,
                    "contact_email": business.contact_email,
                    "contact_phone": business.contact_phone,
                    "address": business.address,
                }

            elif step == 5:
                currency = str(payload.get("currency", business.currency or "INR")).strip().upper()
                thresh = int(payload.get("low_stock_threshold_default", business.low_stock_threshold_default or 10))
                if thresh < 0:
                    raise HTTPException(status_code=400, detail="Low stock threshold must be non-negative.")
                business.currency = currency or "INR"
                business.low_stock_threshold_default = thresh
                if "allow_negative_stock" in payload:
                    business.allow_negative_stock = bool(payload["allow_negative_stock"])
                step_data["preferences"] = {
                    "currency": business.currency,
                    "low_stock_threshold_default": business.low_stock_threshold_default,
                    "allow_negative_stock": business.allow_negative_stock,
                }

            elif step == 6 and business.business_type != "supplier":
                items = payload.get("products") or []
                created_skus = []
                skipped_skus = []
                for item in items:
                    sku = str(item.get("sku", "")).strip()
                    name = str(item.get("name", "")).strip()
                    if not sku or not name:
                        raise HTTPException(status_code=400, detail="Each product requires SKU and name.")
                    existing = (
                        db.query(Product)
                        .filter(Product.business_id == business.id, Product.sku == sku)
                        .first()
                    )
                    if existing:
                        skipped_skus.append(sku)
                        continue
                    cost_price = float(item.get("cost_price", 0) or 0)
                    selling_price = float(item.get("selling_price", 0) or 0)
                    reorder_level = int(item.get("reorder_level", business.low_stock_threshold_default or 10))
                    if cost_price < 0 or selling_price < 0 or reorder_level < 0:
                        raise HTTPException(status_code=400, detail="Product prices and reorder level must be >= 0.")
                    prod = Product(
                        business_id=business.id,
                        sku=sku,
                        name=name,
                        category=str(item.get("category") or "General").strip() or "General",
                        unit=str(item.get("unit") or "piece").strip() or "piece",
                        cost_price=cost_price,
                        selling_price=selling_price,
                        current_stock=0,
                        reorder_level=reorder_level,
                        is_active=True,
                    )
                    db.add(prod)
                    created_skus.append(sku)
                step_data["products_summary"] = {
                    "created_skus": created_skus,
                    "skipped_duplicate_skus": skipped_skus,
                }

            elif step == 7 and business.business_type != "supplier":
                sup_items = payload.get("suppliers") or []
                created_names = []
                skipped_names = []
                for s in sup_items:
                    sname = str(s.get("name", "")).strip()
                    if not sname:
                        raise HTTPException(status_code=400, detail="Supplier name is required.")
                    existing = (
                        db.query(Supplier)
                        .filter(Supplier.business_id == business.id, Supplier.name == sname)
                        .first()
                    )
                    if existing:
                        skipped_names.append(sname)
                        continue
                    supp = Supplier(
                        business_id=business.id,
                        name=sname,
                        contact_person=str(s.get("contact_person") or "").strip() or None,
                        email=str(s.get("email") or "").strip() or None,
                        phone=str(s.get("phone") or "").strip() or None,
                        lead_time_days=max(0, int(s.get("lead_time_days", 7) or 7)),
                        is_active=True,
                    )
                    db.add(supp)
                    created_names.append(sname)
                step_data["suppliers_summary"] = {
                    "created": created_names,
                    "skipped_duplicates": skipped_names,
                }

            elif step == 8 and business.business_type != "supplier":
                entries = payload.get("opening_stocks") or []
                applied = []
                skipped_entries = []
                for entry in entries:
                    qty = int(entry.get("quantity", 0) or 0)
                    if qty <= 0:
                        continue
                    prod = None
                    if entry.get("product_id"):
                        prod = (
                            db.query(Product)
                            .filter(Product.id == int(entry["product_id"]), Product.business_id == business.id)
                            .first()
                        )
                    elif entry.get("sku"):
                        prod = (
                            db.query(Product)
                            .filter(Product.sku == str(entry["sku"]).strip(), Product.business_id == business.id)
                            .first()
                        )
                    if not prod:
                        raise HTTPException(status_code=404, detail="Product for opening stock not found in workspace.")

                    already = (
                        db.query(InventoryLog.id)
                        .filter(
                            InventoryLog.business_id == business.id,
                            InventoryLog.product_id == prod.id,
                            InventoryLog.movement_type == "OPENING_STOCK",
                        )
                        .first()
                    )
                    if already:
                        skipped_entries.append(prod.sku)
                        continue

                    stock_service.apply_stock_movement(
                        db,
                        product_id=prod.id,
                        business_id=business.id,
                        delta=qty,
                        movement_type="OPENING_STOCK",
                        reason="onboarding_opening_stock",
                        reference_type="onboarding",
                        reference_id=progress.id,
                        user_id=user.id,
                    )
                    applied.append({"sku": prod.sku, "quantity": qty})
                step_data["opening_stock_summary"] = {
                    "applied": applied,
                    "skipped_already_initialized": skipped_entries,
                }

            completed.add(step)

        if step == 10 and action == "complete":
            progress.is_completed = True
            progress.completed_at = _utcnow()
            business.onboarding_completed = True
            progress.current_step = 10
        else:
            if step in steps:
                idx = steps.index(step)
                progress.current_step = steps[min(len(steps) - 1, idx + 1)]
            else:
                progress.current_step = min(10, step + 1)

        progress.completed_steps_json = json.dumps(sorted(completed))
        progress.skipped_steps_json = json.dumps(sorted(skipped))
        progress.step_data_json = json.dumps(step_data)
        progress.user_id = user.id

        db.commit()
        db.refresh(progress)
        db.refresh(business)
        return cls._serialize(progress, business)
