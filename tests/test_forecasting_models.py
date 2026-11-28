import pytest
import pandas as pd
import numpy as np

from app.ml.models.arima_model import ARIMAForecaster
from app.ml.models.prophet_model import ProphetForecaster
from app.ml.models.rf_model import RandomForestForecaster
from app.ml.models.xgb_model import XGBoostForecaster
from app.ml.models.lstm_model import LSTMForecaster
from app.ml.base_model import BaseForecastingModel

@pytest.fixture
def synthetic_series():
    dates = pd.date_range(start="2025-01-01", periods=120, freq="D")
    t = np.arange(120)
    # Synthetic series: baseline + weekly seasonality + noise
    weekly = 2.0 * np.sin(2 * np.pi * t / 7.0)
    demand = np.maximum(5.0 + weekly + np.random.normal(0, 0.5, 120), 0.0)
    return pd.DataFrame({"date": dates, "demand": demand})

@pytest.mark.parametrize("model_cls,kwargs", [
    (ARIMAForecaster, {"order": (1, 1, 1)}),
    (ProphetForecaster, {}),
    (RandomForestForecaster, {"n_estimators": 30, "max_depth": 5}),
    (XGBoostForecaster, {"n_estimators": 30, "max_depth": 4}),
    (LSTMForecaster, {"sequence_length": 7, "hidden_units": 8, "epochs": 20}),
])
def test_forecasting_models_lifecycle(model_cls, kwargs, synthetic_series):
    model: BaseForecastingModel = model_cls(**kwargs)
    assert not model.is_fitted

    # Train
    train_df = synthetic_series.iloc[:-14].copy()
    test_df = synthetic_series.iloc[-14:].copy()

    model.fit(train_df, target_col="demand")
    assert model.is_fitted
    assert model.training_time_seconds >= 0

    # Predict 14 days out-of-sample
    forecast = model.predict(horizon_days=14)
    assert len(forecast["dates"]) == 14
    assert len(forecast["predictions"]) == 14
    assert len(forecast["lower_bounds"]) == 14
    assert len(forecast["upper_bounds"]) == 14

    # Predictions must be non-negative
    for p in forecast["predictions"]:
        assert p >= 0.0

    # Evaluate metrics
    metrics = model.evaluate(test_df["demand"].values, np.array(forecast["predictions"]))
    assert "mae" in metrics
    assert "rmse" in metrics
    assert "mape" in metrics
    assert metrics["mae"] >= 0.0
    assert metrics["rmse"] >= 0.0
