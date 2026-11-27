import numpy as np
import pandas as pd
from typing import List, Tuple, Optional

class FeatureEngineeringService:
    """
    Constructs lag features, rolling window aggregates, calendar/seasonal signals,
    and temporal trend indicators for supervised machine learning models.
    """

    LAG_WINDOWS = [1, 2, 3, 7, 14, 21, 30]
    ROLLING_WINDOWS = [7, 14, 30]

    @classmethod
    def create_features(
        cls,
        df: pd.DataFrame,
        target_col: str = "demand",
        lags: Optional[List[int]] = None,
        rolling_windows: Optional[List[int]] = None
    ) -> pd.DataFrame:
        """
        Enriches a continuous daily DataFrame (must contain 'date' and target_col)
        with lag features, rolling statistics, and calendar attributes.
        """
        if df.empty:
            return df

        data = df.sort_values("date").copy()
        lags = lags or cls.LAG_WINDOWS
        rolling_windows = rolling_windows or cls.ROLLING_WINDOWS

        # 1. Calendar / Temporal Features
        data["day_of_week"] = data["date"].dt.day_of_week
        data["day_of_month"] = data["date"].dt.day
        data["month"] = data["date"].dt.month
        data["quarter"] = data["date"].dt.quarter
        data["is_weekend"] = data["day_of_week"].isin([5, 6]).astype(int)

        # Cyclical Sine/Cosine encodings for seasonal continuity
        data["sin_dow"] = np.sin(2 * np.pi * data["day_of_week"] / 7.0)
        data["cos_dow"] = np.cos(2 * np.pi * data["day_of_week"] / 7.0)
        data["sin_month"] = np.sin(2 * np.pi * data["month"] / 12.0)
        data["cos_month"] = np.cos(2 * np.pi * data["month"] / 12.0)

        # 2. Sequential Trend Index
        data["trend_index"] = np.arange(len(data))

        # 3. Lag Features (values from previous t-k days)
        for lag in lags:
            data[f"lag_{lag}"] = data[target_col].shift(lag)

        # 4. Rolling Window Statistics (computed using shifted values to avoid data leakage)
        # Shift by 1 so the current day's demand is never included in the rolling window
        shifted_target = data[target_col].shift(1)
        for w in rolling_windows:
            data[f"rolling_mean_{w}"] = shifted_target.rolling(window=w, min_periods=1).mean()
            data[f"rolling_std_{w}"] = shifted_target.rolling(window=w, min_periods=1).std().fillna(0)
            data[f"rolling_max_{w}"] = shifted_target.rolling(window=w, min_periods=1).max()
            data[f"rolling_min_{w}"] = shifted_target.rolling(window=w, min_periods=1).min()

        # Fill remaining initial NaNs from shifting with backward/forward fill
        data = data.bfill().ffill()

        return data

    @classmethod
    def get_feature_columns(cls, df: pd.DataFrame, target_col: str = "demand") -> List[str]:
        """
        Returns list of explanatory feature columns excluding 'date' and target_col.
        """
        excluded = {"date", target_col, "product_id", "sku"}
        return [c for c in df.columns if c not in excluded]
