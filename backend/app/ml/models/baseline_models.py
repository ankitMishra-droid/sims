import math
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..base_model import BaseForecastingModel


def _future_dates(last_date: pd.Timestamp, horizon_days: int) -> List[str]:
    return [
        (last_date + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d")
        for i in range(horizon_days)
    ]


def _numeric_list(series: pd.Series) -> List[float]:
    return [float(x) for x in pd.to_numeric(series, errors="coerce").fillna(0.0).tolist()]


def _numeric_array(series: pd.Series) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(_numeric_list(series), dtype=np.float64)


def _std_float(values: List[float], ddof: int = 0) -> float:
    n = len(values)
    if n <= ddof:
        return 0.0
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - ddof)
    return math.sqrt(max(0.0, var))


class NaiveForecaster(BaseForecastingModel):
    """Last-observation baseline: y_hat(t+h) = y(t)."""

    is_baseline = True

    def __init__(self):
        super().__init__(model_name="Naive")
        self.last_value_: float = 0.0
        self.residual_std_: float = 0.0

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date")
        self.last_date = pd.Timestamp(df["date"].max())
        vals = _numeric_array(df[target_col])
        self.last_value_ = float(max(float(vals[-1]), 0.0)) if len(vals) > 0 else 0.0
        if len(vals) >= 2:
            diffs = np.diff(vals)
            self.residual_std_ = float(np.std(diffs))
        else:
            self.residual_std_ = max(self.last_value_ * 0.5, 0.25)
        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("NaiveForecaster must be fitted before predict.")
        preds = [round(self.last_value_, 2) for _ in range(horizon_days)]
        lows = [max(0.0, round(p - 1.96 * self.residual_std_ * float(np.sqrt(i + 1)), 2)) for i, p in enumerate(preds)]
        highs = [round(p + 1.96 * self.residual_std_ * float(np.sqrt(i + 1)), 2) for i, p in enumerate(preds)]
        return {
            "dates": _future_dates(self.last_date, horizon_days),
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }


class SeasonalNaiveForecaster(BaseForecastingModel):
    """Day-of-week seasonal naive baseline using recent weekly profiles."""

    is_baseline = True

    def __init__(self, season_length: int = 7):
        super().__init__(model_name=f"SeasonalNaive{season_length}D")
        self.season_length = season_length
        self.dow_means_: Dict[int, float] = {}
        self.overall_mean_: float = 0.0
        self.residual_std_: float = 0.5

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date").copy()
        self.last_date = pd.Timestamp(df["date"].max())
        vals = _numeric_array(df[target_col])
        self.overall_mean_ = float(np.mean(vals)) if len(vals) > 0 else 0.0

        dow_arr: List[int] = [int(x) for x in pd.to_datetime(df["date"]).dt.day_of_week.to_numpy(dtype=np.int64)]
        df["dow"] = dow_arr
        recent = df.tail(self.season_length * 4)
        self.dow_means_ = {
            int(str(dow)): max(0.0, float(grp[target_col].mean()))
            for dow, grp in recent.groupby("dow")
        }

        fitted = np.array([self.dow_means_.get(d, self.overall_mean_) for d in dow_arr], dtype=np.float64)
        residuals = vals - fitted
        self.residual_std_ = float(np.std(residuals)) if len(residuals) > 1 else max(self.overall_mean_ * 0.5, 0.25)
        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("SeasonalNaiveForecaster must be fitted before predict.")
        dates = []
        preds = []
        for i in range(horizon_days):
            dt = self.last_date + pd.Timedelta(days=i + 1)
            dates.append(dt.strftime("%Y-%m-%d"))
            p = float(self.dow_means_.get(dt.day_of_week, self.overall_mean_))
            preds.append(round(max(p, 0.0), 2))
        lows = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in preds]
        highs = [round(p + 1.96 * self.residual_std_, 2) for p in preds]
        return {
            "dates": dates,
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }


class MovingAverageForecaster(BaseForecastingModel):
    """Simple Moving Average baseline over trailing window days."""

    is_baseline = True

    def __init__(self, window: int = 14):
        super().__init__(model_name=f"MovingAverage({window}d)")
        self.window = window
        self.level_: float = 0.0
        self.residual_std_: float = 0.5

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date")
        self.last_date = pd.Timestamp(df["date"].max())
        vals = _numeric_list(df[target_col])
        tail = vals[-self.window :]
        self.level_ = max(sum(tail) / len(tail), 0.0) if tail else 0.0
        if len(vals) > 2:
            residuals: List[float] = []
            for idx in range(1, len(vals)):
                start = max(0, idx - self.window)
                win_slice = vals[start:idx]
                pred_prev = sum(win_slice) / len(win_slice)
                residuals.append(vals[idx] - pred_prev)
            self.residual_std_ = _std_float(residuals)
        else:
            self.residual_std_ = _std_float(vals, ddof=1) if len(vals) > 1 else max(self.level_ * 0.5, 0.25)
        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("MovingAverageForecaster must be fitted before predict.")
        preds = [round(self.level_, 2) for _ in range(horizon_days)]
        lows = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in preds]
        highs = [round(p + 1.96 * self.residual_std_, 2) for p in preds]
        return {
            "dates": _future_dates(self.last_date, horizon_days),
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }


