# Phase 6 Architecture Audit — SIMS (StockSangati)

**Audit Date:** 2026-11-27  
**Scope:** End-to-end review of SIMS backend (`backend/app/`), database/Alembic schema (`backend/migrations/`), existing ML modules (`backend/app/ml/`), routers (`backend/app/routers/`), frontend intelligence UI (`frontend/smart inventory forecast management system/src/`), and existing regression tests (`tests/`, `frontend/.../tests/`).

---

## 1. Existing Architecture Overview

SIMS is a multi-tenant Inventory & Procurement SaaS built on:
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic (`backend/app/main.py`, `backend/app/database.py`, `backend/app/db_migrate.py`), supporting both SQLite (local dev/tests) and PostgreSQL/Supabase (`0001_initial_schema.py`).
- **Multi-Tenancy & RBAC:** Tenant isolation keyed by `business_id`, enforced via `BusinessContext` (`require_business_roles`) across routers (`products`, `sales`, `inventory`, `suppliers`, `purchase_orders`, `dashboard`, `forecast`, `decision`, `simulator`, `analytics`, `onboarding`, `members`, `supplier_portal`).
- **Authoritative Inventory Ledger & Procurement Workflow:**
  - Stock quantities change strictly through `backend/app/services/stock_service.py` (`apply_stock_movement`, appending `InventoryLog` rows inside the active transaction).
  - `InventoryService.get_incoming_stock_map` computes incoming stock strictly as `SUM(ordered_quantity - received_quantity)` across active open POs (`SENT` and `PARTIALLY_RECEIVED`), excluding `DRAFT` and `CANCELLED`.
  - Purchase orders follow `DRAFT -> SENT -> PARTIALLY_RECEIVED -> RECEIVED` / `CANCELLED` via `ProcurementService`, with stock increasing only when a `GoodsReceipt` is created.
  - Cancelled sales transition `Sale.status` to `CANCELLED` and post a `REVERSAL` movement via `SalesService.cancel_sale`.
- **Frontend:** React 19 + Redux Toolkit (`authSlice`, `uiSlice`, `productsSlice`, `suppliersSlice`, `purchaseOrdersSlice`, `inventorySlice`, `salesSlice`) + React Router + Chart.js (`react-chartjs-2`), standardized Inter + Noto Sans Devanagari typography, semantic CSS tokens (`--erp-*`), and EN/HI translations (`src/i18n/translations.js`).
- **Existing ML Stubs / V1 Pipeline (`backend/app/ml/`):**
  - `ingestion_service.py`, `preprocess_service.py`, `feature_service.py`, `evaluation_service.py`, `forecasting_service.py`, `decision_service.py`, `anomaly_service.py`, `simulation_service.py`, and 5 model wrappers (`arima_model.py`, `prophet_model.py`, `rf_model.py`, `xgb_model.py`, `lstm_model.py`).
  - Note: `backend/app/inventory/forecast_service.py` and `backend/app/inventory/inventory_service.py` are empty placeholder files.

---

## 2. Critical Defects, Gaps & Architectural Risks Found

### 2.1 Tenant Isolation & Data Quality Defects (`ingestion_service.py`, `preprocess_service.py`, `feature_service.py`)
1. **Unscoped Sales Ingestion (`DataIngestionService.load_from_database`):**
   - Queries `Sale` and `Product` without filtering by `business_id`. Any direct service call without router guards risks cross-tenant contamination or leaking products across workspaces.
2. **Cancelled Sales Included as Real Demand:**
   - Does not filter out `Sale.status == "CANCELLED"`, inflating historical demand and forecasts whenever orders are cancelled/reversed.
3. **Trailing Zero-Demand Blindness & Stockout Blindness (`DataPreprocessingService.prepare_daily_series`):**
   - Builds the continuous daily date index strictly from `[min(sale_date), max(sale_date)]`, omitting zero-demand days between `max(sale_date)` and `as_of_date` (today). A stagnant SKU whose last sale was 45 days ago appears to have high daily average demand instead of near-zero recent demand.
   - Replaces missing days blindly with `0.0` without distinguishing true zero-demand days from **stockout days** (days where closing/on-hand stock reached `0` and constrained sales) or pre-launch days prior to `product.created_at`.
