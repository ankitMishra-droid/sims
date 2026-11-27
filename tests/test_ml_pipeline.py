import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.ml.preprocess_service import DataPreprocessingService
from app.ml.feature_service import FeatureEngineeringService

@pytest.fixture
def sample_sales_data():
    dates = pd.date_range(start="2026-01-01", periods=90, freq="D")
    records = []
    for d in dates:
        # 20% of days have 0 sales
        qty = 0 if d.day % 5 == 0 else (d.day % 4 + 1)
        records.append({
            "date": d,
            "product_id": 1,
            "sku": "TEST-SKU-1",
            "quantity": qty,
            "unit_price": 100.0,
            "total_amount": qty * 100.0
        })
    return pd.DataFrame(records)

def test_daily_preprocessing_continuity_and_imputation(sample_sales_data):
    # Drop some random dates to test missing date imputation
    sparse_data = sample_sales_data[sample_sales_data["date"].dt.day % 3 != 0].copy()
    daily_df = DataPreprocessingService.prepare_daily_series(sparse_data, product_id=1)

    assert len(daily_df) == 90
    assert "date" in daily_df.columns
    assert "demand" in daily_df.columns
    assert daily_df["demand"].isna().sum() == 0
    # Unbroken sequence
    date_diffs = daily_df["date"].diff().dropna()
    assert (date_diffs == pd.Timedelta(days=1)).all()

def test_train_test_split(sample_sales_data):
    daily = DataPreprocessingService.prepare_daily_series(sample_sales_data, product_id=1)
    train, test = DataPreprocessingService.train_test_split(daily, test_days=14)
    assert len(test) == 14
    assert len(train) == len(daily) - 14
    assert train["date"].max() < test["date"].min()  # Zero lookahead leakage

def test_feature_engineering_lags_and_rolling(sample_sales_data):
    daily = DataPreprocessingService.prepare_daily_series(sample_sales_data, product_id=1)
    df_feat = FeatureEngineeringService.create_features(daily, target_col="demand")

    expected_features = ["lag_1", "lag_7", "lag_14", "rolling_mean_7", "rolling_std_7", "day_of_week", "month"]
    for feat in expected_features:
        assert feat in df_feat.columns, f"Feature {feat} missing from engineered columns"

    assert df_feat.isna().sum().sum() == 0
