import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict, Any

class DataPreprocessingService:
    """
    Cleans, resamples, imputes missing dates, and prepares continuous daily time series.
    """

    @staticmethod
    def prepare_daily_series(
        df: pd.DataFrame,
        product_id: Optional[int] = None,
        freq: str = "D",
        clip_outliers: bool = True
    ) -> pd.DataFrame:
        """
        Filters by product_id if provided, aggregates daily demand, ensures unbroken
        chronological date sequence, fills missing days with 0, and handles outliers.
        """
        if df.empty:
            return pd.DataFrame(columns=["date", "demand"])

        data = df.copy()
        if product_id is not None and "product_id" in data.columns:
            data = data[data["product_id"] == product_id]

        if data.empty:
            return pd.DataFrame(columns=["date", "demand"])

        # Aggregate sales by date (normalizing timestamps to date midnight)
        data["date"] = pd.to_datetime(data["date"]).dt.normalize()
        daily = data.groupby("date")["quantity"].sum().reset_index()
        daily = daily.rename(columns={"quantity": "demand"})

        # Build full continuous date range
        start_date = daily["date"].min()
        end_date = daily["date"].max()
        full_idx = pd.date_range(start=start_date, end=end_date, freq=freq, name="date")

        daily = daily.set_index("date")
        daily = daily.reindex(full_idx, fill_value=0.0).reset_index()

        # Handle outliers using IQR clipping if enabled
        if clip_outliers and len(daily) > 30:
            q25 = daily["demand"].quantile(0.25)
            q75 = daily["demand"].quantile(0.75)
            iqr = q75 - q25
            upper_bound = q75 + (3.0 * iqr)  # 3x IQR allows strong peaks but clips extreme data corruption
            daily["demand"] = daily["demand"].clip(lower=0.0, upper=upper_bound)

        return daily

    @staticmethod
    def train_test_split(
        daily_df: pd.DataFrame,
        test_days: int = 30
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Splits daily time-series chronologically into train and test sets to prevent future lookahead.
        """
        if len(daily_df) <= test_days:
            split_idx = int(len(daily_df) * 0.8)
            train = daily_df.iloc[:split_idx].copy()
            test = daily_df.iloc[split_idx:].copy()
        else:
            train = daily_df.iloc[:-test_days].copy()
            test = daily_df.iloc[-test_days:].copy()

        return train, test
