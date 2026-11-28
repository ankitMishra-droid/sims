"""
Deterministic, Idempotent Historical Business Dataset Seeder (Development / Demo Only).

Generates realistic 0-5+ year historical supply-chain timelines across multiple demand
regimes (stable, seasonal 4Y, growing 2.5Y, declining 2Y, intermittent 3Y, promo/spikes 5Y
with a realistic stockout window, limited 20D, and cold-start 0D) with coherent:
    PurchaseOrder -> PurchaseOrderItem -> GoodsReceipt -> GoodsReceiptItem
    -> InventoryLog -> Sale

Safety invariants:
1. Refuses execution outside development/demo environments unless overridden cleanly in tests
   using explicit isolated sessions with allowed env flags.
2. Never truncates tables or modifies genuine non-synthetic records (is_synthetic == False).
3. Idempotent via natural unique keys (sku, order_number, receipt_number, idempotency_key).
4. Chronologically sound: stock receipts always precede or balance daily sales (never < 0 stock).
5. Explicitly tags every generated Product, PurchaseOrder, GoodsReceipt, InventoryLog, and Sale
   with is_synthetic=True.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import math
import os
from pathlib import Path
import random
import sys
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.business import Business
from app.models.inventory import InventoryLog
from app.models.products import Product
from app.models.purchase_order import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)
from app.models.sales import Sale
from app.models.supplier import Supplier

logger = logging.getLogger("sims.ml.historical_seeder")

ALLOWED_SEED_ENVS = {"development", "dev", "local", "demo"}
ELIGIBLE_WORKSPACE_TYPES = ("retailer", "wholesaler")


def resolve_target_business_ids(db: Session) -> List[int]:
    """Return all active non-supplier (retailer/wholesaler) workspace IDs so every user's workspace gets seeded."""
    rows = (
        db.query(Business.id)
        .filter(func.lower(func.coalesce(Business.business_type, "retailer")).in_(ELIGIBLE_WORKSPACE_TYPES))
        .order_by(Business.id.asc())
        .all()
    )
    return [r[0] for r in rows]


def verify_seed_environment() -> str:
    """Block accidental execution in production or hosted staging environments."""
    app_env = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("SIMS_ENV")
        or "development"
    ).strip().lower()
    is_render = os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes"}
    if app_env not in ALLOWED_SEED_ENVS:
        raise RuntimeError(
            f"Refusing historical demo seeding in APP_ENV='{app_env}'. "
            f"Allowed environments: {sorted(ALLOWED_SEED_ENVS)}."
        )
    if is_render and app_env != "demo":
        raise RuntimeError(
            "Refusing historical demo seeding on hosted Render runtime unless APP_ENV='demo'."
        )
    return app_env


@dataclass
class ScenarioSpec:
    suffix: str
    retail_name: str
    wholesale_name: str
    category: str
    unit_retail: str
    unit_wholesale: str
    cost_price: float
    selling_price: float
    history_days: int
    pattern: str  # stable | seasonal | growing | declining | intermittent | spikes | limited | cold_start
    base_demand: float
    reorder_level: int
    pack_size: int = 1
    moq: int = 1