class WeightedMovingAverageForecaster(BaseForecastingModel):
    """Linearly weighted moving average giving higher emphasis to recent demand."""

    is_baseline = True

    def __init__(self, window: int = 14):
        super().__init__(model_name=f"WeightedMovingAverage({window}d)")
        self.window = window
        self.level_: float = 0.0
        self.residual_std_: float = 0.5

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date")
        self.last_date = pd.Timestamp(df["date"].max())
        vals = _numeric_array(df[target_col])
        tail = vals[-self.window :]
        if len(tail) > 0:
            weights = np.arange(1, len(tail) + 1, dtype=np.float64)
            self.level_ = float(max(float(np.dot(tail, weights) / np.sum(weights)), 0.0))
        else:
            self.level_ = 0.0
        self.residual_std_ = float(np.std(vals - self.level_)) if len(vals) > 1 else max(self.level_ * 0.5, 0.25)
        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("WeightedMovingAverageForecaster must be fitted before predict.")
        preds = [round(self.level_, 2) for _ in range(horizon_days)]
        lows = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in preds]
        highs = [round(p + 1.96 * self.residual_std_, 2) for p in preds]
        return {
            "dates": _future_dates(self.last_date, horizon_days),
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }


class SimpleExponentialSmoothingForecaster(BaseForecastingModel):
    """SES baseline with alpha selected via minimum 1-step-ahead in-sample MSE."""

    is_baseline = True

    def __init__(self):
        super().__init__(model_name="SimpleExponentialSmoothing")
        self.alpha_: float = 0.3
        self.level_: float = 0.0
        self.residual_std_: float = 0.5

    @staticmethod
    def _run_ses(vals: np.ndarray, alpha: float) -> tuple[float, float]:
        level = float(vals[0])
        sq_errors: List[float] = []
        for y in vals[1:]:
            err = float(y) - level
            sq_errors.append(err * err)
            level = alpha * float(y) + (1.0 - alpha) * level
        rmse = float(np.sqrt(np.mean(sq_errors))) if sq_errors else 0.25
        return level, rmse

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date")
        self.last_date = pd.Timestamp(df["date"].max())
        vals = _numeric_array(df[target_col])
        if len(vals) == 0:
            self.level_ = 0.0
            self.residual_std_ = 0.25
        elif len(vals) == 1:
            self.level_ = max(float(vals[0]), 0.0)
            self.residual_std_ = max(self.level_ * 0.5, 0.25)
        else:
            best_alpha = 0.3
            best_level = float(vals[-1])
            best_rmse = float(np.inf)
            for alpha in (0.1, 0.2, 0.3, 0.5, 0.7):
                lvl, rmse = self._run_ses(vals, alpha)
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_alpha = alpha
                    best_level = lvl
            self.alpha_ = best_alpha
            self.level_ = max(float(best_level), 0.0)
            self.residual_std_ = float(best_rmse)
        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("SimpleExponentialSmoothingForecaster must be fitted before predict.")
        preds = [round(self.level_, 2) for _ in range(horizon_days)]
        lows = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in preds]
        highs = [round(p + 1.96 * self.residual_std_, 2) for p in preds]
        return {
            "dates": _future_dates(self.last_date, horizon_days),
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }


class CrostonSBAForecaster(BaseForecastingModel):
    """
    Syntetos-Boylan Approximation (Croston SBA) for intermittent/lumpy retail demand.
    Models positive demand size z_t and inter-demand interval p_t separately.
    """

    is_baseline = True

    def __init__(self, alpha: float = 0.15):
        super().__init__(model_name="CrostonSBA")
        self.alpha = alpha
        self.daily_rate_: float = 0.0
        self.residual_std_: float = 0.5

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date")
        self.last_date = pd.Timestamp(df["date"].max())
        vals = _numeric_array(df[target_col])

        pos_idx = np.flatnonzero(vals > 0.0)
        if len(pos_idx) == 0:
            self.daily_rate_ = 0.0
            self.residual_std_ = 0.1
            self.is_fitted = True
            self.training_time_seconds = round(time.time() - t0, 4)
            return

        z = float(vals[pos_idx[0]])
        p = float(int(pos_idx[0]) + 1)
        last_pos = int(pos_idx[0])

        for i in range(int(pos_idx[0]) + 1, len(vals)):
            if float(vals[i]) > 0.0:
                interval = float(i - last_pos)
                z = self.alpha * float(vals[i]) + (1.0 - self.alpha) * z
                p = self.alpha * interval + (1.0 - self.alpha) * p
                last_pos = i

        trailing_zeros = len(vals) - 1 - last_pos
        effective_p = max(p, float(trailing_zeros + 1) * 0.5 + p * 0.5)
        self.daily_rate_ = max(0.0, (1.0 - self.alpha / 2.0) * (z / max(effective_p, 1.0)))
        self.residual_std_ = float(np.std(vals - self.daily_rate_)) if len(vals) > 1 else max(self.daily_rate_, 0.25)
        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("CrostonSBAForecaster must be fitted before predict.")
        preds = [round(self.daily_rate_, 2) for _ in range(horizon_days)]
        lows = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in preds]
        highs = [round(p + 1.96 * self.residual_std_, 2) for p in preds]
        return {
            "dates": _future_dates(self.last_date, horizon_days),
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }


class ColdStartForecaster(BaseForecastingModel):
    """
    Transparent multi-tenant-safe hierarchical fallback forecaster (Levels 2–4):
    - Uses owner initial_daily_demand when configured (Level 4 explicit prior),
    - Or same-workspace category demand benchmark & day-of-week profile when available (Level 2),
    - Or conservative generalized category/catalog baseline (Level 3) or honest observed rate (Level 4).
    Never exposes cross-tenant raw data or fabricates evaluation accuracy.
    """

    is_baseline = True

    def __init__(
        self,
        initial_daily_demand: Optional[float] = None,
        category_benchmark: Optional[Dict[str, Any]] = None,
        generalized_baseline: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(model_name="ColdStartEstimator")
        self.initial_daily_demand = initial_daily_demand
        self.category_benchmark = category_benchmark or {}
        self.generalized_baseline = generalized_baseline or {}
        self.rate_: float = 0.0
        self.uncertainty_: float = 0.5
        self.dow_factors_: Dict[int, float] = {d: 1.0 for d in range(7)}
        self.hierarchy_level_: str = "LEVEL_4_COLD_START"
        self.hierarchy_explanation_: str = "Cold-start product metadata baseline."

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        if train_df is not None and not train_df.empty:
            df = train_df.sort_values("date")
            self.last_date = pd.Timestamp(df["date"].max())
            vals = _numeric_array(df[target_col])
            observed_mean = float(np.mean(vals)) if len(vals) > 0 else 0.0
        else:
            self.last_date = pd.Timestamp.utcnow().normalize()
            observed_mean = 0.0

        if self.initial_daily_demand is not None and float(self.initial_daily_demand) > 0:
            self.rate_ = float(self.initial_daily_demand)
            self.hierarchy_level_ = "LEVEL_4_COLD_START"
            self.hierarchy_explanation_ = f"Using owner-configured initial_daily_demand={self.rate_:.2f}."
            self.uncertainty_ = max(self.rate_ * 0.75, 0.25)
        elif observed_mean > 0:
            self.rate_ = observed_mean
            self.hierarchy_level_ = "LEVEL_1_TENANT_PRODUCT"
            self.hierarchy_explanation_ = "Using tenant product limited observed daily average baseline."
            self.uncertainty_ = max(self.rate_ * 0.7, 0.25)
        elif self.category_benchmark.get("available"):
            self.rate_ = max(0.0, float(self.category_benchmark.get("median_daily_demand") or self.category_benchmark.get("mean_daily_demand") or 0.0))
            self.dow_factors_ = dict(self.category_benchmark.get("dow_factors") or {d: 1.0 for d in range(7)})
            self.uncertainty_ = max(float(self.category_benchmark.get("std_dev") or self.rate_ * 0.75), 0.25 if self.rate_ > 0 else 0.0)
            self.hierarchy_level_ = "LEVEL_2_CATEGORY_PATTERN"
            self.hierarchy_explanation_ = (
                f"Using same-workspace Level-2 category prior ({self.category_benchmark.get('category')}, "
                f"{self.category_benchmark.get('peer_products', 0)} sibling product(s))."
            )
        elif self.generalized_baseline.get("available"):
            self.rate_ = max(0.0, float(self.generalized_baseline.get("daily_rate") or 0.0))
            self.dow_factors_ = dict(self.generalized_baseline.get("dow_factors") or {d: 1.0 for d in range(7)})
            self.uncertainty_ = max(self.rate_ * 0.85, 0.25 if self.rate_ > 0 else 0.0)
            self.hierarchy_level_ = "LEVEL_3_GENERALIZED_BASELINE"
            self.hierarchy_explanation_ = str(
                self.generalized_baseline.get("source")
                or "Using generalized synthetic/anonymized category prior baseline."
            )
        else:
            self.rate_ = 0.0
            self.uncertainty_ = 0.0
            self.hierarchy_level_ = "LEVEL_4_COLD_START"
            self.hierarchy_explanation_ = "No sales, category peers, or owner demand estimate available yet (0.0 baseline)."

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("ColdStartForecaster must be fitted before predict.")
        dates = []
        preds = []
        lows = []
        highs = []
        for i in range(horizon_days):
            dt = self.last_date + pd.Timedelta(days=i + 1)
            dates.append(dt.strftime("%Y-%m-%d"))
            factor = float(self.dow_factors_.get(dt.day_of_week, 1.0)) if self.rate_ > 0 else 1.0
            p = round(max(0.0, self.rate_ * factor), 2)
            preds.append(p)
            lows.append(max(0.0, round(p - 1.96 * self.uncertainty_, 2)))
            highs.append(round(p + 1.96 * self.uncertainty_, 2))
        return {
            "dates": dates,
            "predictions": preds,
            "lower_bounds": lows,
            "upper_bounds": highs,
        }