4. **Lookahead Leakage in Feature Engineering (`FeatureEngineeringService.create_features`):**
   - Uses `.bfill().ffill()` on lag and rolling features, copying future lag observations backward into early historical rows.

### 2.2 Forecasting & Evaluation Defects (`base_model.py`, `evaluation_service.py`, `forecasting_service.py`, `models/*`)
5. **No Simple Baselines & No Data Sufficiency Gating:**
   - Every SKU is evaluated on all 5 heavy models (`ARIMA`, `Prophet`, `RandomForest`, `XGBoost`, `LSTM`) regardless of history length or intermittency. Short/sparse series (< 14–30 days) cause overfitting or runtime errors.
   - Missing classical retail baselines: Naive, Seasonal Naive (7-day), Moving Average (7/14/30d), Weighted Moving Average, Simple Exponential Smoothing (SES), and Intermittent Demand (Croston / SBA).
6. **Cold-Start Failures:**
   - `ForecastingService.generate_product_forecast` raises `ValueError` for products with 0 sales or very short history instead of falling back cleanly to a cold-start strategy (configured `initial_daily_demand`, category/unit conservative estimate, or explicit insufficient-history status with honest uncertainty).
7. **Single-Split Evaluation & Misleading Metrics (`evaluate()`):**
   - `ModelEvaluationService` evaluates a single fixed cutoff instead of chronological rolling-origin / walk-forward cross-validation.
   - `BaseForecastingModel.evaluate` returns `mape = 0.0` when `y_true` contains all zeros (`~non_zero_mask.any()`), falsely implying 100% forecast accuracy on zero-demand series instead of returning `None` for MAPE and using zero-safe WAPE/MAE/RMSE/sMAPE/MASE.
8. **Silent Model Training Bugs & Latency:**
   - `LSTMForecaster` only updates output layer weights (`W_ho`, `b_o`) with random frozen recurrent weights, while still running 30+ epoch loops per request.
   - `_champion_cache` is an in-memory dict keyed solely by `product_id` (not `(business_id, product_id, horizon, data_cutoff)`), is never persisted in DB, never invalidates on new sales, and can leak model state across tests/processes.

### 2.3 Replenishment, Supplier Lead Time & Procurement Defects (`decision_service.py`, `decision.py`, Frontend)
9. **Fabricated Demand Floor & Hardcoded Lead-Time Uncertainty:**
   - `InventoryDecisionService` forces `if d <= 0: d = 0.5`, creating fake demand (and spurious reorder suggestions) for zero-demand dead stock.
   - Hardcodes `sigma_L = 1.0` instead of learning empirical lead-time mean/variability from historical `PurchaseOrder` (`sent_at` / `order_date`) and `GoodsReceipt` (`received_at`), with clean fallback to `Supplier.lead_time_days`.
10. **Incomplete Replenishment Formula & Missing Policy Constraints:**
    - `recommended_qty` ignores protection-period target stock (`(L + review_period) * d + SS - InventoryPosition`), does not support optional MOQ (`min_order_quantity`), pack size (`order_pack_size`), or max stock cap (`max_stock_level`), and computes `days_remaining` using `on_hand` rather than both `on_hand` cover and `inventory_position` cover.
    - Silently drops products from `/api/decision/recommendations` when `generate_product_forecast` raises `ValueError` (swallowing exceptions via `print`), hiding cold-start/zero-sale items from risk dashboards.
11. **Missing Persisted Recommendation Lifecycle & Explainability:**
    - Recommendations are computed statelessly on each GET request with no persistence, deduplication, status tracking (`NEW`, `VIEWED`, `ACCEPTED`, `DISMISSED`, `CONVERTED_TO_PO`, `EXPIRED`, `RECALCULATED`), or audit linkage to created POs.
    - Missing structured, formula-backed human explanations (`why` a quantity was suggested and `what` inputs drove it).
