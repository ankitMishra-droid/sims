# Inventory Intelligence REST API Reference — SIMS Phase 6

All endpoints require valid JWT Bearer authentication (`Authorization: Bearer <token>`) and workspace scoping (`X-Business-Id` or user's active workspace via `require_business_roles`).  
**Role Matrix:**
- `READ_ROLES`: `owner`, `admin`, `manager`, `analyst`, `staff` (strictly excludes `supplier` workspace role)
- `WRITE_ROLES`: `owner`, `admin`, `manager`, `analyst`
- `PO_WRITE_ROLES`: `owner`, `admin`, `manager`

---

## 1. Phase 6 Unified Intelligence Router (`/api/intelligence`)

### `GET /api/intelligence/overview`
Query: `service_level` (optional float `0.80..0.999`), `sync` (bool, default `true`).  
Returns KPIs (`total_active_products`, `sufficiency_breakdown`, `stockout_risk_breakdown`, `open_recommendations_count`, `reorder_candidates_count`, `estimated_reorder_investment`, `overstock_capital_tied_up`, `high_delay_risk_suppliers`), top 10 prioritized recommendations, and supplier lead-time report.

### `GET /api/intelligence/forecasts`
Query: `horizon_days` (`7..90`, default `30`).  
Returns list of workspace product forecast summaries (`model_used`, `data_sufficiency`, `is_cold_start`, `expected_total_demand`, `avg_predicted_daily_demand`, `data_cutoff_date`, `stockout_days_count`, `cached`).

### `GET /api/intelligence/forecasts/{product_id}`
Query: `horizon_days` (`7..90`), `model` (`auto`, `moving_average`, `weighted_moving_average`, `ses`, `seasonal_naive`, `croston`, `arima`, `prophet`, `random_forest`, `xgboost`, `lstm`), `force_refresh` (bool).  
Returns full `historical_series`, `forecast_series` (`date`, `predicted_demand`, `lower_bound`, `upper_bound`), `historical_summary`, `evaluation_metrics`, `selection_reason`, and cold-start indicator. Returns `404` if `product_id` does not belong to `ctx.business_id`.

### `POST /api/intelligence/forecasts/refresh` *(WRITE_ROLES)*
Body: `{ "product_id": int | null, "horizon_days": 30, "sync_recommendations": true }`.  
Forces recalculation of persisted `ProductForecast` and `ModelEvaluation` rows across one SKU or the entire active workspace catalog.

### `GET /api/intelligence/evaluations/{product_id}`
Query: `test_days` (`3..60`, default `14`), `force_refresh` (bool).  
Returns rolling-origin CV leaderboard sorted by `(WAPE, MAE, RMSE)` showing baselines, gated complex models (`SKIPPED_INSUFFICIENT_DATA`), folds evaluated, nullable MAPE, MASE, and champion rationale.

### `GET /api/intelligence/recommendations`
Query: `status` (`OPEN` | `NEW` | `VIEWED` | `ACCEPTED` | `DISMISSED` | `CONVERTED_TO_PO` | `EXPIRED` | `ALL`), `recommendation_type` (`REORDER_NOW`, `LOW_STOCK_RISK`, `OVERSTOCK_ALERT`, `DEMAND_INCREASING`, `DEMAND_DECREASING`, `SUPPLIER_LEAD_TIME_RISK`, `COLD_START_REVIEW`), `sync` (bool), `service_level`.  
Returns deduplicated persistent recommendations for the workspace.

### `GET /api/intelligence/recommendations/{recommendation_id}`
Marks `NEW` -> `VIEWED` and returns full inventory position, formula breakdown (`explanation_details`), and explainable reason summary.

### `POST /api/intelligence/recommendations/{recommendation_id}/accept` *(WRITE_ROLES)*
Body: `{ "adjusted_order_qty": int | null }`.  
Transitions recommendation to `ACCEPTED` with optional reviewed quantity override.

### `POST /api/intelligence/recommendations/{recommendation_id}/dismiss` *(WRITE_ROLES)*
Body: `{ "reason": string | null }`.  
Transitions recommendation to `DISMISSED` (suppressed from auto-reopening for 7 days unless urgency escalates to `CRITICAL` or inventory position drops).

### `POST /api/intelligence/recommendations/{recommendation_id}/convert-to-po` *(PO_WRITE_ROLES)*
Body:
```json
{
  "supplier_id": 1,
  "ordered_quantity": 25,
  "expected_delivery_date": "2026-12-05",
  "notes": "Confirmed replenishment PO",
  "confirmed": true
}
```
Requires `confirmed=true` (`400` otherwise), creates a `DRAFT` Purchase Order via `ProcurementService`, sets `linked_purchase_order_id`, transitions status to `CONVERTED_TO_PO` (`409` on duplicate attempt), and returns `{ status, message, recommendation, purchase_order_id, order_number, total_amount }`. Does NOT increment stock.

### `GET /api/intelligence/stockout-risks` & `GET /api/intelligence/overstock-risks`
Return active workspace products ordered by critical/high stockout risk or excess overstock/dead-stock capital value.

### `GET /api/intelligence/suppliers/lead-times`
Returns per-supplier empirical lead times (`effective_lead_time_days`, `lead_time_std_days`, `lead_time_source`, `sample_count`, `on_time_delivery_rate`, `delay_risk`).

---

## 2. Preserved Compatibility Endpoints (Upgraded Internals, Tenant-Scoped)
- `GET /api/forecast/{product_id}` & `GET /api/forecast/compare/{product_id}`
- `GET /api/decision/recommendations`, `GET /api/decision/product/{product_id}`, `POST /api/decision/convert-to-po`
- `POST /api/simulator/scenario`
- `GET /api/analytics/anomalies/{product_id}`
