from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Type

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..models.intelligence import ModelEvaluation
from .base_model import BaseForecastingModel
from .models import (
    ARIMAForecaster,
    ColdStartForecaster,
    CrostonSBAForecaster,
    LSTMForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    ProphetForecaster,
    RandomForestForecaster,
    SeasonalNaiveForecaster,
    SimpleExponentialSmoothingForecaster,
    WeightedMovingAverageForecaster,
    XGBoostForecaster,
)

logger = logging.getLogger("sims.ml.evaluation")

MODEL_VERSION = "ml-v2"

PRIMARY_DISPLAY_MAP: Dict[str, str] = {
    "ARIMA(1, 1, 1)": "ARIMA",
    "XGBoost": "XGBoost",
    "RandomForest": "Random Forest",
    "LSTMSequenceNetwork": "LSTM",
}

PRIMARY_ROSTER_ORDER = ["ARIMA", "XGBoost", "Random Forest", "LSTM"]


class ModelEvaluationService:
    """
    Chronological rolling-origin / walk-forward cross-validation benchmark.
    Computes 6+ zero-safe held-out metrics (MAE, MSE, RMSE, MAPE, WAPE, Bias + sMAPE/MASE),
    evaluates candidate eligibility strictly without future leakage, guards champion selection
    against severe systematic forecast bias, and preserves internal baseline & experimental models.
    """

    MAX_BIAS_PCT_GUARD = 35.0

    @staticmethod
    def _candidate_specs(data_sufficiency: str) -> List[Dict[str, Any]]:
        """
        Define candidate model roster with eligibility thresholds.
        Only the 4 primary algorithms carry is_primary=True for user-facing reporting;
        internal baselines and experimental Prophet remain active for safe fallback & benchmarking.
        """
        specs: List[Dict[str, Any]] = [
            {
                "name": "Naive",
                "display_name": "Naive Persistence",
                "cls": NaiveForecaster,
                "kwargs": {},
                "is_baseline": True,
                "is_primary": False,
                "benchmark_only": True,
                "eligible_tiers": {"LIMITED", "INTERMITTENT", "ESTABLISHED", "SEASONAL"},
                "min_train_days": 5,
            },
            {
                "name": "SeasonalNaive7D",
                "display_name": "Seasonal Naive Baseline",
                "cls": SeasonalNaiveForecaster,
                "kwargs": {"season_length": 7},
                "is_baseline": True,
                "is_primary": False,
                "eligible_tiers": {"LIMITED", "INTERMITTENT", "ESTABLISHED", "SEASONAL"},
                "min_train_days": 14,
            },
            {
                "name": "MovingAverage(14d)",
                "display_name": "Moving Average Baseline",
                "cls": MovingAverageForecaster,
                "kwargs": {"window": 14},
                "is_baseline": True,
                "is_primary": False,
                "eligible_tiers": {"LIMITED", "INTERMITTENT", "ESTABLISHED", "SEASONAL"},
                "min_train_days": 7,
            },
            {
                "name": "WeightedMovingAverage(14d)",
                "display_name": "Weighted Moving Average Baseline",
                "cls": WeightedMovingAverageForecaster,
                "kwargs": {"window": 14},
                "is_baseline": True,
                "is_primary": False,
                "eligible_tiers": {"LIMITED", "INTERMITTENT", "ESTABLISHED", "SEASONAL"},
                "min_train_days": 7,
            },
            {
                "name": "SimpleExponentialSmoothing",
                "display_name": "Exponential Smoothing Baseline",
                "cls": SimpleExponentialSmoothingForecaster,
                "kwargs": {},
                "is_baseline": True,
                "is_primary": False,
                "eligible_tiers": {"LIMITED", "INTERMITTENT", "ESTABLISHED", "SEASONAL"},
                "min_train_days": 7,
            },
            {
                "name": "CrostonSBA",
                "display_name": "Croston SBA Baseline",
                "cls": CrostonSBAForecaster,
                "kwargs": {"alpha": 0.15},
                "is_baseline": True,
                "is_primary": False,
                "eligible_tiers": {"INTERMITTENT", "ESTABLISHED", "SEASONAL"},
                "min_train_days": 14,
            },
            {
                "name": "AdditiveProphet",
                "display_name": "Additive Trend (Internal)",
                "cls": ProphetForecaster,
                "kwargs": {},
                "is_baseline": False,
                "is_primary": False,
                "internal_only": True,
                "eligible_tiers": {"ESTABLISHED", "SEASONAL"},
                "min_train_days": 28,
            },
            {
                "name": "ARIMA(1, 1, 1)",
                "display_name": "ARIMA",
                "cls": ARIMAForecaster,
                "kwargs": {"order": (1, 1, 1)},
                "is_baseline": False,
                "is_primary": True,
                "eligible_tiers": {"ESTABLISHED", "SEASONAL", "INTERMITTENT"},
                "min_train_days": 24,
            },
            {
                "name": "RandomForest",
                "display_name": "Random Forest",
                "cls": RandomForestForecaster,
                "kwargs": {"n_estimators": 60, "max_depth": 6},
                "is_baseline": False,
                "is_primary": True,
                "eligible_tiers": {"ESTABLISHED", "SEASONAL", "INTERMITTENT"},
                "min_train_days": 28,
            },
            {
                "name": "XGBoost",
                "display_name": "XGBoost",
                "cls": XGBoostForecaster,
                "kwargs": {"n_estimators": 60, "learning_rate": 0.08, "max_depth": 4},
                "is_baseline": False,
                "is_primary": True,
                "eligible_tiers": {"ESTABLISHED", "SEASONAL", "INTERMITTENT"},
                "min_train_days": 28,
            },
            {
                "name": "LSTMSequenceNetwork",
                "display_name": "LSTM",
                "cls": LSTMForecaster,
                "kwargs": {"sequence_length": 14, "hidden_units": 16, "epochs": 30},
                "is_baseline": False,
                "is_primary": True,
                "eligible_tiers": {"SEASONAL", "ESTABLISHED"},
                "min_train_days": 60,
            },
        ]
        return specs

    @staticmethod
    def _build_rolling_folds(
        n_obs: int,
        test_days: Optional[int] = None,
        max_folds: int = 3,
    ) -> List[tuple[int, int]]:
        """
        Return chronological (train_end_idx, test_end_idx) slices for expanding-window CV.
        Strictly guarantees train_end < test_end <= n_obs and chronological ordering.
        """
        if n_obs < 8:
            return []

        fold_horizon = min(test_days or 14, max(2, n_obs // 5))
        fold_horizon = max(2, min(fold_horizon, n_obs - 5))

        folds: List[tuple[int, int]] = []
        step = max(2, fold_horizon)
        for k in range(max_folds):
            test_end = n_obs - k * step
            train_end = test_end - fold_horizon
            if train_end < 5:
                break
            folds.append((train_end, test_end))

        folds.reverse()
        return folds

    @staticmethod
    def _has_severe_bias(row: Dict[str, Any]) -> bool:
        bias = row.get("bias")
        bias_pct = row.get("bias_pct")
        mae = row.get("mae")
        if bias_pct is not None and abs(float(bias_pct)) > ModelEvaluationService.MAX_BIAS_PCT_GUARD:
            return True
        if bias is not None and mae is not None and float(mae) > 0.1 and abs(float(bias)) > 1.5 * float(mae):
            return True
        return False

    @classmethod
    def _score_key(cls, row: Dict[str, Any]) -> tuple[int, float, float, float, float, float]:
        """
        Deterministic minimization sort key implementing Champion Policy:
        1. Severe systematic bias guard (0 ok, 1 penalized)
        2. Primary metric: WAPE (fallback to MAE if WAPE is None)
        3. MAE
        4. RMSE
        5. Absolute bias
        6. Cross-fold stability dispersion
        """
        severe_bias = 1 if cls._has_severe_bias(row) else 0
        wape = row.get("wape")
        mae = row.get("mae")
        rmse = row.get("rmse")
        bias = abs(float(row.get("bias"))) if row.get("bias") is not None else float("inf")
        stability = float(row.get("stability_score")) if row.get("stability_score") is not None else 0.0
        primary = float(wape) if wape is not None else (float(mae) if mae is not None else float("inf"))
        sec = float(mae) if mae is not None else float("inf")
        ter = float(rmse) if rmse is not None else float("inf")
        return (severe_bias, primary, sec, ter, bias, stability)

    @staticmethod
    def _empty_metrics_fields() -> Dict[str, Any]:
        return {
            "mae": None,
            "mse": None,
            "rmse": None,
            "mape": None,
            "smape": None,
            "wape": None,
            "mase": None,
            "bias": None,
            "bias_pct": None,
            "bias_direction": None,
            "stability_score": None,
            "zero_actuals_ratio": None,
            "mape_limitation_note": None,
        }

    @classmethod
    def evaluate_all_models(
        cls,
        daily_df: pd.DataFrame,
        target_col: str = "demand",
        test_days: int = 14,
        *,
        data_sufficiency: str = "ESTABLISHED",
        initial_daily_demand: Optional[float] = None,
        category_benchmark: Optional[Dict[str, Any]] = None,
        generalized_baseline: Optional[Dict[str, Any]] = None,
        horizon_days: int = 30,
        dataset_version: Optional[str] = None,
        max_folds: int = 3,
    ) -> Dict[str, Any]:
        """
        Run chronological rolling-origin cross-validation across eligible baselines
        and primary ML models, compute all 6+ metrics & dates, apply bias-aware
        champion promotion, and return full + 4-model primary comparison leaderboards.
        """
        ordered = (
            daily_df.sort_values("date").tail(3653).reset_index(drop=True)
            if daily_df is not None and not daily_df.empty
            else pd.DataFrame()
        )
        n_obs = len(ordered)

        train_start_str = pd.Timestamp(ordered["date"].iloc[0]).strftime("%Y-%m-%d") if n_obs > 0 else None
        train_end_str = pd.Timestamp(ordered["date"].iloc[-1]).strftime("%Y-%m-%d") if n_obs > 0 else None

        if data_sufficiency in {"NEW", "DISCONTINUED"} or n_obs < 8:
            reason = (
                f"Product marked inactive/discontinued with {n_obs} historical day(s); using baseline fallback."
                if data_sufficiency == "DISCONTINUED"
                else (
                    f"Cold-start protocol activated (sufficiency={data_sufficiency}, "
                    f"observed_days={n_obs} < 8 min rolling validation window)."
                )
            )
            primary_rows = [
                {
                    "model_name": internal_name,
                    "display_name": PRIMARY_DISPLAY_MAP[internal_name],
                    "is_primary_model": True,
                    "is_baseline": False,
                    "is_champion": False,
                    "status": "SKIPPED_INSUFFICIENT_DATA",
                    "eligibility_reason": reason,
                    "folds_evaluated": 0,
                    "train_window_days": n_obs,
                    "test_window_days": 0,
                    "forecast_horizon_days": horizon_days,
                    "observations_count": 0,
                    "training_start_date": train_start_str,
                    "training_end_date": train_end_str,
                    "backtest_start_date": None,
                    "backtest_end_date": None,
                    "model_version": MODEL_VERSION,
                    "dataset_version": dataset_version,
                    **cls._empty_metrics_fields(),
                    "training_time_seconds": 0.0,
                    "notes": reason,
                }
                for internal_name in ("ARIMA(1, 1, 1)", "XGBoost", "RandomForest", "LSTMSequenceNetwork")
            ]
            cold_inst = ColdStartForecaster(
                initial_daily_demand=initial_daily_demand,
                category_benchmark=category_benchmark,
                generalized_baseline=generalized_baseline,
            )
            cold_row = {
                "model_name": "ColdStartEstimator",
                "display_name": "Baseline (Insufficient Data)",
                "is_primary_model": False,
                "is_baseline": True,
                "is_champion": True,
                "status": "ACTIVE_COLD_START",
                "eligibility_reason": reason,
                "folds_evaluated": 0,
                "train_window_days": n_obs,
                "test_window_days": 0,
                "forecast_horizon_days": horizon_days,
                "observations_count": 0,
                "training_start_date": train_start_str,
                "training_end_date": train_end_str,
                "backtest_start_date": None,
                "backtest_end_date": None,
                "model_version": MODEL_VERSION,
                "dataset_version": dataset_version,
                **cls._empty_metrics_fields(),
                "training_time_seconds": 0.0,
                "notes": "Insufficient historical observations for out-of-sample cross-validation.",
            }
            return {
                "champion_model": "ColdStartEstimator",
                "champion_display_name": "Baseline (Insufficient Data)",
                "champion_is_ml": False,
                "fallback_used": True,
                "champion_instance": cold_inst,
                "selection_reason": reason,
                "evaluation_strategy": "cold_start",
                "folds_evaluated": 0,
                "train_days": n_obs,
                "test_days": 0,
                "training_start_date": train_start_str,
                "training_end_date": train_end_str,
                "backtest_start_date": None,
                "backtest_end_date": None,
                "leaderboard": [cold_row] + primary_rows,
                "primary_leaderboard": primary_rows,
                "backtest_comparison": [],
                "failed_models": [],
            }

        folds = cls._build_rolling_folds(n_obs, test_days=min(test_days, 14), max_folds=max_folds)
        # Common primary evaluation window (latest shared folds usable across models where applicable)
        specs = cls._candidate_specs(data_sufficiency)
        scorer = NaiveForecaster()

        leaderboard: List[Dict[str, Any]] = []
        failed_models: List[Dict[str, str]] = []
        backtest_series_by_model: Dict[str, List[Dict[str, Any]]] = {}

        for spec in specs:
            name = spec["name"]
            display_name = spec.get("display_name") or PRIMARY_DISPLAY_MAP.get(name, name)
            is_baseline = bool(spec["is_baseline"])
            is_primary = bool(spec.get("is_primary", False))
            min_train = int(spec["min_train_days"])
            internal_only = bool(spec.get("internal_only", False))

            if data_sufficiency not in spec["eligible_tiers"]:
                skip_msg = f"Ineligible for sufficiency tier '{data_sufficiency}' (requires {sorted(spec['eligible_tiers'])})."
                leaderboard.append(
                    {
                        "model_name": name,
                        "display_name": display_name,
                        "is_primary_model": is_primary,
                        "is_baseline": is_baseline,
                        "is_champion": False,
                        "status": "SKIPPED_INSUFFICIENT_DATA",
                        "eligibility_reason": skip_msg,
                        "folds_evaluated": 0,
                        "train_window_days": 0,
                        "test_window_days": 0,
                        "forecast_horizon_days": horizon_days,
                        "observations_count": 0,
                        "training_start_date": train_start_str,
                        "training_end_date": train_end_str,
                        "backtest_start_date": None,
                        "backtest_end_date": None,
                        "model_version": MODEL_VERSION,
                        "dataset_version": dataset_version,
                        **cls._empty_metrics_fields(),
                        "training_time_seconds": 0.0,
                        "notes": skip_msg,
                        "internal_only": internal_only,
                    }
                )
                continue

            eligible_folds = [(tr_end, te_end) for tr_end, te_end in folds if tr_end >= min_train]
            if not eligible_folds:
                skip_msg = f"Requires >= {min_train} training days before first validation fold (observed={n_obs})."
                leaderboard.append(
                    {
                        "model_name": name,
                        "display_name": display_name,
                        "is_primary_model": is_primary,
                        "is_baseline": is_baseline,
                        "is_champion": False,
                        "status": "SKIPPED_INSUFFICIENT_DATA",
                        "eligibility_reason": skip_msg,
                        "folds_evaluated": 0,
                        "train_window_days": 0,
                        "test_window_days": 0,
                        "forecast_horizon_days": horizon_days,
                        "observations_count": 0,
                        "training_start_date": train_start_str,
                        "training_end_date": train_end_str,
                        "backtest_start_date": None,
                        "backtest_end_date": None,
                        "model_version": MODEL_VERSION,
                        "dataset_version": dataset_version,
                        **cls._empty_metrics_fields(),
                        "training_time_seconds": 0.0,
                        "notes": skip_msg,
                        "internal_only": internal_only,
                    }
                )
                continue

            # Run explicit model-level eligibility check on deepest training window prior to fitting
            deepest_tr_end = eligible_folds[-1][0]
            deepest_train_slice = ordered.iloc[:deepest_tr_end]
            model_cls: Type[BaseForecastingModel] = spec["cls"]
            is_elig, elig_reason = model_cls.check_eligibility(deepest_train_slice)
            if not is_elig:
                leaderboard.append(
                    {
                        "model_name": name,
                        "display_name": display_name,
                        "is_primary_model": is_primary,
                        "is_baseline": is_baseline,
                        "is_champion": False,
                        "status": "SKIPPED_INSUFFICIENT_DATA",
                        "eligibility_reason": elig_reason,
                        "folds_evaluated": 0,
                        "train_window_days": deepest_tr_end,
                        "test_window_days": 0,
                        "forecast_horizon_days": horizon_days,
                        "observations_count": 0,
                        "training_start_date": train_start_str,
                        "training_end_date": pd.Timestamp(deepest_train_slice["date"].iloc[-1]).strftime("%Y-%m-%d"),
                        "backtest_start_date": None,
                        "backtest_end_date": None,
                        "model_version": MODEL_VERSION,
                        "dataset_version": dataset_version,
                        **cls._empty_metrics_fields(),
                        "training_time_seconds": 0.0,
                        "notes": elig_reason,
                        "internal_only": internal_only,
                    }
                )
                continue

            fold_actuals: List[np.ndarray] = []
            fold_preds: List[np.ndarray] = []
            fold_maes: List[float] = []
            total_train_secs = 0.0
            last_train_arr = None
            eval_error: Optional[str] = None
            latest_fold_points: List[Dict[str, Any]] = []

            for f_idx, (tr_end, te_end) in enumerate(eligible_folds):
                train_slice = ordered.iloc[:tr_end].copy()
                test_slice = ordered.iloc[tr_end:te_end].copy()
                horizon = len(test_slice)
                try:
                    model_inst: BaseForecastingModel = spec["cls"](**spec["kwargs"])
                    model_inst.fit(train_slice, target_col=target_col)
                    pred_dict = model_inst.predict(horizon_days=horizon)
                    total_train_secs += float(model_inst.training_time_seconds or 0.0)
                    act_arr = np.asarray(test_slice[target_col].to_numpy(dtype=np.float64), dtype=np.float64)
                    pred_arr = np.asarray(pred_dict["predictions"], dtype=np.float64)
                    fold_actuals.append(act_arr)
                    fold_preds.append(pred_arr)
                    fold_maes.append(float(np.mean(np.abs(act_arr - pred_arr))))
                    last_train_arr = np.asarray(train_slice[target_col].to_numpy(dtype=np.float64), dtype=np.float64)
                    if f_idx == len(eligible_folds) - 1:
                        latest_fold_points = [
                            {
                                "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                                "actual": round(float(a), 2),
                                "predicted": round(float(p), 2),
                            }
                            for dt, a, p in zip(test_slice["date"].tolist(), act_arr.tolist(), pred_arr.tolist())
                        ]
                except Exception as exc:
                    eval_error = str(exc)
                    logger.warning("Evaluation error for model=%s: %s", name, exc)
                    break

            fold_tr_start = pd.Timestamp(ordered["date"].iloc[0]).strftime("%Y-%m-%d")
            fold_tr_end = pd.Timestamp(ordered["date"].iloc[eligible_folds[-1][0] - 1]).strftime("%Y-%m-%d")
            fold_te_start = pd.Timestamp(ordered["date"].iloc[eligible_folds[0][0]]).strftime("%Y-%m-%d")
            fold_te_end = pd.Timestamp(ordered["date"].iloc[eligible_folds[-1][1] - 1]).strftime("%Y-%m-%d")

            if eval_error is not None or not fold_actuals:
                failed_models.append({"model_name": display_name, "error": eval_error or "No valid folds"})
                leaderboard.append(
                    {
                        "model_name": name,
                        "display_name": display_name,
                        "is_primary_model": is_primary,
                        "is_baseline": is_baseline,
                        "is_champion": False,
                        "status": "FAILED",
                        "eligibility_reason": f"Evaluation failed: {eval_error or 'No valid folds'}",
                        "folds_evaluated": 0,
                        "train_window_days": eligible_folds[-1][0],
                        "test_window_days": eligible_folds[-1][1] - eligible_folds[-1][0],
                        "forecast_horizon_days": horizon_days,
                        "observations_count": 0,
                        "training_start_date": fold_tr_start,
                        "training_end_date": fold_tr_end,
                        "backtest_start_date": fold_te_start,
                        "backtest_end_date": fold_te_end,
                        "model_version": MODEL_VERSION,
                        "dataset_version": dataset_version,
                        **cls._empty_metrics_fields(),
                        "training_time_seconds": round(total_train_secs, 3),
                        "notes": eval_error or "Evaluation failed",
                        "internal_only": internal_only,
                    }
                )
                continue

            y_all_true = np.concatenate(fold_actuals)
            y_all_pred = np.concatenate(fold_preds)
            agg_metrics = scorer.evaluate(y_all_true, y_all_pred, y_train=last_train_arr)
            stability = round(float(np.std(fold_maes)), 4) if len(fold_maes) > 1 else 0.0
            agg_metrics["stability_score"] = stability

            backtest_series_by_model[name] = latest_fold_points
            leaderboard.append(
                {
                    "model_name": name,
                    "display_name": display_name,
                    "is_primary_model": is_primary,
                    "is_baseline": is_baseline,
                    "is_champion": False,
                    "status": "EVALUATED",
                    "eligibility_reason": elig_reason,
                    "folds_evaluated": len(fold_actuals),
                    "train_window_days": eligible_folds[-1][0],
                    "test_window_days": eligible_folds[-1][1] - eligible_folds[-1][0],
                    "forecast_horizon_days": horizon_days,
                    "observations_count": len(y_all_true),
                    "training_start_date": fold_tr_start,
                    "training_end_date": fold_tr_end,
                    "backtest_start_date": fold_te_start,
                    "backtest_end_date": fold_te_end,
                    "model_version": MODEL_VERSION,
                    "dataset_version": dataset_version,
                    **agg_metrics,
                    "training_time_seconds": round(total_train_secs, 3),
                    "notes": f"Rolling-origin CV ({len(fold_actuals)} fold(s), {len(y_all_true)} held-out days)."
                    + (" [1-step persistence benchmark]" if spec.get("benchmark_only") else ""),
                    "benchmark_only": bool(spec.get("benchmark_only", False)),
                    "internal_only": internal_only,
                    "_spec": spec,
                }
            )

        evaluated_rows = [r for r in leaderboard if r["status"] == "EVALUATED"]
        evaluated_rows.sort(key=cls._score_key)

        selectable_rows = [
            r for r in evaluated_rows if not r.get("benchmark_only", False) and not r.get("internal_only", False)
        ]
        if not selectable_rows:
            selectable_rows = [r for r in evaluated_rows if not r.get("internal_only", False)] or evaluated_rows

        if not evaluated_rows:
            fallback_inst = MovingAverageForecaster(window=7)
            return {
                "champion_model": fallback_inst.model_name,
                "champion_display_name": "Moving Average Baseline",
                "champion_is_ml": False,
                "fallback_used": True,
                "champion_instance": fallback_inst,
                "selection_reason": "Fallback baseline MovingAverage(7d): insufficient historical evidence for rolling CV across candidates.",
                "evaluation_strategy": "rolling_origin",
                "folds_evaluated": len(folds),
                "train_days": folds[-1][0] if folds else n_obs,
                "test_days": (folds[-1][1] - folds[-1][0]) if folds else 0,
                "training_start_date": train_start_str,
                "training_end_date": train_end_str,
                "backtest_start_date": None,
                "backtest_end_date": None,
                "leaderboard": [
                    {k: v for k, v in r.items() if k not in ("_spec", "benchmark_only", "internal_only")}
                    for r in leaderboard
                ],
                "primary_leaderboard": [
                    {k: v for k, v in r.items() if k not in ("_spec", "benchmark_only", "internal_only")}
                    for r in leaderboard
                    if r.get("is_primary_model")
                ],
                "backtest_comparison": [],
                "failed_models": failed_models,
            }

        # Baseline-first & Bias-guarded Champion Selection:
        # An eligible primary ML model promotes over baselines only if it does not violate the severe bias guard
        # and improves out-of-sample error cleanly against the best selectable baseline.
        baselines = [r for r in selectable_rows if r["is_baseline"]]
        primary_ml = [r for r in selectable_rows if r.get("is_primary_model")]

        best_baseline = baselines[0] if baselines else selectable_rows[0]
        champion_row = best_baseline
        fallback_used = bool(best_baseline["is_baseline"])
        selection_reason = (
            f"Baseline {best_baseline['display_name']} retained (insufficient historical data or error advantage for primary ML models; "
            f"WAPE={best_baseline.get('wape')}, MAE={best_baseline.get('mae')}, Bias={best_baseline.get('bias')})."
        )

        if primary_ml:
            unbiased_ml = [r for r in primary_ml if not cls._has_severe_bias(r)]
            best_ml = unbiased_ml[0] if unbiased_ml else primary_ml[0]
            base_wape = best_baseline.get("wape")
            comp_wape = best_ml.get("wape")
            base_mae = best_baseline.get("mae") or 0.0
            comp_mae = best_ml.get("mae") or 0.0

            promoted = False
            if not cls._has_severe_bias(best_ml):
                if not best_baseline["is_baseline"]:
                    promoted = True
                elif base_wape is not None and comp_wape is not None:
                    if base_wape > 0 and comp_wape <= base_wape * 0.98:
                        promoted = True
                elif comp_mae <= base_mae - 0.05:
                    promoted = True
            else:
                selection_reason = (
                    f"Baseline {best_baseline['display_name']} retained because top ML challenger {best_ml['display_name']} "
                    f"exhibited systematic bias ({best_ml.get('bias')}, {best_ml.get('bias_direction')})."
                )

            if promoted:
                champion_row = best_ml
                fallback_used = False
                selection_reason = (
                    f"{best_ml['display_name']} selected as champion over {best_baseline['display_name']} "
                    f"(WAPE {comp_wape}% vs {base_wape}%, MAE {comp_mae} vs {base_mae}, RMSE {best_ml.get('rmse')}, Bias {best_ml.get('bias')})."
                )
            elif best_ml["model_name"] != best_baseline["model_name"] and not cls._has_severe_bias(best_ml):
                selection_reason = (
                    f"Baseline {best_baseline['display_name']} retained over {best_ml['display_name']} "
                    f"(did not exceed >=2% out-of-sample error reduction; WAPE {best_baseline.get('wape')}% vs {comp_wape}%, "
                    f"MAE {base_mae} vs {comp_mae})."
                )

        champion_spec = champion_row["_spec"]
        champion_instance: BaseForecastingModel = champion_spec["cls"](**champion_spec["kwargs"])
        champion_row["is_champion"] = True

        skipped_or_failed = [r for r in leaderboard if r["status"] != "EVALUATED"]
        ordered_board = [
            {k: v for k, v in r.items() if k not in ("_spec", "benchmark_only", "internal_only")}
            for r in (evaluated_rows + skipped_or_failed)
        ]

        # Primary 4-algorithm view in canonical UI order (ARIMA, XGBoost, Random Forest, LSTM)
        primary_by_display = {r["display_name"]: r for r in ordered_board if r.get("is_primary_model")}
        primary_leaderboard = [primary_by_display[name] for name in PRIMARY_ROSTER_ORDER if name in primary_by_display]

        return {
            "champion_model": champion_row["model_name"],
            "champion_display_name": champion_row["display_name"],
            "champion_is_ml": not champion_row["is_baseline"],
            "fallback_used": fallback_used,
            "champion_instance": champion_instance,
            "selection_reason": selection_reason,
            "evaluation_strategy": "rolling_origin",
            "folds_evaluated": champion_row["folds_evaluated"],
            "train_days": champion_row["train_window_days"],
            "test_days": champion_row["test_window_days"],
            "training_start_date": champion_row.get("training_start_date") or train_start_str,
            "training_end_date": champion_row.get("training_end_date") or train_end_str,
            "backtest_start_date": champion_row.get("backtest_start_date"),
            "backtest_end_date": champion_row.get("backtest_end_date"),
            "leaderboard": ordered_board,
            "primary_leaderboard": primary_leaderboard,
            "backtest_comparison": backtest_series_by_model.get(champion_row["model_name"], []),
            "failed_models": failed_models,
        }

    @staticmethod
    def build_model_by_name(
        model_choice: str,
        initial_daily_demand: Optional[float] = None,
        category_benchmark: Optional[Dict[str, Any]] = None,
        generalized_baseline: Optional[Dict[str, Any]] = None,
    ) -> Optional[BaseForecastingModel]:
        """Resolve an explicit manual model override safely (preserving internal & primary names)."""
        norm = (model_choice or "").strip().lower().replace(" ", "_")
        mapping: Dict[str, tuple[Type[BaseForecastingModel], dict]] = {
            "naive": (NaiveForecaster, {}),
            "seasonal_naive": (SeasonalNaiveForecaster, {"season_length": 7}),
            "moving_average": (MovingAverageForecaster, {"window": 14}),
            "weighted_moving_average": (WeightedMovingAverageForecaster, {"window": 14}),
            "ses": (SimpleExponentialSmoothingForecaster, {}),
            "croston": (CrostonSBAForecaster, {"alpha": 0.15}),
            "cold_start": (
                ColdStartForecaster,
                {
                    "initial_daily_demand": initial_daily_demand,
                    "category_benchmark": category_benchmark,
                    "generalized_baseline": generalized_baseline,
                },
            ),
            "arima": (ARIMAForecaster, {"order": (1, 1, 1)}),
            "arima(1,_1,_1)": (ARIMAForecaster, {"order": (1, 1, 1)}),
            "prophet": (ProphetForecaster, {}),
            "random_forest": (RandomForestForecaster, {"n_estimators": 60, "max_depth": 6}),
            "randomforest": (RandomForestForecaster, {"n_estimators": 60, "max_depth": 6}),
            "xgboost": (XGBoostForecaster, {"n_estimators": 60, "learning_rate": 0.08, "max_depth": 4}),
            "lstm": (LSTMForecaster, {"sequence_length": 14, "hidden_units": 16, "epochs": 30}),
            "lstmsequencenetwork": (LSTMForecaster, {"sequence_length": 14, "hidden_units": 16, "epochs": 30}),
        }
        entry = mapping.get(norm)
        if not entry:
            return None
        cls_, kwargs = entry
        return cls_(**kwargs)

    @staticmethod
    def _parse_date_str(val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.strptime(val[:10], "%Y-%m-%d")
        except ValueError:
            return None

    @classmethod
    def persist_evaluations(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
        cutoff_dt: datetime,
        eval_report: Dict[str, Any],
        *,
        horizon_days: int = 30,
        dataset_version: Optional[str] = None,
    ) -> None:
        """Persist latest rolling-origin CV leaderboard cleanly inside tenant scope."""
        (
            db.query(ModelEvaluation)
            .filter(
                ModelEvaluation.business_id == business_id,
                ModelEvaluation.product_id == product_id,
            )
            .delete(synchronize_session=False)
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for row in eval_report.get("leaderboard", []):
            rec = ModelEvaluation(
                business_id=business_id,
                product_id=product_id,
                model_name=str(row["model_name"]),
                display_name=str(row.get("display_name") or PRIMARY_DISPLAY_MAP.get(str(row["model_name"]), str(row["model_name"]))),
                is_baseline=bool(row.get("is_baseline", True)),
                is_champion=bool(row.get("is_champion", False)),
                evaluation_strategy=str(eval_report.get("evaluation_strategy", "rolling_origin")),
                folds_evaluated=int(row.get("folds_evaluated") or 0),
                train_window_days=int(row.get("train_window_days") or 0),
                test_window_days=int(row.get("test_window_days") or 0),
                forecast_horizon_days=int(row.get("forecast_horizon_days") or horizon_days),
                observations_count=int(row.get("observations_count") or 0),
                data_cutoff_date=cutoff_dt,
                training_start_date=cls._parse_date_str(row.get("training_start_date")),
                training_end_date=cls._parse_date_str(row.get("training_end_date")),
                backtest_start_date=cls._parse_date_str(row.get("backtest_start_date")),
                backtest_end_date=cls._parse_date_str(row.get("backtest_end_date")),
                mae=row.get("mae"),
                mse=row.get("mse"),
                rmse=row.get("rmse"),
                mape=row.get("mape"),
                smape=row.get("smape"),
                wape=row.get("wape"),
                mase=row.get("mase"),
                bias=row.get("bias"),
                stability_score=row.get("stability_score"),
                model_version=str(row.get("model_version") or MODEL_VERSION),
                dataset_version=row.get("dataset_version") or dataset_version,
                training_time_seconds=float(row.get("training_time_seconds") or 0.0),
                status=str(row.get("status") or "EVALUATED"),
                eligibility_reason=row.get("eligibility_reason"),
                notes=row.get("notes"),
                trained_at=now if row.get("status") == "EVALUATED" else None,
                evaluated_at=now,
            )
            db.add(rec)
        db.flush()
