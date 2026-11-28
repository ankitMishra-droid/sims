from typing import List, Optional
import numpy as np
import pandas as pd


class FeatureEngineeringService:
    """
    Creates strictly causal lag, rolling, calendar, festive, price, promotion, and
    stockout-lag features from daily demand data.
    All autoregressive/contextual lag transforms depend exclusively on observations
    strictly prior to time t (zero bfill / future leakage).
    """

    LAG_WINDOWS = [1, 2, 3, 7, 14, 21, 30]
    ROLLING_WINDOWS = [7, 14, 30]

    @staticmethod
    def create_features(
        df: pd.DataFrame,
        target_col: str = "demand",
        *,
        drop_warmup: bool = False,
    ) -> pd.DataFrame:
        data = df.copy()
        data["date"] = pd.to_datetime(data["date"])
        data = data.sort_values("date").reset_index(drop=True)

        # Deterministic calendar features known at any prediction origin t
        data["day_of_week"] = data["date"].dt.day_of_week
        data["is_weekend"] = (data["day_of_week"] >= 5).astype(int)
        data["day_of_month"] = data["date"].dt.day
        data["week_of_year"] = data["date"].dt.isocalendar().week.astype(int)
        data["month"] = data["date"].dt.month
        data["quarter"] = data["date"].dt.quarter
        festive_mask = (
            ((data["month"] == 10) & (data["day_of_month"] >= 10))
            | ((data["month"] == 11) & (data["day_of_month"] <= 20))
            | ((data["month"] == 12) & (data["day_of_month"] >= 20))
        )
        data["is_festive_window"] = festive_mask.astype(int)

        # Cyclic encodings
        data["dow_sin"] = np.sin(2.0 * np.pi * data["day_of_week"] / 7.0)
        data["dow_cos"] = np.cos(2.0 * np.pi * data["day_of_week"] / 7.0)
        data["month_sin"] = np.sin(2.0 * np.pi * data["month"] / 12.0)
        data["month_cos"] = np.cos(2.0 * np.pi * data["month"] / 12.0)

        target_series = pd.to_numeric(data[target_col], errors="coerce").fillna(0.0).astype(float)
        shifted_1 = target_series.shift(1)
        # Strictly causal prior expanding mean (depends only on 0..t-1), defaulting to 0.0 at t=0
        causal_prior_mean = shifted_1.expanding(min_periods=1).mean().fillna(0.0)

        # Autoregressive lags without backward lookahead leakage
        for lag in FeatureEngineeringService.LAG_WINDOWS:
            col = f"lag_{lag}"
            lag_vals = target_series.shift(lag)
            if not drop_warmup:
                lag_vals = lag_vals.fillna(causal_prior_mean)
            data[col] = lag_vals

        # Strictly causal rolling mean & std over [t-window .. t-1]
        for win in FeatureEngineeringService.ROLLING_WINDOWS:
            rmean = shifted_1.rolling(window=win, min_periods=1).mean()
            rstd = shifted_1.rolling(window=win, min_periods=1).std()
            if not drop_warmup:
                rmean = rmean.fillna(0.0)
                rstd = rstd.fillna(0.0)
            data[f"rolling_mean_{win}"] = rmean
            data[f"rolling_std_{win}"] = rstd

        # Strictly causal stockout & pricing context (never leaks target at >= t)
        if "is_stockout_day" in data.columns:
            stockout_num = data["is_stockout_day"].astype(float)
        else:
            stockout_num = pd.Series(0.0, index=data.index)
        shifted_so = stockout_num.shift(1).fillna(0.0)
        data["prior_stockout_flag"] = shifted_so
        data["rolling_stockout_7"] = shifted_so.rolling(window=7, min_periods=1).mean().fillna(0.0)

        if "price_change_pct" in data.columns:
            price_chg = pd.to_numeric(data["price_change_pct"], errors="coerce").fillna(0.0).astype(float)
            data["prior_price_change_pct"] = price_chg.shift(1).fillna(0.0)
        else:
            data["prior_price_change_pct"] = 0.0

        if "is_promo_day" in data.columns:
            promo_num = pd.to_numeric(data["is_promo_day"], errors="coerce").fillna(0.0).astype(float)
            data["prior_promo_flag"] = promo_num.shift(1).fillna(0.0)
        else:
            data["prior_promo_flag"] = 0.0

        if drop_warmup:
            data = data.dropna().reset_index(drop=True)

        return data

    @staticmethod
    def get_feature_columns(df: Optional[pd.DataFrame] = None, target_col: str = "demand") -> List[str]:
        cols = [
            "day_of_week",
            "is_weekend",
            "day_of_month",
            "week_of_year",
            "month",
            "quarter",
            "is_festive_window",
            "dow_sin",
            "dow_cos",
            "month_sin",
            "month_cos",
            "prior_stockout_flag",
            "rolling_stockout_7",
            "prior_price_change_pct",
            "prior_promo_flag",
        ]
        for lag in FeatureEngineeringService.LAG_WINDOWS:
            cols.append(f"lag_{lag}")
        for win in FeatureEngineeringService.ROLLING_WINDOWS:
            cols.append(f"rolling_mean_{win}")
            cols.append(f"rolling_std_{win}")
        if df is not None:
            return [c for c in cols if c in df.columns and c != target_col]
        return cols
