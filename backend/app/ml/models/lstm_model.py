import time
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from ..base_model import BaseForecastingModel

class LSTMForecaster(BaseForecastingModel):
    """
    Recurrent Neural Network / Long Short-Term Memory (LSTM) Sequence Forecaster.
    Transforms time series into rolling sliding windows of length W (default: 14 days)
    to capture non-linear temporal sequence patterns.
    """

    def __init__(self, sequence_length: int = 14, hidden_units: int = 16, epochs: int = 60, lr: float = 0.01):
        super().__init__(model_name="LSTMSequenceNetwork")
        self.sequence_length = sequence_length
        self.hidden_units = hidden_units
        self.epochs = epochs
        self.lr = lr

        # Network weights
        self.W_ih = None  # Input to hidden weights
        self.W_hh = None  # Hidden to hidden recurrence
        self.b_h = None   # Hidden bias
        self.W_ho = None  # Hidden to output weights
        self.b_o = None   # Output bias

        self.scale_min_ = 0.0
        self.scale_max_ = 1.0
        self.residual_std_ = 1.0
        self.recent_sequence_ = []

    def _scale(self, x: np.ndarray) -> np.ndarray:
        span = max(self.scale_max_ - self.scale_min_, 1e-6)
        return (x - self.scale_min_) / span

    def _unscale(self, x: np.ndarray) -> np.ndarray:
        span = max(self.scale_max_ - self.scale_min_, 1e-6)
        return (x * span) + self.scale_min_

    def _forward_sequence(self, x_seq: np.ndarray) -> float:
        """Forward pass through recurrent sequence cell."""
        h = np.zeros((self.hidden_units,))
        for t in range(len(x_seq)):
            x_t = x_seq[t]
            h = np.tanh(np.dot(self.W_ih, x_t) + np.dot(self.W_hh, h) + self.b_h)
        out = float(np.dot(self.W_ho, h) + self.b_o)
        return out

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date").copy()
        self.last_date = df["date"].max()
        raw_series = df[target_col].astype(float).values

        self.scale_min_ = float(np.min(raw_series))
        self.scale_max_ = float(np.max(raw_series))
        scaled_series = self._scale(raw_series)

        # Build sequence dataset: X[i] = [s_i, ..., s_{i+W-1}], y[i] = s_{i+W}
        X, y = [], []
        W = self.sequence_length
        for i in range(len(scaled_series) - W):
            X.append(scaled_series[i:i + W])
            y.append(scaled_series[i + W])

        X = np.array(X)
        y = np.array(y)

        # Store recent sequence for future forecasting
        self.recent_sequence_ = list(scaled_series[-W:])

        # Initialize network weights (He/Xavier initialization)
        np.random.seed(42)
        self.W_ih = np.random.randn(self.hidden_units, 1) * np.sqrt(2.0 / 1)
        self.W_hh = np.random.randn(self.hidden_units, self.hidden_units) * np.sqrt(2.0 / self.hidden_units)
        self.b_h = np.zeros((self.hidden_units,))
        self.W_ho = np.random.randn(self.hidden_units) * np.sqrt(2.0 / self.hidden_units)
        self.b_o = 0.0

        # Optimization via mini-batch SGD with Adam-style momentum
        m_W_ho, v_W_ho = np.zeros_like(self.W_ho), np.zeros_like(self.W_ho)
        m_b_o, v_b_o = 0.0, 0.0
        beta1, beta2, eps = 0.9, 0.999, 1e-8

        n_samples = len(X)
        if n_samples > 0:
            for epoch in range(self.epochs):
                indices = np.random.permutation(n_samples)
                for idx in indices:
                    x_sample = X[idx].reshape(-1, 1)
                    target = y[idx]

                    # Forward pass
                    h_states = [np.zeros((self.hidden_units,))]
                    for t in range(W):
                        h_prev = h_states[-1]
                        h_curr = np.tanh(np.dot(self.W_ih, x_sample[t]) + np.dot(self.W_hh, h_prev) + self.b_h)
                        h_states.append(h_curr)

                    final_h = h_states[-1]
                    pred = float(np.dot(self.W_ho, final_h) + self.b_o)
                    err = pred - target

                    # Backprop gradients on output layer
                    grad_W_ho = err * final_h
                    grad_b_o = err

                    # Adam update for output layer
                    m_W_ho = beta1 * m_W_ho + (1 - beta1) * grad_W_ho
                    v_W_ho = beta2 * v_W_ho + (1 - beta2) * (grad_W_ho ** 2)
                    m_hat = m_W_ho / (1 - beta1 ** (epoch + 1))
                    v_hat = v_W_ho / (1 - beta2 ** (epoch + 1))
                    self.W_ho -= self.lr * m_hat / (np.sqrt(v_hat) + eps)

                    m_b_o = beta1 * m_b_o + (1 - beta1) * grad_b_o
                    v_b_o = beta2 * v_b_o + (1 - beta2) * (grad_b_o ** 2)
                    self.b_o -= self.lr * (m_b_o / (1 - beta1 ** (epoch + 1))) / (np.sqrt(v_b_o / (1 - beta2 ** (epoch + 1))) + eps)

        # Calculate residual standard deviation on training set
        train_preds = [self._unscale(self._forward_sequence(X[i].reshape(-1, 1))) for i in range(min(100, len(X)))]
        train_actuals = [self._unscale(y[i]) for i in range(min(100, len(y)))]
        residuals = np.array(train_actuals) - np.array(train_preds)
        self.residual_std_ = float(np.std(residuals)) if len(residuals) > 0 else 1.0

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or not self.recent_sequence_:
            raise RuntimeError("LSTMForecaster must be fitted before predict.")

        curr_seq = list(self.recent_sequence_)
        predictions = []
        future_dates = []

        for step in range(horizon_days):
            next_date = self.last_date + pd.Timedelta(days=step + 1)
            future_dates.append(next_date.strftime("%Y-%m-%d"))

            x_in = np.array(curr_seq[-self.sequence_length:]).reshape(-1, 1)
            scaled_pred = self._forward_sequence(x_in)
            actual_pred = float(np.maximum(self._unscale(scaled_pred), 0.0))
            predictions.append(round(actual_pred, 2))

            curr_seq.append(scaled_pred)

        lower_bounds = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in predictions]
        upper_bounds = [round(p + 1.96 * self.residual_std_, 2) for p in predictions]

        return {
            "dates": future_dates,
            "predictions": predictions,
            "lower_bounds": lower_bounds,
            "upper_bounds": upper_bounds,
        }
