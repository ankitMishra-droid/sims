# Phase 6 Implementation Report — SIMS Inventory Intelligence, Demand Forecasting & Smart Replenishment

**System:** StockSangati (SIMS)  
**Scope Completed:** Database schema evolution (`0002_phase6_intelligence`), tenant-isolated demand pipeline, sufficiency-gated forecasting engine, rolling-origin cross-validation, supplier lead-time intelligence, explainable replenishment engine with lifecycle persistence, `/api/intelligence/*` REST endpoints, React UI pages & PO confirmation workflow, EN/HI multilingual coverage.

---

## 1. Summary of Architecture & Implemented Modules

### 1.1 Database & Schema Extensions (`backend/app/models/`, `backend/migrations/versions/0002_phase6_intelligence.py`)
- **`products` ordering policy extensions** (with non-breaking defaults and cross-dialect check constraints):
  - `min_order_quantity` (Integer >= 1, default `1`)
  - `order_pack_size` (Integer >= 1, default `1`)
  - `max_stock_level` (Nullable Integer > 0)
  - `review_period_days` (Integer >= 0, default `7`)
  - `service_level_target` (Float in `[0.5, 0.9999]`, default `0.95`)
  - `initial_daily_demand` (Nullable Float >= 0 for optional new-SKU cold-start estimates)
- **New persisted intelligence tables (`backend/app/models/intelligence.py`):**
  - `product_forecasts`: stores persisted forecast horizons per `(business_id, product_id, horizon_days)` with `data_cutoff_date`, `data_sufficiency`, `champion_model`, `model_version`, `is_cold_start`, `stockout_days_count`, serialized trajectory JSON, and automatic invalidation when new sales occur.
  - `model_evaluations`: stores rolling-origin validation leaderboard rows (`model_name`, `is_baseline`, `is_champion`, `evaluation_strategy`, `folds_evaluated`, `mae`, `rmse`, `mape`, `smape`, `wape`, `mase`, `status`, `notes`).
  - `replenishment_recommendations`: stores deduplicated recommendations keyed by `dedup_key = "biz:{business_id}:prod:{product_id}:cat:{recommendation_type}"`, supporting `NEW -> VIEWED -> ACCEPTED -> CONVERTED_TO_PO`, `DISMISSED`, and `EXPIRED` transitions with linked `purchase_order_id`.

### 1.2 Data Preparation & Forecasting Pipeline (`backend/app/ml/`)
- `ingestion_service.py`: strictly scopes reads by `business_id`, excludes `Sale.status == "CANCELLED"`, enforces `as_of_date` cutoff, and loads daily stock ledger closing balances (`InventoryLog`) for stockout-day inference.
- `preprocess_service.py`: aggregates same-day sales onto continuous calendars extended through `as_of_date` so trailing zero-demand days are counted, tags ledger-confirmed `is_stockout_day` entries separately from free zero-demand days, applies conservative positive-series outlier winsorization (`IQR` / `MAD`), and computes `analyze_demand_profile(...)` (`avg_daily_demand`, `demand_std_dev`, `cv`, `adi`, `trend_pct_change`, `data_sufficiency`).
- `feature_service.py`: builds strictly causal lag, rolling mean/std, and cyclic calendar features without `bfill` lookahead leakage.
- `models/baseline_models.py`: implements `NaiveForecaster`, `SeasonalNaiveForecaster`, `MovingAverageForecaster`, `WeightedMovingAverageForecaster`, `SimpleExponentialSmoothingForecaster`, `CrostonSBAForecaster`, and `ColdStartForecaster`.
- `evaluation_service.py`: executes chronological rolling-origin cross-validation (`_build_rolling_folds`), computes zero-safe MAE/RMSE/nullable-MAPE/sMAPE/WAPE/MASE, enforces baseline-first champion promotion, and skips heavy ML candidates (`LSTMSequenceNetwork`, `XGBoost`, `RandomForest`, `ARIMA`, `AdditiveProphet`) on `NEW`/`LIMITED`/`INTERMITTENT` tiers.
- `forecasting_service.py`: orchestrates forecast generation, persists `ProductForecast` and `ModelEvaluation` records, and caches results cleanly inside PostgreSQL/SQLite.

### 1.3 Supplier Lead Time, Replenishment, Simulation & Recommendation Lifecycle
- `lead_time_service.py`: measures empirical supplier lead time mean & variability (`sigma_L`), late delivery rate, and partial-delivery signals from `PurchaseOrder.sent_at` / `order_date` and `GoodsReceipt.received_at`, falling back explicitly to `Supplier.lead_time_days` (`"supplier_default"`) when fewer than 2 completed multi-hour receipts exist.
- `decision_service.py`: computes `InventoryPosition = OnHand + Incoming(SENT/PARTIALLY_RECEIVED) - Reserved`, normal quantile `Z = scipy.stats.norm.ppf(service_level)`, stochastic `SafetyStock`, `ReorderPoint`, protection-period `TargetStock = ceil(d * (L + R) + SS)`, `SuggestedOrderQty` respecting MOQ/pack/max-stock constraints, stockout risk, overstock/dead-stock risk, and deterministic formula explanations.
- `recommendation_service.py`: synchronizes deduplicated persistent recommendations, validates status transitions, and converts confirmed recommendations strictly to **DRAFT** Purchase Orders via `ProcurementService.create_purchase_order` without ever touching `Product.current_stock`.
- `anomaly_service.py` & `simulation_service.py`: upgraded with `business_id` scoping, stockout-aware anomaly filtering, and empirical `demand_std_dev`/`lead_time_std_days` propagation.

### 1.4 API & Frontend Integration
- Backend routers: `backend/app/routers/intelligence.py` (`/api/intelligence/*`) plus tenant-scoped compatibility alignments in `forecast.py`, `decision.py`, `simulator.py`, and `analytics.py`, and `"intelligence.read"`/`"intelligence.write"` RBAC permissions in `backend/app/core/permissions.py`.
- Frontend pages & components (`frontend/smart inventory forecast management system/src/`):
  - `pages/IntelligenceOverviewPage.jsx` (`/intelligence`)
  - Upgraded `pages/ForecastingPage.jsx` (combined historical + predicted trajectory chart, confidence bounds, cold-start alerts, demand diagnostics, rolling-origin leaderboard)
  - Upgraded `pages/ReorderPlannerPage.jsx` (persisted queue, lifecycle filters, explanation inspector, mandatory **Review & Confirm Draft PO Modal** preventing stock mutation)
  - Upgraded `pages/StockAlertsPage.jsx`, `pages/DashboardPage.jsx` (restrained intelligence card), `components/products/ProductFormModal.jsx` (MOQ/pack/max stock/review period/initial demand fields), `api.js`, `Sidebar.jsx`, `CommandPalette.jsx`, and EN/HI dictionaries in `i18n/translations.js`.

---

## 2. Invariants Preserved
- **Multi-Tenant Isolation:** Every intelligence service query, persisted cache table, evaluation record, recommendation row, and API endpoint enforces `business_id` membership.
- **Inventory & Procurement Integrity:** Stock increases occur **exclusively** via Goods Receipts inside `ProcurementService`/`stock_service`. Accepting or converting a recommendation creates only a `DRAFT` PO after user review and confirmation.
- **Backward Compatibility:** Existing `/api/forecast/*`, `/api/decision/*`, `/api/simulator/*`, `/api/analytics/*` endpoints remain operational alongside `/api/intelligence/*`.
