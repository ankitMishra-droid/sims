# Demand Forecasting Engine Design — SIMS Phase 6

## 1. Data Ingestion & Quality Pipeline
1. **Tenant & Status Filtering (`DataIngestionService.load_from_database`):**
   - Queries join `Sale` and `Product` with mandatory `Sale.business_id == Product.business_id == resolved_business_id`.
   - Excludes `Sale.status == "CANCELLED"` rows completely so reversed orders never inflate demand.
   - Enforces `Sale.sales_date <= as_of_date` (23:59:59 UTC) to prevent future leakage during backtesting.
2. **Continuous Calendar Construction (`DataPreprocessingService.prepare_daily_series`):**
   - Multiple transactions on the same UTC calendar day are summed (`raw_demand`).
   - Reindexed onto an unbroken daily grid bounded by `min(first_sale_day, max(product.created_at, cutoff - 730d))` through `as_of_date`. Extending to `as_of_date` ensures trailing zero-sale days on stagnant or slowing products reduce recent demand rather than appearing falsely active.
3. **Stockout-Day Awareness:**
   - Daily closing stock is mapped from `InventoryLog` (`load_stock_ledger_for_product`) and forward-filled across observed ledger spans; if current stock `== 0` at cutoff, cutoff zero demand is flagged.
   - Days where `raw_demand == 0` AND `closing_stock_known` AND `closing_stock <= 0` are marked `is_stockout_day = True` (tracking an informational `stockout_days_count` and excluding confirmed stockout-only periods from dragging down active daily demand rates). Free zero-demand days when stock was on hand (`closing_stock > 0`) are preserved as `0.0`.
4. **Conservative Outlier Winsorization:**
   - Triggered only when at least 14 positive-demand days exist; caps extreme bulk spikes above `max(min(Q75 + 3*IQR, median + 5*1.4826*MAD), 1.5*Q75)` into `demand`, preserving untouched `raw_demand` alongside it.
5. **Leak-Free Causal Features (`FeatureEngineeringService.create_features`):**
   - All lag features (`lag_1..lag_30`) and rolling statistics (`rolling_mean_{7,14,30}`, `rolling_std_{7,14,30}`) are derived strictly from `demand.shift(1)` (observations strictly `< t`). Early rows fill leading missing lags using the causal prior expanding mean (defaulting to `0.0` at `t=0`), never `bfill()`.

---

## 2. Data Sufficiency Classification

Each product is classified before candidate model selection (`DataPreprocessingService.analyze_demand_profile`):

| Tier | Criteria | Eligible Models | Rationale |
| :--- | :--- | :--- | :--- |
| **`NEW`** | `< 7` observed days or `0` non-zero sales days | `ColdStartEstimator` | Avoids spurious extrapolation or fabricated ML accuracy on near-empty data. |
| **`LIMITED`** | `7 <= days < 30` and `non_zero >= 1` | `MovingAverage(14d)`, `WeightedMovingAverage(14d)`, `SES`, `SeasonalNaive7D` (`>=14d`) (+ `Naive` benchmark) | Short histories cannot support high-variance tree/neural/ARIMA models reliably. |
| **`INTERMITTENT`** | `days >= 14` and (`ADI >= 1.32` or zero ratio `>= 40%`) | `CrostonSBA`, `MovingAverage(14d)`, `WeightedMovingAverage(14d)`, `SES`, `SeasonalNaive7D` | Standard Syntetos-Boylan (`ADI >= 1.32`) separation for lumpy/sparse SKUs. |
| **`ESTABLISHED`** | `30 <= days < 56` (non-intermittent) | All baselines + `ARIMA(1,1,1)`, `AdditiveProphet`, `RandomForest`, `XGBoost` | Sufficient sample size for lagged & trend models to compete against baselines. |
| **`SEASONAL`** | `days >= 56` and `non_zero >= 20` (non-intermittent) | All baselines + `ARIMA`, `AdditiveProphet`, `RandomForest`, `XGBoost`, vectorized `LSTMSequenceNetwork` | Full weekly & multi-month patterns allow recurrent/Fourier seasonal models. |

---

## 3. Model Portfolio & Cold-Start Protocol
- **Cold Start (`ColdStartForecaster`):** Uses optional `Product.initial_daily_demand` if entered by the workspace owner/manager; otherwise predicts observed daily mean (or honest `0.0` for `0` historical sales) with wide uncertainty (`0.75 * rate`) and marks `is_cold_start = True`. Cross-tenant data is never used.
- **Baselines (`backend/app/ml/models/baseline_models.py`):**
  - `Naive` (marked `benchmark_only=True` in CV so single-day trailing zero noise cannot collapse multi-week replenishment forecasts to zero),
  - `SeasonalNaive7D` (day-of-week averages over recent 4 weeks),
  - `MovingAverage(14d)`,
  - `WeightedMovingAverage(14d)`,
  - `SimpleExponentialSmoothing` (alpha tuned via 1-step in-sample RMSE over `{0.1, 0.2, 0.3, 0.5, 0.7}`),
  - `CrostonSBA` (Syntetos-Boylan bias-adjusted intermittent demand rate).
- **Statistical & ML Models:**
  - `ARIMAForecaster` (with variance/length guard and constant fallback),
  - `ProphetForecaster` (Ridge Fourier weekly + monthly harmonics),
  - `RandomForestForecaster` & `XGBoostForecaster` (using fast O(horizon) array feature stepping for multi-step recursion),
  - `LSTMForecaster` (vectorized NumPy mini-batch recurrent cell over latest 240 days).

---

## 4. Persistence & Cache Invalidation
Forecast snapshots (`product_forecasts`) are keyed uniquely on `(business_id, product_id, horizon_days)` along with `model_version` (`phase6-v1`), `data_cutoff_date`, `_sale_count`, and `_initial_daily_demand`. Subsequent requests return immediately from PostgreSQL/SQLite without retraining unless:
1. A new day begins (`data_cutoff_date < today`),
2. New/cancelled sales modify `_sale_count` or latest sale timestamp,
3. `initial_daily_demand` is edited on the product, or
4. `force_refresh=True` or `/api/intelligence/forecasts/refresh` is invoked.