SCENARIO_CATALOG: List[ScenarioSpec] = [
    ScenarioSpec(
        suffix="STA-180",
        retail_name="Basmati Classic 5kg (Demo Stable 6M)",
        wholesale_name="Basmati Classic 25kg Sack (Demo Stable 6M)",
        category="Grains & Staples",
        unit_retail="pack",
        unit_wholesale="sack",
        cost_price=240.0,
        selling_price=310.0,
        history_days=180,
        pattern="stable",
        base_demand=9.0,
        reorder_level=35,
        pack_size=5,
        moq=10,
    ),
    ScenarioSpec(
        suffix="SEA-4Y",
        retail_name="Festive Dry Fruit Box (Demo Seasonal 4Y)",
        wholesale_name="Festive Dry Fruit Master Case (Demo Seasonal 4Y)",
        category="Festive & Snacks",
        unit_retail="box",
        unit_wholesale="case",
        cost_price=320.0,
        selling_price=450.0,
        history_days=1460,
        pattern="seasonal",
        base_demand=6.5,
        reorder_level=40,
        pack_size=4,
        moq=12,
    ),
    ScenarioSpec(
        suffix="GRO-2Y",
        retail_name="Cold-Pressed Mustard Oil 1L (Demo Growing 2.5Y)",
        wholesale_name="Mustard Oil 15L Tin (Demo Growing 2.5Y)",
        category="Edible Oils",
        unit_retail="bottle",
        unit_wholesale="tin",
        cost_price=145.0,
        selling_price=195.0,
        history_days=910,
        pattern="growing",
        base_demand=4.5,
        reorder_level=30,
        pack_size=6,
        moq=12,
    ),
    ScenarioSpec(
        suffix="DEC-2Y",
        retail_name="Standard Tungsten Lamp 60W (Demo Declining 2Y)",
        wholesale_name="Tungsten Lamp 60W Carton (Demo Declining 2Y)",
        category="Home Electrical",
        unit_retail="pack",
        unit_wholesale="carton",
        cost_price=65.0,
        selling_price=95.0,
        history_days=730,
        pattern="declining",
        base_demand=7.5,
        reorder_level=15,
        pack_size=5,
        moq=5,
    ),
    ScenarioSpec(
        suffix="INT-3Y",
        retail_name="Commercial Mixer Blade Set (Demo Intermittent 3Y)",
        wholesale_name="Commercial Mixer Motor Kit (Demo Intermittent 3Y)",
        category="Appliances",
        unit_retail="set",
        unit_wholesale="kit",
        cost_price=410.0,
        selling_price=580.0,
        history_days=1095,
        pattern="intermittent",
        base_demand=3.2,
        reorder_level=12,
        pack_size=2,
        moq=4,
    ),
    ScenarioSpec(
        suffix="SPK-5Y",
        retail_name="Copper Beverage Dispenser (Demo Spikes 5Y)",
        wholesale_name="Stainless Catering Urn 20L (Demo Spikes 5Y)",
        category="Beverageware",
        unit_retail="piece",
        unit_wholesale="piece",
        cost_price=620.0,
        selling_price=890.0,
        history_days=1825,
        pattern="spikes",
        base_demand=4.2,
        reorder_level=28,
        pack_size=2,
        moq=6,
    ),
    ScenarioSpec(
        suffix="LNG-7Y",
        retail_name="Royal Whole Black Peppercorn (Demo 7Y Horizon)",
        wholesale_name="Whole Black Peppercorn 25kg Bag (Demo 7Y Horizon)",
        category="Spices & Condiments",
        unit_retail="pack",
        unit_wholesale="bag",
        cost_price=290.0,
        selling_price=395.0,
        history_days=2550,
        pattern="long_horizon",
        base_demand=6.0,
        reorder_level=30,
        pack_size=5,
        moq=10,
    ),
    ScenarioSpec(
        suffix="HIS-10Y",
        retail_name="Cardamom Whole Green 1kg (Demo 10Y Horizon)",
        wholesale_name="Green Cardamom 10kg Crate (Demo 10Y Horizon)",
        category="Spices & Condiments",
        unit_retail="pack",
        unit_wholesale="crate",
        cost_price=520.0,
        selling_price=690.0,
        history_days=3650,
        pattern="long_horizon",
        base_demand=5.2,
        reorder_level=28,
        pack_size=4,
        moq=8,
    ),
    ScenarioSpec(
        suffix="LIM-20D",
        retail_name="Roasted Seed Mix 200g (Demo Limited 20D)",
        wholesale_name="Roasted Seed Mix Case (Demo Limited 20D)",
        category="Festive & Snacks",
        unit_retail="pouch",
        unit_wholesale="case",
        cost_price=95.0,
        selling_price=140.0,
        history_days=20,
        pattern="limited",
        base_demand=3.5,
        reorder_level=15,
        pack_size=5,
        moq=10,
    ),
    ScenarioSpec(
        suffix="NEW-0D",
        retail_name="Artisan Brass Kettle (Demo New Cold-Start)",
        wholesale_name="Brass Service Kettle Lot (Demo New Cold-Start)",
        category="Beverageware",
        unit_retail="piece",
        unit_wholesale="lot",
        cost_price=780.0,
        selling_price=1120.0,
        history_days=0,
        pattern="cold_start",
        base_demand=0.0,
        reorder_level=10,
        pack_size=1,
        moq=2,
    ),
]


@dataclass
class SeedingReport:
    env: str
    seed: int
    workspaces_processed: List[Dict[str, Any]] = field(default_factory=list)
    workspaces_skipped: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, Dict[str, int]] = field(
        default_factory=lambda: {
            "Products": {"inserted": 0, "skipped": 0, "failed": 0},
            "Suppliers": {"inserted": 0, "skipped": 0, "failed": 0},
            "PurchaseOrders": {"inserted": 0, "skipped": 0, "failed": 0},
            "GoodsReceipts": {"inserted": 0, "skipped": 0, "failed": 0},
            "InventoryLogs": {"inserted": 0, "skipped": 0, "failed": 0},
            "Sales": {"inserted": 0, "skipped": 0, "failed": 0},
        }
    )

    def inc(self, entity: str, bucket: str, n: int = 1) -> None:
        self.counts[entity][bucket] += n

    def as_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.env,
            "seed": self.seed,
            "workspaces_processed": self.workspaces_processed,
            "workspaces_skipped": self.workspaces_skipped,
            "summary": self.counts,
        }


