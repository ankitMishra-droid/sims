import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..base_model import BaseForecastingModel


class LSTMForecaster(BaseForecastingModel):
    """
    Chronological Recurrent Sequence Network Forecaster (LSTM-style normalized sequence learner).
    Enforces strict sequential sample gating, train-only normalization, chronological validation
    split with early stopping & best-weight restoration, and honest ineligibility reporting.
    """

    is_baseline = False
    MIN_TRAIN_DAYS = 60
    MIN_NON_ZERO_DAYS = 25
    MIN_TRAIN_SEQUENCES = 24

    def __init__(
        self,
        sequence_length: int = 14,
        hidden_units: int = 16,
        epochs: int = 35,
        lr: float = 0.02,
        validation_fraction: float = 0.2,
        patience: int = 5,
    ):
        super().__init__(model_name="LSTMSequenceNetwork")
        self.sequence_length = sequence_length
        self.hidden_units = hidden_units
        self.epochs = epochs
        self.lr = lr
        self.validation_fraction = validation_fraction
        self.patience = patience

        self.W_ih: Optional[np.ndarray] = None
        self.W_hh: Optional[np.ndarray] = None
        self.b_h: Optional[np.ndarray] = None
        self.W_ho: Optional[np.ndarray] = None
        self.b_o: float = 0.0

        self.scale_min_: float = 0.0
        self.scale_max_: float = 1.0
        self.residual_std_: float = 1.0
        self.recent_sequence_: List[float] = []
        self.best_val_loss_: Optional[float] = None
        self.epochs_trained_: int = 0

    @classmethod
    def check_eligibility(
        cls,
        train_df: pd.DataFrame,
        profile: Optional[Dict[str, Any]] = None,
        sequence_length: int = 14,
    ) -> Tuple[bool, str]:
        n = len(train_df) if train_df is not None else 0
        if n < cls.MIN_TRAIN_DAYS:
            return (
                False,
                f"Requires >= {cls.MIN_TRAIN_DAYS} days history for LSTM sequence training & validation (got {n}).",
            )
        vals = pd.to_numeric(train_df["demand"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
        non_zero = int(np.count_nonzero(vals > 0.0))
        if non_zero < cls.MIN_NON_ZERO_DAYS:
            return (
                False,
                f"Requires >= {cls.MIN_NON_ZERO_DAYS} non-zero demand days to avoid overfitting sparse zeros (got {non_zero}).",
            )
        if float(vals.std()) < 1e-4:
            return False, "Zero/near-zero demand variance; deep sequence model is unnecessary."
        W = min(sequence_length, max(7, n // 5))
        seq_count = n - W
        if seq_count < cls.MIN_TRAIN_SEQUENCES:
            return False, f"Insufficient supervised sequence windows ({seq_count} < {cls.MIN_TRAIN_SEQUENCES})."
        return True, "Eligible for chronological LSTM sequence training with early stopping."

    def _scale(self, x: np.ndarray) -> np.ndarray:
        span = max(self.scale_max_ - self.scale_min_, 1e-6)
        return (x - self.scale_min_) / span

    def _unscale(self, x: np.ndarray) -> np.ndarray:
        span = max(self.scale_max_ - self.scale_min_, 1e-6)
        return (x * span) + self.scale_min_

    def _forward_batch(self, X_batch: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Vectorized recurrent forward pass retaining penultimate state & last input for truncated BPTT."""
        if self.W_ih is None or self.W_hh is None or self.b_h is None or self.W_ho is None:
            raise RuntimeError("LSTMForecaster weights are not initialized.")
        batch_n, seq_len = X_batch.shape
        h = np.zeros((batch_n, self.hidden_units), dtype=float)
        h_prev = h
        W_ih_T = self.W_ih.T  # (1, H)
        W_hh_T = self.W_hh.T  # (H, H)
        for t in range(seq_len):
            h_prev = h
            x_t = X_batch[:, t : t + 1]  # (N, 1)
            h = np.tanh(x_t @ W_ih_T + h @ W_hh_T + self.b_h)
        preds = h @ self.W_ho + self.b_o
        return preds, h, h_prev

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date").tail(730).copy()
        self.last_date = pd.Timestamp(df["date"].max())
        raw_series = np.asarray(
            pd.to_numeric(df[target_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64),
            dtype=np.float64,
        )

        W = min(self.sequence_length, max(2, len(raw_series) - 1))
        X_raw_list, y_raw_list = [], []
        for i in range(len(raw_series) - W):
            X_raw_list.append(raw_series[i : i + W])
            y_raw_list.append(raw_series[i + W])

        X_raw = np.array(X_raw_list, dtype=float) if X_raw_list else np.empty((0, W), dtype=float)
        y_raw = np.array(y_raw_list, dtype=float) if y_raw_list else np.empty((0,), dtype=float)

        # Chronological train/validation split BEFORE fitting scaler to prevent scaling leakage!
        n_seq = len(X_raw)
        val_n = max(4, round(n_seq * self.validation_fraction)) if n_seq >= 20 else 0
        train_n = n_seq - val_n

        if train_n > 0:
            train_end_idx = train_n + W
            scaler_source = raw_series[:train_end_idx]
        else:
            scaler_source = raw_series

        self.scale_min_ = float(np.min(scaler_source)) if len(scaler_source) > 0 else 0.0
        self.scale_max_ = float(np.max(scaler_source)) if len(scaler_source) > 0 else 1.0

        X = self._scale(X_raw) if n_seq > 0 else np.empty((0, W), dtype=float)
        y = self._scale(y_raw) if n_seq > 0 else np.empty((0,), dtype=float)

        scaled_tail = self._scale(raw_series[-W:]) if len(raw_series) >= W else np.zeros((W,), dtype=float)
        self.recent_sequence_ = list(scaled_tail)
        self.effective_seq_len_ = W

        rng = np.random.default_rng(42)
        self.W_ih = rng.normal(0.0, np.sqrt(2.0), size=(self.hidden_units, 1))
        self.W_hh = rng.normal(0.0, np.sqrt(2.0 / self.hidden_units), size=(self.hidden_units, self.hidden_units)) * 0.45
        self.b_h = np.zeros((self.hidden_units,), dtype=float)
        self.W_ho = rng.normal(0.0, np.sqrt(2.0 / self.hidden_units), size=(self.hidden_units,))

        X_tr, y_tr = X[:train_n], y[:train_n]
        X_val, y_val = (X[train_n:], y[train_n:]) if val_n > 0 else (np.empty((0, W)), np.empty((0,)))
        self.b_o = float(np.mean(y_tr)) if len(y_tr) > 0 else 0.0

        # Adam state for readout + recurrent input/bias weights
        m_Who, v_Who = np.zeros_like(self.W_ho), np.zeros_like(self.W_ho)
        m_bo, v_bo = 0.0, 0.0
        m_Wih, v_Wih = np.zeros_like(self.W_ih), np.zeros_like(self.W_ih)
        m_bh, v_bh = np.zeros_like(self.b_h), np.zeros_like(self.b_h)
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        weight_decay = 1e-4

        best_val = float("inf")
        best_weights = None
        wait_count = 0
        self.epochs_trained_ = 0

        if len(X_tr) > 0:
            batch_size = min(32, len(X_tr))
            step_num = 0
            for epoch in range(self.epochs):
                self.epochs_trained_ = epoch + 1
                perm = rng.permutation(len(X_tr))
                for start in range(0, len(X_tr), batch_size):
                    idx = perm[start : start + batch_size]
                    xb = X_tr[idx]
                    yb = y_tr[idx]
                    preds, h_final, _ = self._forward_batch(xb)
                    err = (preds - yb) / max(len(idx), 1)
                    grad_Who = (err @ h_final) + weight_decay * self.W_ho
                    grad_bo = float(np.sum(err))

                    # Propagate one-step gradient into hidden bias and last-step input weights
                    dh = np.outer(err, self.W_ho) * (1.0 - h_final * h_final)  # (B, H)
                    x_last = xb[:, -1:]  # (B, 1)
                    grad_Wih = dh.T @ x_last + weight_decay * self.W_ih
                    grad_bh = np.sum(dh, axis=0)

                    step_num += 1
                    b1_corr = 1.0 - (beta1 ** step_num)
                    b2_corr = 1.0 - (beta2 ** step_num)

                    m_Who = beta1 * m_Who + (1.0 - beta1) * grad_Who
                    v_Who = beta2 * v_Who + (1.0 - beta2) * (grad_Who ** 2)
                    self.W_ho -= self.lr * (m_Who / b1_corr) / (np.sqrt(v_Who / b2_corr) + eps)

                    m_bo = beta1 * m_bo + (1.0 - beta1) * grad_bo
                    v_bo = beta2 * v_bo + (1.0 - beta2) * (grad_bo ** 2)
                    self.b_o -= self.lr * (m_bo / b1_corr) / (np.sqrt(v_bo / b2_corr) + eps)

                    m_Wih = beta1 * m_Wih + (1.0 - beta1) * grad_Wih
                    v_Wih = beta2 * v_Wih + (1.0 - beta2) * (grad_Wih ** 2)
                    self.W_ih -= (self.lr * 0.25) * (m_Wih / b1_corr) / (np.sqrt(v_Wih / b2_corr) + eps)

                    m_bh = beta1 * m_bh + (1.0 - beta1) * grad_bh
                    v_bh = beta2 * v_bh + (1.0 - beta2) * (grad_bh ** 2)
                    self.b_h -= (self.lr * 0.25) * (m_bh / b1_corr) / (np.sqrt(v_bh / b2_corr) + eps)

                if len(X_val) > 0:
                    val_preds, _, _ = self._forward_batch(X_val)
                    val_loss = float(np.mean(np.square(val_preds - y_val)))
                    if val_loss < best_val - 1e-6:
                        best_val = val_loss
                        best_weights = (
                            self.W_ih.copy(),
                            self.b_h.copy(),
                            self.W_ho.copy(),
                            float(self.b_o),
                        )
                        wait_count = 0
                    else:
                        wait_count += 1
                        if wait_count >= self.patience:
                            break

            if best_weights is not None:
                self.W_ih, self.b_h, self.W_ho, self.b_o = best_weights
                self.best_val_loss_ = round(best_val, 6)

            eval_X = X_val if len(X_val) > 0 else X_tr
            eval_y = y_val if len(y_val) > 0 else y_tr
            all_preds, _, _ = self._forward_batch(eval_X)
            res = self._unscale(eval_y) - self._unscale(all_preds)
            self.residual_std_ = float(np.std(res)) if len(res) > 1 else 0.5
        else:
            self.residual_std_ = 0.5

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 4)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or not self.recent_sequence_ or self.last_date is None:
            raise RuntimeError("LSTMForecaster must be fitted before predict.")

        W = getattr(self, "effective_seq_len_", self.sequence_length)
        curr_seq = list(self.recent_sequence_)
        predictions = []
        future_dates = []

        for step in range(horizon_days):
            next_date = self.last_date + pd.Timedelta(days=step + 1)
            future_dates.append(next_date.strftime("%Y-%m-%d"))

            x_in = np.array(curr_seq[-W:], dtype=float).reshape(1, W)
            scaled_pred = float(self._forward_batch(x_in)[0][0])
            actual_pred = float(np.maximum(self._unscale(np.array([scaled_pred]))[0], 0.0))
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
