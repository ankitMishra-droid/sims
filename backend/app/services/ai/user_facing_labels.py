"""Centralized translation layer mapping internal SIMS enums/statuses to natural user-facing copy."""

from __future__ import annotations

import re
from typing import Optional

PRIORITY_LABELS = {
    "CRITICAL": "Critical priority",
    "HIGH": "High priority",
    "MEDIUM": "Medium priority",
    "LOW": "Low priority",
    "INFO": "Informational",
}

PRIORITY_SHORT_LABELS = {
    "CRITICAL": "Critical",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
    "INFO": "Info",
}

RECOMMENDATION_LABELS = {
    "REORDER_NOW": "Reorder now",
    "LOW_STOCK_RISK": "Running low",
    "OVERSTOCK_ALERT": "Overstock",
    "COLD_START_REVIEW": "New or limited sales history",
    "DEMAND_INCREASING": "Rising demand",
    "DEMAND_DECREASING": "Declining demand",
    "SUPPLIER_LEAD_TIME_RISK": "Supplier delivery delay risk",
    "HEALTHY": "Healthy stock",
}

STOCK_STATUS_LABELS = {
    "OUT_OF_STOCK": "Out of stock",
    "CRITICAL": "Critical priority",
    "HIGH": "High priority",
    "LOW_STOCK": "Running low",
    "IN_STOCK": "In stock",
    "OPTIMAL": "Healthy stock",
    "HEALTHY": "Healthy stock",
    "OVERSTOCK": "Overstock",
    "INSUFFICIENT_DATA": "Not enough data available",
}

PO_STATUS_LABELS = {
    "DRAFT": "Draft",
    "SENT": "Sent to supplier",
    "ACKNOWLEDGED": "Acknowledged by supplier",
    "IN_TRANSIT": "In transit",
    "PARTIALLY_RECEIVED": "Partially received",
    "RECEIVED": "Received",
    "CANCELLED": "Cancelled",
    "PENDING_CONFIRMATION": "Awaiting your confirmation",
    "EXECUTED": "Completed",
}

MOVEMENT_TYPE_LABELS = {
    "OPENING_STOCK": "Opening stock",
    "PURCHASE_RECEIPT": "Purchase receipt",
    "SALE": "Sale",
    "STOCK_ADJUSTMENT": "Stock adjustment",
    "RETURN": "Customer/supplier return",
    "REVERSAL": "Adjustment reversal",
}

# Ordered exact internal enum token replacements for response text validation/sanitization
INTERNAL_ENUM_REPLACEMENTS = (
    ("REORDER_NOW", "Reorder now"),
    ("LOW_STOCK_RISK", "Running low"),
    ("OUT_OF_STOCK", "Out of stock"),
    ("LOW_STOCK", "Running low"),
    ("INSUFFICIENT_DATA", "Not enough data available"),
    ("COLD_START_REVIEW", "New or limited sales history"),
    ("OVERSTOCK_ALERT", "Overstock"),
    ("SUPPLIER_LEAD_TIME_RISK", "Supplier delivery risk"),
    ("DEMAND_INCREASING", "Rising demand"),
    ("DEMAND_DECREASING", "Declining demand"),
    ("PARTIALLY_RECEIVED", "Partially received"),
    ("PURCHASE_RECEIPT", "Purchase receipt"),
    ("STOCK_ADJUSTMENT", "Stock adjustment"),
    ("OPENING_STOCK", "Opening stock"),
    ("PENDING_CONFIRMATION", "Pending confirmation"),
)


def humanize_priority(value: Optional[str], *, short: bool = False) -> str:
    key = str(value or "").strip().upper()
    mapping = PRIORITY_SHORT_LABELS if short else PRIORITY_LABELS
    if key in mapping:
        return mapping[key]
    return key.replace("_", " ").title() if key else "Not rated"


def humanize_recommendation_type(value: Optional[str]) -> str:
    key = str(value or "").strip().upper()
    if key in RECOMMENDATION_LABELS:
        return RECOMMENDATION_LABELS[key]
    return key.replace("_", " ").capitalize() if key else "Review needed"


def humanize_stock_status(value: Optional[str]) -> str:
    key = str(value or "").strip().upper()
    if key in STOCK_STATUS_LABELS:
        return STOCK_STATUS_LABELS[key]
    return key.replace("_", " ").capitalize() if key else "Unknown"


def humanize_po_status(value: Optional[str]) -> str:
    key = str(value or "").strip().upper()
    if key in PO_STATUS_LABELS:
        return PO_STATUS_LABELS[key]
    return key.replace("_", " ").capitalize() if key else "Unknown"


def humanize_movement_type(value: Optional[str]) -> str:
    key = str(value or "").strip().upper()
    if key in MOVEMENT_TYPE_LABELS:
        return MOVEMENT_TYPE_LABELS[key]
    return key.replace("_", " ").capitalize() if key else "Adjustment"


def humanize_internal_text(text: str) -> str:
    """Replace internal abbreviations/enum tokens inside analytical summaries with natural language."""
    if not text:
        return ""
    cleaned = text
    for raw_enum, friendly in INTERNAL_ENUM_REPLACEMENTS:
        cleaned = re.sub(rf"\b{re.escape(raw_enum)}\b", friendly, cleaned)
    cleaned = re.sub(r"\bROP\b", "reorder point", cleaned)
    cleaned = re.sub(r"\bMOQ\b", "minimum order quantity", cleaned)
    cleaned = re.sub(r"\bSL\b", "service level", cleaned)
    cleaned = re.sub(r"\bPOs\b", "purchase orders", cleaned)
    cleaned = re.sub(r"\bPO\b", "purchase order", cleaned)
    return cleaned.strip()