def _simulate_daily_demand_and_price(
    spec: ScenarioSpec,
    day_idx: int,
    total_days: int,
    cur_date: datetime,
    is_wholesale: bool,
    rng: random.Random,
) -> tuple[int, float]:
    """Deterministically generate non-negative realistic daily demand and unit price."""
    scale = 1.6 if is_wholesale else 1.0
    dow = cur_date.weekday()
    month = cur_date.month
    dow_factor = 1.22 if dow in (4, 5) else (0.86 if dow == 6 else 1.0)
    base_price = spec.selling_price * (2.2 if is_wholesale else 1.0)

    if spec.pattern == "cold_start":
        return 0, base_price

    if spec.pattern == "limited":
        # Sparse 20-day launch period
        if rng.random() < 0.35:
            return 0, base_price
        mu = spec.base_demand * scale * dow_factor
        return max(1, round(rng.gauss(mu, 1.2))), base_price

    if spec.pattern == "stable":
        mu = spec.base_demand * scale * dow_factor
        return max(0, round(rng.gauss(mu, max(1.0, mu * 0.22)))), base_price

    if spec.pattern == "seasonal":
        annual_wave = 1.0 + 0.38 * math.sin(2.0 * math.pi * (day_idx / 365.25 - 0.15))
        festive = 1.65 if (month == 10 and cur_date.day >= 12) or (month == 11 and cur_date.day <= 18) else 1.0
        if month == 12 and cur_date.day >= 20:
            festive = 1.4
        mu = spec.base_demand * scale * dow_factor * annual_wave * festive
        price = round(base_price * (0.92 if festive > 1.2 else 1.0), 2)
        return max(0, round(rng.gauss(mu, max(1.1, mu * 0.2)))), price

    if spec.pattern == "growing":
        progress = day_idx / max(total_days - 1, 1)
        growth = 0.65 + 1.15 * progress
        mu = spec.base_demand * scale * dow_factor * growth
        return max(0, round(rng.gauss(mu, max(0.9, mu * 0.2)))), base_price

    if spec.pattern == "declining":
        progress = day_idx / max(total_days - 1, 1)
        decay = max(0.22, 1.35 - 1.05 * progress)
        mu = spec.base_demand * scale * dow_factor * decay
        return max(0, round(rng.gauss(mu, max(0.7, mu * 0.25)))), base_price

    if spec.pattern == "intermittent":
        # Genuine ~74% zero days, bursts when ordered
        if rng.random() > 0.26:
            return 0, base_price
        qty = rng.randint(1, max(2, round(spec.base_demand * 2.1 * scale)))
        return qty, base_price

    if spec.pattern == "spikes":
        promo_week = (day_idx % 90) in (10, 11, 12, 13, 14, 15, 16)
        event_spike = 2.6 if (day_idx % 180) in (40, 41, 42) else (1.55 if promo_week else 1.0)
        seasonal_boost = 1.28 if month in (10, 11, 12) else 1.0
        mu = spec.base_demand * scale * dow_factor * event_spike * seasonal_boost
        price = round(base_price * (0.82 if promo_week else 1.0), 2)
        return max(0, round(rng.gauss(mu, max(1.0, mu * 0.22)))), price

    if spec.pattern == "long_horizon":
        progress = day_idx / max(total_days - 1, 1)
        long_growth = 0.75 + 0.65 * progress
        annual_wave = 1.0 + 0.34 * math.sin(2.0 * math.pi * (day_idx / 365.25 - 0.12))
        festive = 1.45 if (month == 10 and cur_date.day >= 12) or (month == 11 and cur_date.day <= 18) or (month == 12 and cur_date.day >= 20) else 1.0
        mu = spec.base_demand * scale * dow_factor * long_growth * annual_wave * festive
        price = round(base_price * (0.94 if festive > 1.2 else 1.0), 2)
        return max(0, round(rng.gauss(mu, max(0.9, mu * 0.18)))), price

    return 0, base_price


def _get_or_create_supplier(
    db: Session,
    business: Business,
    report: SeedingReport,
) -> Supplier:
    existing = (
        db.query(Supplier)
        .filter(Supplier.business_id == business.id, Supplier.is_active.is_(True))
        .order_by(Supplier.id.asc())
        .first()
    )
    if existing:
        report.inc("Suppliers", "skipped", 1)
        return existing

    sup = Supplier(
        business_id=business.id,
        name="Synthetic Supply Partner",
        phone="9999000011",
        email=f"syn-supplier-b{business.id}@example.local",
        lead_time_days=5,
        is_active=True,
    )
    db.add(sup)
    db.flush()
    report.inc("Suppliers", "inserted", 1)
    return sup


