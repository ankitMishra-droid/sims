# Forecast Evaluation & Model Selection Report — SIMS Phase 6

## 1. Chronological Rolling-Origin Cross-Validation
`ModelEvaluationService` replaces the prior single fixed train/test split with chronological expanding-window **rolling-origin validation** (`_build_rolling_folds`):
- History is ordered ascending by calendar date and capped for evaluation efficiency at the latest 240 daily observations (`ordered.tail(240)`).
- Up to **3 non-overlapping validation test horizons** (`fold_horizon = min(test_days, max(2, n // 5))`) are evaluated chronologically (`train_end < test_end <= n`), verifying minimum per-model training windows (`min_train_days`, e.g., 5–14d for baselines, 24–45d for statistical/ML models).
- Predictions across all evaluated folds are concatenated chronologically before computing aggregate metrics so every fold carries equal per-day weight.

---

## 2. Zero-Safe Accuracy Metrics (`BaseForecastingModel.evaluate`)
All negative model outputs are clipped at `0.0` before scoring (`y_pred = max(y_pred, 0.0)`):

| Metric | Formula | Zero-Demand Behavior |
| :--- | :--- | :--- |
| **MAE** | `mean(|y - yhat|)` | Always defined for `n >= 1`. |
| **RMSE** | `sqrt(mean((y - yhat)^2))` | Always defined for `n >= 1`. |
| **WAPE (%)** | `100 * sum(|y - yhat|) / sum(y)` | Primary ranking metric when `sum(y) > 0`; returns **`None`** when `sum(y) == 0`. |
| **MAPE (%)** | `100 * mean(|y - yhat| / y)` over `y > 0` | Evaluates positive days only; returns **`None`** if all actuals are `0` (never returns fake `0.0`). |
| **sMAPE (%)** | `100 * mean(|y - yhat| / ((|y| + |yhat|) / 2))` | Returns `0.0` only when both actual and prediction equal `0`. |
| **MASE** | `MAE / mean(|diff(y_train)|)` | Scale-free relative accuracy against 1-step in-sample naive error; returns `None` on constant training segments. |

---

## 3. Baseline-First Champion Promotion Policy
1. Candidates are ranked deterministically by `(WAPE, MAE, RMSE)`.
2. **`Naive` Benchmark Discipline:** `Naive` (last-value persistence) is evaluated across folds as a transparent reference benchmark (`[1-step persistence benchmark]`), preventing a random single zero day at cutoff from collapsing 30-day replenishment forecasts.
3. **Champion Selection:**
   - First, identify the best eligible multi-step baseline (`MovingAverage(14d)`, `WeightedMovingAverage(14d)`, `SimpleExponentialSmoothing`, `SeasonalNaive7D`, or `CrostonSBA`).
   - A complex ML/statistical model (`ARIMA(1,1,1)`, `AdditiveProphet`, `RandomForest`, `XGBoost`, `LSTMSequenceNetwork`) promotes to Champion **only** if it achieves **>= 2% relative WAPE improvement** (`comp_wape <= base_wape * 0.98`), or `>= 0.05` MAE improvement when WAPE is `None`.
   - Every decision emits an explicit human-readable `selection_reason` persisted in `product_forecasts` and `model_evaluations`.

---

## 4. Cold-Start & Insufficiency Reporting
- Products classified `NEW` skip rolling CV cleanly (`status="ACTIVE_COLD_START"`, `folds_evaluated=0`), setting `mae=rmse=mape=smape=wape=mase=None` instead of displaying fabricated accuracy percentages.
- Complex models gated out on `LIMITED` or `INTERMITTENT` tiers remain visible in the leaderboard with `status="SKIPPED_INSUFFICIENT_DATA"` and an explicit `notes` explanation.
