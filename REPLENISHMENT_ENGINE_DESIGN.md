# Replenishment Engine & Lead-Time Intelligence Design — SIMS Phase 6

## 1. Authoritative Inventory Position (`InventoryService`)
All replenishment decisions evaluate **Inventory Position**, never raw on-hand stock alone:

$$\text{InventoryPosition} = \text{OnHandStock} + \text{IncomingStock} - \text{ReservedStock}$$

- **`OnHandStock`**: `Product.current_stock` (mutated strictly by `stock_service`).
- **`IncomingStock`**: `InventoryService.get_incoming_stock_map(db, business_id, [product_id])`, summing `(ordered_quantity - received_quantity)` solely for `PurchaseOrder.status IN ('SENT', 'PARTIALLY_RECEIVED')`. Excludes `DRAFT` and `CANCELLED` orders and deducts quantities already received.
- **`ReservedStock`**: `0` currently (`reservations_supported = False`).

---

## 2. Empirical Supplier Lead-Time Intelligence (`SupplierLeadTimeService`)
For each assigned supplier inside `business_id`:
- Inspects non-cancelled `PurchaseOrder` rows and linked `GoodsReceipt` records.
- For completed POs (`RECEIVED`), calculates elapsed days from `po.sent_at or po.order_date` to `po.received_at or max(receipt.received_at)`.
- Sub-6-hour observations (`< 0.25d`, e.g., immediate test setup workflows) do not override realistic `Supplier.lead_time_days`. When `>= 2` meaningful completed POs exist (`source="po_receipt_history"`):
  - $L = \text{mean}(\text{lead\_days})$
  - $\sigma_L = \text{std}_{ddof=1}(\text{lead\_days})$
- When only 1 meaningful receipt or only partial receipts exist, uses partial/single-PO observations cleanly labeled (`"single_po_receipt"` / `"partial_receipt_history"`).
- When no receipt history exists, falls back explicitly to `Supplier.lead_time_days` (or system default `7.0d` if unassigned) with conservative $\sigma_L = \max(0.5, 0.20 \cdot L)$ labeled `"supplier_default"` / `"system_default"`.
- Computes `on_time_delivery_rate` and `late_delivery_rate` when `expected_delivery_date` is recorded (`HIGH` delay risk when `late_rate >= 30%` over >= 2 tracked orders).

---

## 3. Replenishment & Buffer Equations (`InventoryDecisionService`)
Given average forecast daily demand $d \ge 0$, demand standard deviation $\sigma_d \ge 0$, effective lead time $L$, lead-time std dev $\sigma_L$, review period $R$ (`product.review_period_days`, default `7`), and target service level $SL$ (`norm.ppf(SL)`):

1. **Zero-Demand Safety:** If $d = 0$, no demand-driven reorder is fabricated (`SafetyStock = 0, ROP = 0, TargetStock = 0, SuggestedOrderQty = 0`).
2. **When $d > 0$:**
   - $\text{LeadTimeDemand} = d \cdot L$
   - $\text{SafetyStock} = \lceil Z_{SL} \cdot \sqrt{L \cdot \sigma_d^2 + d^2 \cdot \sigma_L^2} \rceil$
   - $\text{ReorderPoint} = \lceil d \cdot L + \text{SafetyStock} \rceil$
   - $\text{TargetStockLevel} = \min(\lceil d \cdot (L + R) + \text{SafetyStock} \rceil,\ \text{max\_stock\_level})$ (if `max_stock_level` is configured)
3. **Suggested Order Quantity & Policy Constraints (`apply_ordering_constraints`):**
   - Triggered when `InventoryPosition <= ReorderPoint` (`raw_need = max(0, TargetStockLevel - InventoryPosition)`).
   - Rounded up to `order_pack_size` multiples (`ceil(raw / pack) * pack`).
   - Enforces minimum order quantity `min_order_quantity` (rounded up to pack size).
   - Clamped to remaining headroom (`max_stock_level - InventoryPosition`) when `max_stock_level` is configured, annotating any MOQ/cap conflict transparently.
4. **EOQ Reference:** Computes informational Economic Order Quantity (`sqrt(2 * 365*d * 50 / max(1, 0.20 * cost_price))`).

---

## 4. Risk Categories, Overstock Detection & Persisted Lifecycle
- **Days of Cover:** Both `days_of_cover_on_hand = OnHand / d` and `days_of_cover_position = InventoryPosition / d` plus `projected_stockout_date`.
- **Stockout Risk Tiers:**
  - `CRITICAL`: `OnHand == 0` (with $d > 0$ or static threshold > 0) or `days_of_cover_position < L`.
  - `HIGH`: `days_of_cover_position < L + SafetyStock/d` or `InventoryPosition <= ReorderPoint`.
  - `OVERSTOCK`: `InventoryPosition > max(TargetStock * 1.75, 90 * d)` or stagnant stock (`>0` units, `>= 60` days since last sale with `>= 30` history days -> `DEAD_STOCK`).
- **Persisted Recommendation Deduplication (`RecommendationLifecycleService`):**
  - Open records deduplicate per `(business_id, product_id, recommendation_type)`.
  - Lifecycle: `NEW -> VIEWED -> ACCEPTED -> CONVERTED_TO_PO`, `DISMISSED` (suppressed for 7 days unless urgency escalates to `CRITICAL` or inventory drops), or `EXPIRED` automatically when inventory position recovers above target/ROP.
  - Converting to PO requires explicit user confirmation (`confirmed=True`) and creates a **`DRAFT` Purchase Order** strictly via `ProcurementService.create_purchase_order`. Stock never mutates on conversion; inventory increases only on `GoodsReceipt`.