def _seed_scenario_sku(
    db: Session,
    business: Business,
    supplier: Supplier,
    spec: ScenarioSpec,
    anchor_now: datetime,
    seed: int,
    report: SeedingReport,
) -> None:
    is_wholesale = (business.business_type or "").lower() == "wholesaler"
    biz_tag = "ANK" if business.id == 4 else ("SAN" if business.id == 3 else f"B{business.id}")
    sku = f"SYN-{biz_tag}-{spec.suffix}"
    unit = spec.unit_wholesale if is_wholesale else spec.unit_retail
    name = spec.wholesale_name if is_wholesale else spec.retail_name
    cost_price = round(spec.cost_price * (2.2 if is_wholesale else 1.0), 2)
    selling_price = round(spec.selling_price * (2.2 if is_wholesale else 1.0), 2)

    existing_prod = (
        db.query(Product)
        .filter(Product.business_id == business.id, Product.sku == sku)
        .first()
    )
    if existing_prod is not None:
        # Idempotent: SKU already seeded; check if history marker is complete and skip without altering records
        report.inc("Products", "skipped", 1)
        existing_sales = (
            db.query(func.count(Sale.id))
            .filter(Sale.business_id == business.id, Sale.product_id == existing_prod.id)
            .scalar()
            or 0
        )
        existing_logs = (
            db.query(func.count(InventoryLog.id))
            .filter(InventoryLog.business_id == business.id, InventoryLog.product_id == existing_prod.id)
            .scalar()
            or 0
        )
        existing_pos = (
            db.query(func.count(PurchaseOrderItem.purchase_order_id))
            .filter(PurchaseOrderItem.product_id == existing_prod.id)
            .scalar()
            or 0
        )
        existing_grs = (
            db.query(func.count(GoodsReceiptItem.goods_receipt_id))
            .filter(GoodsReceiptItem.product_id == existing_prod.id)
            .scalar()
            or 0
        )
        report.inc("Sales", "skipped", int(existing_sales))
        report.inc("InventoryLogs", "skipped", int(existing_logs))
        report.inc("PurchaseOrders", "skipped", int(existing_pos))
        report.inc("GoodsReceipts", "skipped", int(existing_grs))
        return

    history_days = max(0, spec.history_days)
    created_dt = (anchor_now - timedelta(days=max(1, history_days))).replace(hour=8, minute=0, second=0, microsecond=0)
    prod = Product(
        business_id=business.id,
        sku=sku,
        name=name,
        category=spec.category,
        unit=unit,
        cost_price=cost_price,
        selling_price=selling_price,
        current_stock=0,
        reorder_level=spec.reorder_level * (2 if is_wholesale else 1),
        min_order_quantity=spec.moq,
        order_pack_size=spec.pack_size,
        review_period_days=7,
        service_level_target=0.95,
        supplier_id=supplier.id,
        is_active=True,
        is_synthetic=True,
        created_at=created_dt,
    )
    db.add(prod)
    db.flush()
    report.inc("Products", "inserted", 1)

    rng = random.Random(f"{seed}:{business.id}:{sku}")
    owner_uid = business.owner_user_id

    if history_days == 0:
        # Cold-start product: coherent initial receipt of 25 units, zero sales
        init_qty = 25
        po_num = f"SYNPO-{business.id}-C00-001"
        gr_num = f"SYNGR-{business.id}-C00-001"
        po = PurchaseOrder(
            business_id=business.id,
            order_number=po_num,
            supplier_id=supplier.id,
            status=PurchaseOrderStatus.RECEIVED,
            total_amount=Decimal(str(round(init_qty * cost_price, 2))),
            order_date=created_dt - timedelta(days=3),
            sent_at=created_dt - timedelta(days=3),
            expected_delivery_date=created_dt,
            received_at=created_dt,
            created_by=owner_uid,
            notes=f"Synthetic demo cold-start opening PO for {sku}",
            is_synthetic=True,
        )
        db.add(po)
        db.flush()
        poi = PurchaseOrderItem(
            purchase_order_id=po.id,
            product_id=prod.id,
            ordered_quantity=init_qty,
            received_quantity=init_qty,
            unit_cost=Decimal(str(cost_price)),
        )
        db.add(poi)
        db.flush()
        gr = GoodsReceipt(
            receipt_number=gr_num,
            business_id=business.id,
            purchase_order_id=po.id,
            received_by=owner_uid,
            idempotency_key=f"syn-gr:{business.id}:{sku}:0001",
            notes=f"Synthetic demo cold-start GR for {sku}",
            is_synthetic=True,
            received_at=created_dt,
        )
        db.add(gr)
        db.flush()
        db.add(
            GoodsReceiptItem(
                goods_receipt_id=gr.id,
                purchase_order_item_id=poi.id,
                product_id=prod.id,
                quantity_received=init_qty,
            )
        )
        db.add(
            InventoryLog(
                business_id=business.id,
                product_id=prod.id,
                timestamp=created_dt,
                movement_type="PURCHASE_RECEIPT",
                stock_in=init_qty,
                stock_out=0,
                previous_stock=0,
                closing_stock=init_qty,
                reference_type="GOODS_RECEIPT",
                reference_id=gr.id,
                user_id=owner_uid,
                is_synthetic=True,
                reason=f"Synthetic demo receipt {gr_num}",
            )
        )
        prod.current_stock = init_qty
        report.inc("PurchaseOrders", "inserted", 1)
        report.inc("GoodsReceipts", "inserted", 1)
        report.inc("InventoryLogs", "inserted", 1)
        return

    # Multi-day supply chain timeline from [anchor_now - history_days .. anchor_now - 1 day]
    start_day = (anchor_now - timedelta(days=history_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    stock = 0
    cycle_idx = 0
    short_code = spec.suffix.replace("-", "")[:7]

    # Stockout demonstration window strictly for spikes-5Y scenario around days [n-35..n-31]
    stockout_start_idx = max(10, history_days - 35) if spec.pattern == "spikes" else -1
    stockout_end_idx = stockout_start_idx + 4 if stockout_start_idx > 0 else -1

    def _receive_po_batch(order_qty: int, arrival_dt: datetime, lead_days: int) -> None:
        nonlocal stock, cycle_idx
        cycle_idx += 1
        po_num = f"SYNPO-{business.id}-{short_code}-{cycle_idx:03d}"
        gr_num = f"SYNGR-{business.id}-{short_code}-{cycle_idx:03d}"
        order_dt = arrival_dt - timedelta(days=max(1, lead_days))
        po = PurchaseOrder(
            business_id=business.id,
            order_number=po_num,
            supplier_id=supplier.id,
            status=PurchaseOrderStatus.RECEIVED,
            total_amount=Decimal(str(round(order_qty * cost_price, 2))),
            order_date=order_dt,
            sent_at=order_dt + timedelta(hours=1),
            expected_delivery_date=arrival_dt,
            received_at=arrival_dt,
            created_by=owner_uid,
            notes=f"Synthetic replenishment PO cycle {cycle_idx} for {sku}",
            is_synthetic=True,
        )
        db.add(po)
        db.flush()
        poi = PurchaseOrderItem(
            purchase_order_id=po.id,
            product_id=prod.id,
            ordered_quantity=order_qty,
            received_quantity=order_qty,
            unit_cost=Decimal(str(cost_price)),
        )
        db.add(poi)
        db.flush()
        gr = GoodsReceipt(
            receipt_number=gr_num,
            business_id=business.id,
            purchase_order_id=po.id,
            received_by=owner_uid,
            idempotency_key=f"syn-gr:{business.id}:{sku}:{cycle_idx:04d}",
            notes=f"Synthetic replenishment receipt for {po_num}",
            is_synthetic=True,
            received_at=arrival_dt,
        )
        db.add(gr)
        db.flush()
        db.add(
            GoodsReceiptItem(
                goods_receipt_id=gr.id,
                purchase_order_item_id=poi.id,
                product_id=prod.id,
                quantity_received=order_qty,
            )
        )
        prev = stock
        stock += order_qty
        db.add(
            InventoryLog(
                business_id=business.id,
                product_id=prod.id,
                timestamp=arrival_dt,
                movement_type="PURCHASE_RECEIPT",
                stock_in=order_qty,
                stock_out=0,
                previous_stock=prev,
                closing_stock=stock,
                reference_type="GOODS_RECEIPT",
                reference_id=gr.id,
                user_id=owner_uid,
                is_synthetic=True,
                reason=f"Synthetic receipt {gr_num} for {po_num}",
            )
        )
        report.inc("PurchaseOrders", "inserted", 1)
        report.inc("GoodsReceipts", "inserted", 1)
        report.inc("InventoryLogs", "inserted", 1)

    reorder_trigger = max(12, round(spec.base_demand * (1.6 if is_wholesale else 1.0) * 8))
    batch_order_qty = max(40, round(spec.base_demand * (1.6 if is_wholesale else 1.0) * 65))

    # Initial opening procurement batch on day 0
    _receive_po_batch(batch_order_qty, start_day.replace(hour=8, minute=0), lead_days=4)

    pending_sales: List[tuple[Sale, int, int, datetime]] = []

    for day_idx in range(history_days):
        cur_date = start_day + timedelta(days=day_idx)
        in_stockout_window = stockout_start_idx <= day_idx <= stockout_end_idx

        # Force natural depletion right before stockout window for realism
        if spec.pattern == "spikes" and day_idx == stockout_start_idx - 1 and stock > 0:
            qty_clear = min(stock, max(1, stock))
            sale_dt = cur_date.replace(hour=16, minute=0)
            prev_s = stock
            stock = 0
            sale_obj = Sale(
                business_id=business.id,
                product_id=prod.id,
                sales_date=sale_dt,
                quantity_sold=qty_clear,
                selling_price=selling_price,
                revenue=round(qty_clear * selling_price, 2),
                status="COMPLETED",
                created_by=owner_uid,
                idempotency_key=f"syn-sale:{business.id}:{sku}:{cur_date.strftime('%Y-%m-%d')}",
                is_synthetic=True,
                notes=f"Synthetic high-demand day prior to stockout for {sku}",
            )
            pending_sales.append((sale_obj, prev_s, stock, sale_dt))
            continue

        if in_stockout_window:
            # Zero stock available -> zero recorded sales during stockout window
            continue

        # Replenish BEFORE sales if stock dropped low
        if stock <= reorder_trigger and day_idx > 0:
            # Avoid scheduling arrival right inside stockout window
            if not (stockout_start_idx > 0 and stockout_start_idx - 8 <= day_idx <= stockout_end_idx):
                lead_days = rng.choice([4, 5, 6])
                _receive_po_batch(batch_order_qty, cur_date.replace(hour=9, minute=0), lead_days=lead_days)

        # After stockout ends on day_idx == stockout_end_idx + 1, emergency replenishment arrives
        if spec.pattern == "spikes" and day_idx == stockout_end_idx + 1 and stock == 0:
            _receive_po_batch(batch_order_qty, cur_date.replace(hour=8, minute=30), lead_days=3)

        dem_qty, eff_price = _simulate_daily_demand_and_price(
            spec=spec,
            day_idx=day_idx,
            total_days=history_days,
            cur_date=cur_date,
            is_wholesale=is_wholesale,
            rng=rng,
        )
        sold = min(dem_qty, stock)
        if sold <= 0:
            continue

        sale_dt = cur_date.replace(hour=15, minute=day_idx % 50)
        prev_s = stock
        stock -= sold
        sale_obj = Sale(
            business_id=business.id,
            product_id=prod.id,
            sales_date=sale_dt,
            quantity_sold=sold,
            selling_price=eff_price,
            revenue=round(sold * eff_price, 2),
            status="COMPLETED",
            created_by=owner_uid,
            idempotency_key=f"syn-sale:{business.id}:{sku}:{cur_date.strftime('%Y-%m-%d')}",
            is_synthetic=True,
            notes=f"Synthetic historical demand ({spec.pattern}) for {sku}",
        )
        pending_sales.append((sale_obj, prev_s, stock, sale_dt))

    # Persist sales + ledger in batches so Sale.id links cleanly to InventoryLog.reference_id
    chunk_size = 500
    for i in range(0, len(pending_sales), chunk_size):
        chunk = pending_sales[i : i + chunk_size]
        sale_objs = [item[0] for item in chunk]
        db.add_all(sale_objs)
        db.flush()
        log_objs = [
            InventoryLog(
                business_id=business.id,
                product_id=prod.id,
                timestamp=sale_dt,
                movement_type="SALE",
                stock_in=0,
                stock_out=sale_obj.quantity_sold,
                previous_stock=prev_s,
                closing_stock=close_s,
                reference_type="SALE",
                reference_id=sale_obj.id,
                user_id=owner_uid,
                is_synthetic=True,
                reason=f"Synthetic historical sale {sku}",
            )
            for sale_obj, prev_s, close_s, sale_dt in chunk
        ]
        db.add_all(log_objs)
        db.flush()
        report.inc("Sales", "inserted", len(sale_objs))
        report.inc("InventoryLogs", "inserted", len(log_objs))

    prod.current_stock = stock


def _backfill_sparse_real_products(
    db: Session,
    business: Business,
    default_supplier: Supplier,
    anchor_now: datetime,
    seed: int,
    report: SeedingReport,
) -> None:
    """
    Backfill coherent 0.5Y-10Y pre-inception historical cycles on active non-synthetic
    catalog products that have < 90 sales so every ML algorithm (ARIMA, XGBoost,
    Random Forest, LSTM) can evaluate and run cleanly without altering genuine
    post-inception stock balances or genuine transaction rows.
    """
    real_prods = (
        db.query(Product)
        .filter(
            Product.business_id == business.id,
            Product.is_synthetic.is_(False),
            Product.is_active.is_(True),
        )
        .order_by(Product.id.asc())
        .all()
    )
    horizons = [3650, 2555, 1825, 1095, 730, 365, 180]
    patterns = ["seasonal", "stable", "growing", "spikes", "long_horizon", "declining"]
    is_wholesale = (business.business_type or "").lower() == "wholesaler"
    owner_uid = business.owner_user_id

    for idx, prod in enumerate(real_prods):
        bf_sales_count = (
            db.query(func.count(Sale.id))
            .filter(
                Sale.business_id == business.id,
                Sale.product_id == prod.id,
                Sale.idempotency_key.like(f"syn-bf:{business.id}:{prod.id}:%"),
            )
            .scalar()
            or 0
        )
        if bf_sales_count > 0:
            bf_logs = (
                db.query(func.count(InventoryLog.id))
                .filter(
                    InventoryLog.business_id == business.id,
                    InventoryLog.product_id == prod.id,
                    InventoryLog.is_synthetic.is_(True),
                )
                .scalar()
                or 0
            )
            bf_pos = (
                db.query(func.count(PurchaseOrder.id))
                .filter(
                    PurchaseOrder.business_id == business.id,
                    PurchaseOrder.order_number.like(f"SYNPO-BF{business.id}-{prod.id}-%"),
                )
                .scalar()
                or 0
            )
            report.inc("Sales", "skipped", bf_sales_count)
            report.inc("InventoryLogs", "skipped", bf_logs)
            report.inc("PurchaseOrders", "skipped", bf_pos)
            report.inc("GoodsReceipts", "skipped", bf_pos)
            continue

        genuine_sales = (
            db.query(func.count(Sale.id))
            .filter(
                Sale.business_id == business.id,
                Sale.product_id == prod.id,
                func.upper(func.coalesce(Sale.status, "COMPLETED")) != "CANCELLED",
            )
            .scalar()
            or 0
        )
        if genuine_sales >= 90:
            continue

        min_sale_dt = (
            db.query(func.min(Sale.sales_date))
            .filter(Sale.business_id == business.id, Sale.product_id == prod.id)
            .scalar()
        )
        min_log_dt = (
            db.query(func.min(InventoryLog.timestamp))
            .filter(InventoryLog.business_id == business.id, InventoryLog.product_id == prod.id)
            .scalar()
        )
        anchors = [dt for dt in (min_sale_dt, min_log_dt) if dt is not None]
        if anchors:
            earliest_genuine = min(anchors)
            backfill_end = earliest_genuine.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
        else:
            backfill_end = anchor_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

        hist_days = horizons[idx % len(horizons)]
        pattern = patterns[idx % len(patterns)]
        price = float(prod.selling_price or 100.0)
        cost = float(prod.cost_price or round(price * 0.72, 2))
        if price > 800:
            base_d = 2.6
        elif price > 200:
            base_d = 4.5
        else:
            base_d = 7.5
        spec = ScenarioSpec(
            suffix=f"BF{prod.id}",
            retail_name=prod.name,
            wholesale_name=prod.name,
            category=prod.category or "General",
            unit_retail=prod.unit or "piece",
            unit_wholesale=prod.unit or "piece",
            cost_price=cost,
            selling_price=price,
            history_days=hist_days,
            pattern=pattern,
            base_demand=base_d,
            reorder_level=max(10, prod.reorder_level or 10),
        )

        start_day = backfill_end - timedelta(days=hist_days - 1)
        rng = random.Random(f"{seed}:bf:{business.id}:{prod.id}:{prod.sku}")
        daily_demands: List[tuple[datetime, int, float]] = []
        stockout_start = max(15, hist_days - 40)
        stockout_end = stockout_start + 3

        for day_idx in range(hist_days):
            cur_date = start_day + timedelta(days=day_idx)
            if stockout_start <= day_idx <= stockout_end:
                daily_demands.append((cur_date, 0, price))
                continue
            q, eff_p = _simulate_daily_demand_and_price(
                spec=spec,
                day_idx=day_idx,
                total_days=hist_days,
                cur_date=cur_date,
                is_wholesale=is_wholesale,
                rng=rng,
            )
            daily_demands.append((cur_date, q, price if eff_p <= 0 else round(price * (eff_p / max(price * (2.2 if is_wholesale else 1.0), 1e-6)), 2)))

        # Guarantee >= 75 non-zero demand days across all generated horizons so LSTM/XGB/ARIMA/RF qualify cleanly
        nonzero_indices = [i for i, (_, q, _) in enumerate(daily_demands) if q > 0]
        if len(nonzero_indices) < 75:
            for d_i in range(0, hist_days, max(1, hist_days // 90)):
                dt_v, q_v, p_v = daily_demands[d_i]
                if q_v == 0:
                    daily_demands[d_i] = (dt_v, 2, p_v)

        cycle_days = 55
        sup_id = prod.supplier_id or default_supplier.id
        running_stock = 0
        pending_sales: List[tuple[Sale, int, int, datetime]] = []
        cycle_idx = 0

        for c_start in range(0, hist_days, cycle_days):
            c_slice = daily_demands[c_start : c_start + cycle_days]
            batch_qty = sum(q for _, q, _ in c_slice)
            if batch_qty <= 0:
                continue
            cycle_idx += 1
            arrival_dt = c_slice[0][0].replace(hour=8, minute=0)
            lead_days = rng.choice([4, 5, 6])
            order_dt = arrival_dt - timedelta(days=lead_days)
            po_num = f"SYNPO-BF{business.id}-{prod.id}-{cycle_idx:03d}"
            gr_num = f"SYNGR-BF{business.id}-{prod.id}-{cycle_idx:03d}"

            po = PurchaseOrder(
                business_id=business.id,
                order_number=po_num,
                supplier_id=sup_id,
                status=PurchaseOrderStatus.RECEIVED,
                total_amount=Decimal(str(round(batch_qty * cost, 2))),
                order_date=order_dt,
                sent_at=order_dt + timedelta(hours=1),
                expected_delivery_date=arrival_dt,
                received_at=arrival_dt,
                created_by=owner_uid,
                notes=f"Synthetic historical backfill cycle {cycle_idx} for {prod.sku}",
                is_synthetic=True,
            )
            db.add(po)
            db.flush()
            poi = PurchaseOrderItem(
                purchase_order_id=po.id,
                product_id=prod.id,
                ordered_quantity=batch_qty,
                received_quantity=batch_qty,
                unit_cost=Decimal(str(cost)),
            )
            db.add(poi)
            db.flush()
            gr = GoodsReceipt(
                receipt_number=gr_num,
                business_id=business.id,
                purchase_order_id=po.id,
                received_by=owner_uid,
                idempotency_key=f"syn-bf-gr:{business.id}:{prod.id}:{cycle_idx:04d}",
                notes=f"Synthetic historical backfill receipt for {po_num}",
                is_synthetic=True,
                received_at=arrival_dt,
            )
            db.add(gr)
            db.flush()
            db.add(
                GoodsReceiptItem(
                    goods_receipt_id=gr.id,
                    purchase_order_item_id=poi.id,
                    product_id=prod.id,
                    quantity_received=batch_qty,
                )
            )
            prev_s = running_stock
            running_stock += batch_qty
            db.add(
                InventoryLog(
                    business_id=business.id,
                    product_id=prod.id,
                    timestamp=arrival_dt,
                    movement_type="PURCHASE_RECEIPT",
                    stock_in=batch_qty,
                    stock_out=0,
                    previous_stock=prev_s,
                    closing_stock=running_stock,
                    reference_type="GOODS_RECEIPT",
                    reference_id=gr.id,
                    user_id=owner_uid,
                    is_synthetic=True,
                    reason=f"Synthetic backfill receipt {gr_num}",
                )
            )
            report.inc("PurchaseOrders", "inserted", 1)
            report.inc("GoodsReceipts", "inserted", 1)
            report.inc("InventoryLogs", "inserted", 1)

            for offset_idx, (d_ts, qty_sold, unit_p) in enumerate(c_slice):
                if qty_sold <= 0:
                    continue
                sale_dt = d_ts.replace(hour=15, minute=(c_start + offset_idx) % 50)
                s_prev = running_stock
                running_stock -= qty_sold
                sale_obj = Sale(
                    business_id=business.id,
                    product_id=prod.id,
                    sales_date=sale_dt,
                    quantity_sold=qty_sold,
                    selling_price=unit_p,
                    revenue=round(qty_sold * unit_p, 2),
                    status="COMPLETED",
                    created_by=owner_uid,
                    idempotency_key=f"syn-bf:{business.id}:{prod.id}:{d_ts.strftime('%Y-%m-%d')}",
                    is_synthetic=True,
                    notes=f"Synthetic pre-inception historical backfill ({pattern}) for {prod.sku}",
                )
                pending_sales.append((sale_obj, s_prev, running_stock, sale_dt))

        chunk_size = 500
        for i in range(0, len(pending_sales), chunk_size):
            chunk = pending_sales[i : i + chunk_size]
            sale_objs = [item[0] for item in chunk]
            db.add_all(sale_objs)
            db.flush()
            log_objs = [
                InventoryLog(
                    business_id=business.id,
                    product_id=prod.id,
                    timestamp=sale_dt,
                    movement_type="SALE",
                    stock_in=0,
                    stock_out=sale_obj.quantity_sold,
                    previous_stock=s_prev,
                    closing_stock=s_close,
                    reference_type="SALE",
                    reference_id=sale_obj.id,
                    user_id=owner_uid,
                    is_synthetic=True,
                    reason=f"Synthetic backfill sale {prod.sku}",
                )
                for sale_obj, s_prev, s_close, sale_dt in chunk
            ]
            db.add_all(log_objs)
            db.flush()
            report.inc("Sales", "inserted", len(sale_objs))
            report.inc("InventoryLogs", "inserted", len(log_objs))


def seed_demo_historical_datasets(
    db: Session,
    *,
    target_business_ids: Optional[Sequence[int]] = None,
    seed: int = 42,
    enforce_env_guard: bool = True,
    backfill_existing_sparse: bool = True,
) -> SeedingReport:
    """
    Seed coherent, deterministic, idempotent 0-10 year historical datasets into every
    target retailer/wholesaler workspace while leaving genuine post-inception records intact.
    """
    env_name = verify_seed_environment() if enforce_env_guard else "test"
    report = SeedingReport(env=env_name, seed=seed)
    biz_ids = (
        list(target_business_ids)
        if target_business_ids is not None
        else resolve_target_business_ids(db)
    )

    anchor_now = datetime.now(timezone.utc).replace(tzinfo=None, hour=12, minute=0, second=0, microsecond=0)

    for bid in biz_ids:
        business = db.query(Business).filter(Business.id == bid).first()
        if business is None:
            report.workspaces_skipped.append({"business_id": bid, "reason": "Workspace not found in database"})
            continue

        supplier = _get_or_create_supplier(db, business, report)
        for spec in SCENARIO_CATALOG:
            _seed_scenario_sku(
                db=db,
                business=business,
                supplier=supplier,
                spec=spec,
                anchor_now=anchor_now,
                seed=seed,
                report=report,
            )
        if backfill_existing_sparse:
            _backfill_sparse_real_products(
                db=db,
                business=business,
                default_supplier=supplier,
                anchor_now=anchor_now,
                seed=seed,
                report=report,
            )
        db.commit()
        report.workspaces_processed.append(
            {"business_id": business.id, "name": business.name, "business_type": business.business_type}
        )

    return report


def seed_historical_sales(days: int = 700):
    """Backward-compatible entrypoint delegating safely to seed_demo_historical_datasets."""
    db = SessionLocal()
    try:
        report = seed_demo_historical_datasets(db=db, target_business_ids=None, seed=42)
        _print_report_table(report)
    finally:
        db.close()


def _print_report_table(report: SeedingReport) -> None:
    print(f"\n[SIMS Historical Seeder] env={report.env} seed={report.seed}")
    print(f"Workspaces processed: {report.workspaces_processed}")
    if report.workspaces_skipped:
        print(f"Workspaces skipped: {report.workspaces_skipped}")
    print("\nEntity           | Inserted | Skipped | Failed")
    print("-----------------+----------+---------+-------")
    for entity, stats in report.counts.items():
        print(f"{entity:<16} | {stats['inserted']:>8} | {stats['skipped']:>7} | {stats['failed']:>6}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SIMS Deterministic Historical Demo Dataset Seeder")
    parser.add_argument(
        "--business-id",
        type=int,
        action="append",
        dest="business_ids",
        help="Target workspace business_id (can pass multiple times; defaults to all retailer/wholesaler workspaces)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic PRNG seed")
    parser.add_argument(
        "--warm-forecasts",
        action="store_true",
        help="Run ForecastingService.generate_product_forecast on seeded/stale workspace SKUs after seeding",
    )
    parser.add_argument(
        "--warm-all",
        action="store_true",
        help="Warm forecasts for ALL active products (including genuine products) across processed workspaces",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        biz_ids = args.business_ids or None
        report = seed_demo_historical_datasets(db=db, target_business_ids=biz_ids, seed=args.seed)
        _print_report_table(report)

        if args.warm_forecasts or args.warm_all:
            from app.ml.forecasting_service import ForecastingService

            warmed = 0
            for ws in report.workspaces_processed:
                bid = ws["business_id"]
                prod_query = db.query(Product).filter(Product.business_id == bid, Product.is_active.is_(True))
                if not args.warm_all:
                    prod_query = prod_query.filter(Product.is_synthetic.is_(True))
                prods_to_warm = prod_query.order_by(Product.id.asc()).all()
                for p in prods_to_warm:
                    res = ForecastingService.generate_product_forecast(
                        db=db, product_id=p.id, horizon_days=30, model_choice="auto", business_id=bid
                    )
                    warmed += 1
                    print(
                        f"  Forecast biz={bid} sku={p.sku}: model={res['model_display_name']} "
                        f"tier={res['data_sufficiency']} fallback={res['fallback_used']} expected_30d={res['expected_total_demand']}"
                    )
            print(f"\nWarmed {warmed} forecasts successfully.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