12. **Procurement Confirmation Safety:**
    - `POST /api/decision/convert-to-po` creates a `DRAFT` PO cleanly via `ProcurementService`, but lacks recommendation lifecycle binding, idempotent conversion protection, and frontend review-before-submit confirmation modal allowing adjustments (quantity, supplier, expected delivery date, notes).

---

## 3. Target Phase 6 Design Decisions & Invariants

1. **Tenant & Stock Safety Invariants (Non-Negotiable):**
   - Every intelligence query, persisted table, cache key, recommendation, evaluation, and simulation strictly filters by `business_id`.
   - Phase 6 NEVER mutates `Product.current_stock` or creates stock movements directly; accepted recommendations create **DRAFT Purchase Orders** strictly through `ProcurementService.create_purchase_order` only after user review & confirmation. Stock increases only upon `GoodsReceipt` creation.
2. **Schema Evolution via Alembic (`0002_phase6_intelligence.py`):**
   - Extend `products` cleanly with nullable/defaulted ordering policy metadata (`min_order_quantity`, `order_pack_size`, `max_stock_level`, `initial_daily_demand`, `review_period_days`, `service_level_target`) and add tenant-scoped intelligence persistence tables:
     - `product_forecasts` (champion model, horizon, serialized point/lower/upper forecast, data sufficiency tier, cutoff date, model version)
     - `model_evaluations` (chronological rolling-origin CV results per model & metric: MAE, RMSE, nullable MAPE, sMAPE, WAPE, MASE)
     - `replenishment_recommendations` (deduplicated per active SKU + category, persisted inventory snapshot, formula components, explanation text, status lifecycle, linked `purchase_order_id`, dismissal/acceptance metadata)
   - Cross-dialect compatibility (`SQLite` + `PostgreSQL 16+` / Supabase) enforced and tested identically to `0001_initial_schema.py`.
3. **Honest Forecasting & Classification Hierarchy:**
   - Demand sufficiency classification per SKU:
     - `NEW` (< 7 active/observed days or 0 completed sales -> Cold-Start strategy)
     - `LIMITED` (7–29 days -> Simple baselines only: Moving Average / WMA / SES / Naive)
     - `INTERMITTENT` (sparse non-zero demand with high ADI >= 1.32 or zero ratio >= 40% -> Croston / SBA / Moving Average)
     - `ESTABLISHED` (>= 30 days non-intermittent -> Baselines + ARIMA / RandomForest / XGBoost / SES)
     - `SEASONAL` (>= 60 days with weekly/calendar coverage -> Seasonal Naive + Prophet-style additive + ARIMA/ML candidates)
   - Champion selected strictly by out-of-sample rolling-origin CV WAPE/MAE against baselines; complex models never win unless they strictly beat simple baselines.
4. **Unified `/api/intelligence/*` Surface + Full Backward Compatibility:**
   - Introduce clean `/api/intelligence/*` endpoints for overview, forecasts, evaluations, recommendations lifecycle (`accept`, `dismiss`, `convert-to-po`), stockout risks, overstock risks, and supplier lead-time intelligence.
   - Upgrade internals of existing `/api/forecast/*`, `/api/decision/*`, `/api/simulator/*`, and `/api/analytics/*` so existing callers and test suites receive repaired, tenant-safe, non-crashing responses while preserving response keys.
5. **Frontend Integration Within Existing Design System:**
   - Preserve Inter + Noto Sans Devanagari typography, light/dark themes, existing Redux patterns, EN + HI translations, and add:
     - Dedicated **Intelligence Overview** page (`/intelligence`) + restrained actionable widget on `DashboardPage`,
     - Upgraded **`ForecastingPage`** (historical vs forecast separation, sufficiency/cold-start badges, evaluation comparison table, demand/stockout context),
     - Upgraded **`ReorderPlannerPage`** (persisted recommendation queue, explainability details, accept/dismiss, and mandatory **Review & Confirm PO Modal** before calling backend PO conversion),
     - Supplier lead-time performance & Overstock/Stockout risk visibility,
     - Optional SKU ordering constraints (`MOQ`, `Pack Size`, `Max Stock`, `Initial Daily Demand`) in `ProductFormModal`.
