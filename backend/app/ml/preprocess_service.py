from datetime import date, datetime, timezone
import hashlib
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

MAX_HISTORY_LOOKBACK_DAYS = 3653  # Up to 10 years (10 * 365 + leap days)


def _to_utc_day(val: Optional[datetime | date | pd.Timestamp]) -> Optional[pd.Timestamp]:
    if val is None:
        return None
    ts = pd.Timestamp(val)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(timezone.utc).tz_localize(None)
    return ts.normalize()


def _is_festive_calendar_day(ts: pd.Timestamp) -> int:
    """Deterministic Indian/global peak festive calendar signal strictly from date t."""
    m = ts.month
    d = ts.day
    if (m == 10 and d >= 10) or (m == 11 and d <= 20):
        return 1
    if m == 12 and d >= 20:
        return 1
    return 0


class DataPreprocessingService:
    """
    Aggregates sales, inventory ledger, and purchase receipts into a continuous,
    tenant-safe daily demand series up to 7 years (2,557 days), separates genuine
    zero-demand days from stockout unavailability and unrecorded gaps, detects
    price/promotion/calendar context, clips extreme outliers conservatively, and
    computes complete historical data quality diagnostics.
    """

    @staticmethod
    def compute_dataset_version(
        daily_df: pd.DataFrame,
        business_id: int,
        product_id: int,
        cutoff_dt: datetime,
    ) -> str:
        """Return a deterministic SHA256 dataset fingerprint for provenance & caching."""
        if daily_df is None or daily_df.empty:
            sig = f"{business_id}:{product_id}:empty:{cutoff_dt.strftime('%Y-%m-%d')}"
            return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]

        ordered = daily_df.sort_values("date")
        total_raw = round(float(ordered["raw_demand"].sum()), 4) if "raw_demand" in ordered.columns else round(float(ordered["demand"].sum()), 4)
        stockouts = int(ordered["is_stockout_day"].sum()) if "is_stockout_day" in ordered.columns else 0
        min_d = pd.Timestamp(ordered["date"].min()).strftime("%Y-%m-%d")
        max_d = pd.Timestamp(ordered["date"].max()).strftime("%Y-%m-%d")
        sig = f"{business_id}:{product_id}:{len(ordered)}:{min_d}:{max_d}:{total_raw}:{stockouts}"
        return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def prepare_daily_series(
        raw_df: pd.DataFrame,
        product_id: Optional[int] = None,
        *,
        as_of_date: Optional[datetime | date] = None,
        product_created_at: Optional[datetime | date] = None,
        stock_logs_df: Optional[pd.DataFrame] = None,
        receipts_df: Optional[pd.DataFrame] = None,
        current_stock: Optional[int] = None,
        default_selling_price: Optional[float] = None,
        is_product_active: bool = True,
        clip_outliers: bool = True,
        lookback_cap_days: int = MAX_HISTORY_LOOKBACK_DAYS,
    ) -> pd.DataFrame:
        """
        Aggregate transaction rows into an unbroken daily calendar time series (0..7 years).
        Explicitly distinguishes:
        - DEMAND_OBSERVED (recorded non-zero sales)
        - ACTUAL_ZERO_DEMAND (stock confirmed available via ledger/receipts, zero sales)
        - PRODUCT_UNAVAILABLE (confirmed stockout closing_stock <= 0 or inactive catalog)
        - NO_RECORDED_TRANSACTION (zero sales without stock-ledger confirmation)
        - MISSING_HISTORICAL_DATA (pre-inception or corrupted gaps)
        """
        end_cap = _to_utc_day(as_of_date)
        created_day = _to_utc_day(product_created_at)

        df = raw_df.copy() if raw_df is not None else pd.DataFrame()
        if not df.empty:
            if "product_id" in df.columns and product_id is not None:
                df = df[df["product_id"] == product_id].copy()
            if "status" in df.columns:
                df = df[df["status"].astype(str).str.upper() != "CANCELLED"].copy()
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"])
                df["date"] = df["date"].apply(lambda d: _to_utc_day(d))
                if end_cap is not None:
                    df = df[df["date"] <= end_cap]

        logs = stock_logs_df.copy() if stock_logs_df is not None else pd.DataFrame()
        if not logs.empty and "timestamp" in logs.columns:
            logs["day"] = pd.to_datetime(logs["timestamp"], errors="coerce").apply(lambda d: _to_utc_day(d))
            logs = logs.dropna(subset=["day"])
            if end_cap is not None:
                logs = logs[logs["day"] <= end_cap]

        rec_df = receipts_df.copy() if receipts_df is not None else pd.DataFrame()
        if not rec_df.empty and "date" in rec_df.columns:
            rec_df["day"] = pd.to_datetime(rec_df["date"], errors="coerce").apply(lambda d: _to_utc_day(d))
            rec_df = rec_df.dropna(subset=["day"])
            if end_cap is not None:
                rec_df = rec_df[rec_df["day"] <= end_cap]

        if df.empty:
            if end_cap is None:
                return pd.DataFrame(
                    columns=[
                        "date",
                        "demand",
                        "raw_demand",
                        "revenue",
                        "is_zero_demand",
                        "is_stockout_day",
                        "stockout_imputed",
                        "closing_stock",
                        "closing_stock_known",
                        "day_state",
                        "receipt_qty",
                        "effective_price",
                        "price_change_pct",
                        "is_promo_day",
                        "is_festive_window",
                        "is_outlier_day",
                    ]
                )
            earliest_candidates = [d for d in (created_day,) if d is not None and d <= end_cap]
            if not logs.empty:
                earliest_candidates.append(logs["day"].min())
            if not rec_df.empty:
                earliest_candidates.append(rec_df["day"].min())
            start_day = min(earliest_candidates) if earliest_candidates else end_cap
            if (end_cap - start_day).days > lookback_cap_days:
                start_day = end_cap - pd.Timedelta(days=lookback_cap_days)
            full_dates = pd.date_range(start=start_day, end=end_cap, freq="D")
            out = pd.DataFrame({"date": full_dates})
            out["raw_demand"] = 0.0
            out["demand"] = 0.0
            out["revenue"] = 0.0
            out["is_zero_demand"] = True
            out["closing_stock"] = -1.0
            out["closing_stock_known"] = False
            out["is_stockout_day"] = False
            out["receipt_qty"] = 0.0
            if not rec_df.empty:
                daily_rec = rec_df.groupby("day")["received_quantity"].sum()
                out["receipt_qty"] = out["date"].map(daily_rec).fillna(0.0).astype(float)
            if not logs.empty:
                daily_close = logs.sort_values("timestamp").groupby("day", as_index=True)["closing_stock"].last()
                mapped_close = out["date"].map(daily_close).ffill()
                known_mask = mapped_close.notna()
                out["closing_stock_known"] = known_mask
                out.loc[known_mask, "closing_stock"] = mapped_close[known_mask].astype(float)
                out["is_stockout_day"] = out["closing_stock_known"] & (out["closing_stock"] <= 0.0)
            if current_stock is not None and current_stock <= 0 and len(out) > 0:
                out.loc[out.index[-1], "closing_stock"] = 0.0
                out.loc[out.index[-1], "closing_stock_known"] = True
                out.loc[out.index[-1], "is_stockout_day"] = True
            out["stockout_imputed"] = 0.0
            out["effective_price"] = float(default_selling_price or 0.0)
            out["price_change_pct"] = 0.0
            out["is_promo_day"] = 0
            out["is_festive_window"] = [_is_festive_calendar_day(pd.Timestamp(d)) for d in out["date"]]
            out["is_outlier_day"] = False
            unavail_arr = out["is_stockout_day"].to_numpy(dtype=bool) | (not is_product_active)
            actual_zero_arr = out["closing_stock_known"].to_numpy(dtype=bool) & (out["closing_stock"].to_numpy(dtype=float) > 0)
            out["day_state"] = [
                "PRODUCT_UNAVAILABLE"
                if unavail
                else ("ACTUAL_ZERO_DEMAND" if act_zero else "NO_RECORDED_TRANSACTION")
                for unavail, act_zero in zip(unavail_arr.tolist(), actual_zero_arr.tolist())
            ]
            return out

        qty_col = "quantity" if "quantity" in df.columns else "demand"
        df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0.0).clip(lower=0.0)
        if "total_amount" not in df.columns:
            df["total_amount"] = 0.0
        else:
            df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce").fillna(0.0)

        daily_agg = (
            df.groupby("date", as_index=False)
            .agg(
                raw_demand=(qty_col, "sum"),
                revenue=("total_amount", "sum"),
            )
            .sort_values("date")
        )
        raw_dem_arr = daily_agg["raw_demand"].to_numpy(dtype=float)
        rev_arr = daily_agg["revenue"].to_numpy(dtype=float)
        daily_agg["observed_price"] = [
            (rev / max(raw, 1e-6)) if raw > 0 else np.nan
            for raw, rev in zip(raw_dem_arr.tolist(), rev_arr.tolist())
        ]

        min_sale_day = daily_agg["date"].min()
        max_sale_day = daily_agg["date"].max()
        start_day = min_sale_day
        earliest_known = min_sale_day
        if not logs.empty:
            earliest_known = min(earliest_known, logs["day"].min())
        if not rec_df.empty:
            earliest_known = min(earliest_known, rec_df["day"].min())
        if created_day is not None and created_day < earliest_known:
            earliest_known = created_day
        if end_cap is not None and earliest_known < start_day:
            capped_earliest = end_cap - pd.Timedelta(days=lookback_cap_days)
            start_day = max(earliest_known, capped_earliest)
        end_day = max(max_sale_day, end_cap) if end_cap is not None else max_sale_day
        if (end_day - start_day).days > lookback_cap_days:
            start_day = end_day - pd.Timedelta(days=lookback_cap_days)

        full_dates = pd.date_range(start=start_day, end=end_day, freq="D")
        out = pd.DataFrame({"date": full_dates}).merge(daily_agg, on="date", how="left")
        out["raw_demand"] = out["raw_demand"].fillna(0.0).clip(lower=0.0)
        out["revenue"] = out["revenue"].fillna(0.0).clip(lower=0.0)
        out["is_zero_demand"] = out["raw_demand"] <= 0.0

        out["receipt_qty"] = 0.0
        if not rec_df.empty:
            daily_rec = rec_df.groupby("day")["received_quantity"].sum()
            out["receipt_qty"] = out["date"].map(daily_rec).fillna(0.0).astype(float)

        # Infer day-end closing stock and stockout constraints strictly from ledger when available
        out["closing_stock"] = -1.0
        out["closing_stock_known"] = False
        out["is_stockout_day"] = False
        if not logs.empty:
            daily_close = logs.sort_values("timestamp").groupby("day", as_index=True)["closing_stock"].last()
            mapped_close = out["date"].map(daily_close).ffill()
            known_mask = mapped_close.notna()
            out["closing_stock_known"] = known_mask
            out.loc[known_mask, "closing_stock"] = mapped_close[known_mask].astype(float)
            out["is_stockout_day"] = out["is_zero_demand"] & out["closing_stock_known"] & (out["closing_stock"] <= 0.0)

        if current_stock is not None and current_stock <= 0 and len(out) > 0:
            last_idx = out.index[-1]
            if not bool(out.loc[last_idx, "closing_stock_known"]):
                out.loc[last_idx, "closing_stock"] = 0.0
                out.loc[last_idx, "closing_stock_known"] = True
            if bool(out.loc[last_idx, "is_zero_demand"]):
                out.loc[last_idx, "is_stockout_day"] = True

        # Causal price, price change, and promotion signals (strictly causal: no bfill!)
        base_price = float(default_selling_price or 0.0)
        if "observed_price" in out.columns:
            eff_price = out["observed_price"].ffill()
            if base_price > 0:
                eff_price = eff_price.fillna(base_price)
            else:
                eff_price = eff_price.fillna(0.0)
            out["effective_price"] = eff_price.astype(float).clip(lower=0.0)
        else:
            out["effective_price"] = max(0.0, base_price)

        eff_arr = out["effective_price"].to_numpy(dtype=float)
        prev_price_arr = out["effective_price"].shift(1).fillna(out["effective_price"]).to_numpy(dtype=float)
        out["price_change_pct"] = [
            ((eff_v - prev_v) / max(prev_v, 1e-6)) if prev_v > 1e-6 else 0.0
            for eff_v, prev_v in zip(eff_arr.tolist(), prev_price_arr.tolist())
        ]
        trailing_med_price = (
            out["effective_price"].shift(1).rolling(window=30, min_periods=5).median().fillna(out["effective_price"])
        )
        promo_mask = (
            (out["raw_demand"] > 0)
            & (trailing_med_price > 1e-6)
            & (out["effective_price"] <= trailing_med_price * 0.90)
        )
        out["is_promo_day"] = promo_mask.astype(int)
        out["is_festive_window"] = [_is_festive_calendar_day(pd.Timestamp(d)) for d in out["date"]]

        if "observed_price" in out.columns:
            out = out.drop(columns=["observed_price"])

        # Conservative outlier capping only on sufficient positive series
        demand_series = out["raw_demand"].astype(float).copy()
        is_outlier = pd.Series(False, index=out.index)
        if clip_outliers:
            positive_vals = demand_series[demand_series > 0]
            if len(positive_vals) >= 14:
                q25 = float(positive_vals.quantile(0.25))
                q75 = float(positive_vals.quantile(0.75))
                iqr = q75 - q25
                med = float(positive_vals.median())
                mad = float((positive_vals - med).abs().median())
                upper_iqr = q75 + 3.0 * iqr if iqr > 0 else np.inf
                upper_mad = med + 5.0 * mad * 1.4826 if mad > 0 else np.inf
                upper_cap = max(float(min(upper_iqr, upper_mad)), q75 * 1.5)
                if np.isfinite(upper_cap) and upper_cap > 0:
                    is_outlier = demand_series > upper_cap
                    demand_series = demand_series.clip(upper=upper_cap)

        out["is_outlier_day"] = is_outlier.astype(bool)
        out["demand"] = demand_series.clip(lower=0.0)

        # Classify every day's demand observation reliability cleanly
        pre_first_activity = out["date"] < min_sale_day
        discontinued_mask = (not is_product_active) & (out["date"] > max_sale_day)
        day_states = []
        for idx, row in out.iterrows():
            if float(row["raw_demand"]) > 0.0:
                day_states.append("DEMAND_OBSERVED")
            elif bool(row["is_stockout_day"]) or bool(discontinued_mask.loc[idx]):
                day_states.append("PRODUCT_UNAVAILABLE")
            elif bool(row["closing_stock_known"]) and float(row["closing_stock"]) > 0.0:
                day_states.append("ACTUAL_ZERO_DEMAND")
            elif bool(pre_first_activity.loc[idx]) and not bool(row["closing_stock_known"]):
                day_states.append("MISSING_HISTORICAL_DATA")
            else:
                day_states.append("NO_RECORDED_TRANSACTION")
        out["day_state"] = day_states

        # Unconstrained reference value strictly for optional inspection (raw_demand remains genuine 0.0)
        non_stockout_mask = ~out["is_stockout_day"]
        fallback_unconstrained = (
            float(out.loc[non_stockout_mask, "demand"].tail(28).mean())
            if non_stockout_mask.any()
            else 0.0
        )
        out["stockout_imputed"] = out["demand"].where(
            ~out["is_stockout_day"],
            max(0.0, fallback_unconstrained),
        )
        return out

    @staticmethod
    def train_test_split(daily_df: pd.DataFrame, test_days: int = 30) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Chronological train/test split strictly preserving temporal order."""
        if daily_df is None or daily_df.empty:
            empty = pd.DataFrame(columns=["date", "demand"])
            return empty, empty

        ordered = daily_df.sort_values("date").reset_index(drop=True)
        n = len(ordered)
        if n <= test_days:
            split_idx = max(1, int(n * 0.8))
        else:
            split_idx = n - test_days

        train_df = ordered.iloc[:split_idx].copy().reset_index(drop=True)
        test_df = ordered.iloc[split_idx:].copy().reset_index(drop=True)
        return train_df, test_df

    @staticmethod
    def analyze_demand_profile(
        daily_df: pd.DataFrame,
        product: Optional[Any] = None,
        *,
        raw_df: Optional[pd.DataFrame] = None,
        receipts_df: Optional[pd.DataFrame] = None,
        stock_logs_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Compute transparent demand statistics, intermittency indices (ADI / CV^2),
        data-quality completeness report, stockout uncertainty, synthetic provenance,
        and honest data-sufficiency tiering.
        """
        is_discontinued = product is not None and not getattr(product, "is_active", True)
        synth_sales = (
            int(raw_df["is_synthetic"].sum())
            if raw_df is not None and not raw_df.empty and "is_synthetic" in raw_df.columns
            else 0
        )
        total_sales_rows = len(raw_df) if raw_df is not None else 0
        product_is_synth = bool(getattr(product, "is_synthetic", False)) if product is not None else False
        has_synth = product_is_synth or synth_sales > 0

        if daily_df is None or daily_df.empty:
            return {
                "history_days_observed": 0,
                "available_history_years": 0.0,
                "valid_observation_days": 0,
                "non_zero_demand_days": 0,
                "zero_demand_days": 0,
                "actual_zero_demand_days": 0,
                "no_recorded_transaction_days": 0,
                "product_unavailable_days": 0,
                "missing_historical_days": 0,
                "stockout_days_count": 0,
                "outlier_days_count": 0,
                "outlier_frequency": 0.0,
                "missing_date_pct": 100.0,
                "data_completeness_pct": 0.0,
                "zero_demand_ratio": 1.0,
                "zero_demand_frequency": 1.0,
                "stockout_frequency": 0.0,
                "stockout_uncertainty": "UNCONFIRMED_NO_LEDGER",
                "total_units_sold": 0.0,
                "avg_daily_demand": 0.0,
                "demand_std_dev": 0.0,
                "avg_weekly_demand": 0.0,
                "avg_monthly_demand": 0.0,
                "cv": None,
                "adi": None,
                "is_intermittent": False,
                "is_discontinued": is_discontinued,
                "recent_7d_avg": 0.0,
                "prior_7d_avg": 0.0,
                "recent_14d_avg": 0.0,
                "prior_14d_avg": 0.0,
                "trend_pct_change": None,
                "trend_direction": "INSUFFICIENT_DATA",
                "training_start_date": None,
                "training_end_date": None,
                "last_sale_date": None,
                "days_since_last_sale": None,
                "data_sufficiency": "NEW",
                "unit": getattr(product, "unit", "piece") if product is not None else "piece",
                "synthetic_records_count": synth_sales,
                "genuine_records_count": max(0, total_sales_rows - synth_sales),
                "has_synthetic_data": has_synth,
                "synthetic_ratio": round(synth_sales / total_sales_rows, 4) if total_sales_rows > 0 else (1.0 if product_is_synth else 0.0),
                "receipts_count": len(receipts_df) if receipts_df is not None else 0,
                "ledger_entries_count": len(stock_logs_df) if stock_logs_df is not None else 0,
            }

        ordered = daily_df.sort_values("date").reset_index(drop=True)
        n = len(ordered)
        raw_vals = ordered["raw_demand"].astype(float) if "raw_demand" in ordered.columns else ordered["demand"].astype(float)
        clean_vals = ordered["demand"].astype(float)
        non_zero_mask = raw_vals > 0
        non_zero_days = sum(1 for v in raw_vals.tolist() if float(v) > 0.0)
        zero_days = n - non_zero_days
        stockout_days = (
            sum(1 for v in ordered["is_stockout_day"].tolist() if v)
            if "is_stockout_day" in ordered.columns
            else 0
        )
        outlier_days = (
            int(ordered["is_outlier_day"].sum())
            if "is_outlier_day" in ordered.columns
            else 0
        )
        states = ordered["day_state"].tolist() if "day_state" in ordered.columns else []
        actual_zero_days = sum(1 for s in states if s == "ACTUAL_ZERO_DEMAND")
        no_tx_days = sum(1 for s in states if s == "NO_RECORDED_TRANSACTION")
        unavail_days = sum(1 for s in states if s == "PRODUCT_UNAVAILABLE")
        missing_days = sum(1 for s in states if s == "MISSING_HISTORICAL_DATA")

        valid_obs_days = non_zero_days + actual_zero_days if states else (n - stockout_days)
        known_stock_days = (
            int(ordered["closing_stock_known"].sum())
            if "closing_stock_known" in ordered.columns
            else 0
        )
        if known_stock_days == 0:
            stockout_uncertainty = "UNCONFIRMED_NO_LEDGER"
        elif no_tx_days > 0:
            stockout_uncertainty = "PARTIAL_UNCERTAIN"
        else:
            stockout_uncertainty = "CONFIRMED_LEDGER"

        missing_pct = round(((missing_days + no_tx_days * 0.5) / n) * 100.0, 2) if n > 0 else 100.0
        if states and known_stock_days == 0 and no_tx_days == zero_days:
            # No ledger confirmation on zero-sale days -> treat calendar span conservatively as observed with uncertainty
            missing_pct = round((missing_days / n) * 100.0, 2) if n > 0 else 100.0
        completeness_pct = round(max(0.0, 100.0 - missing_pct), 2)

        zero_ratio = round(zero_days / n, 4) if n > 0 else 1.0
        stockout_freq = round(stockout_days / n, 4) if n > 0 else 0.0
        outlier_freq = round(outlier_days / n, 4) if n > 0 else 0.0

        # Active unconstrained demand mean excludes confirmed stockout/unavailable days
        non_stockout_vals = (
            clean_vals[~ordered["is_stockout_day"]]
            if "is_stockout_day" in ordered.columns
            else clean_vals
        )
        mean_all = float(clean_vals.mean())
        std_all = float(clean_vals.std(ddof=1)) if n > 1 else 0.0
        active_mean = float(non_stockout_vals.mean()) if len(non_stockout_vals) > 0 else mean_all
        effective_mean = active_mean if stockout_days > 0 and len(non_stockout_vals) >= 7 else mean_all

        cv = round(float(std_all / effective_mean), 4) if effective_mean > 0 else None
        adi = round(float(n / non_zero_days), 4) if non_zero_days > 0 else None

        recent_7d = float(clean_vals.tail(7).mean()) if n >= 1 else 0.0
        prior_7d = float(clean_vals.iloc[max(0, n - 14) : max(0, n - 7)].mean()) if n >= 8 else 0.0
        recent_14d = float(clean_vals.tail(14).mean()) if n >= 1 else 0.0
        prior_14d = float(clean_vals.iloc[max(0, n - 28) : max(0, n - 14)].mean()) if n >= 15 else 0.0

        trend_pct = None
        trend_dir = "INSUFFICIENT_DATA"
        if is_discontinued:
            trend_dir = "DISCONTINUED"
        elif n >= 14 and non_zero_days >= 3:
            baseline = prior_7d if n < 28 else prior_14d
            latest = recent_7d if n < 28 else recent_14d
            if baseline > 0.05:
                trend_pct = round(((latest - baseline) / baseline) * 100.0, 2)
                if trend_pct >= 20.0:
                    trend_dir = "INCREASING"
                elif trend_pct <= -20.0:
                    trend_dir = "DECREASING"
                else:
                    trend_dir = "STABLE"
            elif latest > 0.25:
                trend_dir = "INCREASING"
                trend_pct = 100.0
            else:
                trend_dir = "STABLE"
                trend_pct = 0.0

        positive_dates = ordered.loc[non_zero_mask, "date"]
        last_sale_ts = positive_dates.max() if not positive_dates.empty else None
        start_ts = ordered["date"].min()
        end_ts = ordered["date"].max()
        days_since_last = int((end_ts - last_sale_ts).days) if last_sale_ts is not None else None

        is_intermittent = (adi is not None and adi >= 1.32) or zero_ratio >= 0.40

        if is_discontinued:
            sufficiency = "DISCONTINUED" if non_zero_days > 0 else "NEW"
        elif n < 7 or non_zero_days == 0:
            sufficiency = "NEW"
        elif n < 30:
            sufficiency = "LIMITED"
        elif is_intermittent and non_zero_days < 35:
            sufficiency = "INTERMITTENT"
        elif n >= 56 and non_zero_days >= 20:
            sufficiency = "SEASONAL"
        elif is_intermittent:
            sufficiency = "INTERMITTENT"
        else:
            sufficiency = "ESTABLISHED"

        return {
            "history_days_observed": n,
            "available_history_years": round(n / 365.25, 2),
            "valid_observation_days": valid_obs_days,
            "non_zero_demand_days": non_zero_days,
            "zero_demand_days": zero_days,
            "actual_zero_demand_days": actual_zero_days,
            "no_recorded_transaction_days": no_tx_days,
            "product_unavailable_days": unavail_days,
            "missing_historical_days": missing_days,
            "stockout_days_count": stockout_days,
            "outlier_days_count": outlier_days,
            "outlier_frequency": outlier_freq,
            "missing_date_pct": missing_pct,
            "data_completeness_pct": completeness_pct,
            "zero_demand_ratio": zero_ratio,
            "zero_demand_frequency": zero_ratio,
            "stockout_frequency": stockout_freq,
            "stockout_uncertainty": stockout_uncertainty,
            "total_units_sold": round(float(raw_vals.sum()), 2),
            "avg_daily_demand": round(effective_mean, 4),
            "demand_std_dev": round(std_all, 4),
            "avg_weekly_demand": round(effective_mean * 7.0, 2),
            "avg_monthly_demand": round(effective_mean * 30.0, 2),
            "cv": cv,
            "adi": adi,
            "is_intermittent": is_intermittent,
            "is_discontinued": is_discontinued,
            "recent_7d_avg": round(recent_7d, 4),
            "prior_7d_avg": round(prior_7d, 4),
            "recent_14d_avg": round(recent_14d, 4),
            "prior_14d_avg": round(prior_14d, 4),
            "trend_pct_change": trend_pct,
            "trend_direction": trend_dir,
            "training_start_date": start_ts.strftime("%Y-%m-%d") if pd.notna(start_ts) else None,
            "training_end_date": end_ts.strftime("%Y-%m-%d") if pd.notna(end_ts) else None,
            "last_sale_date": last_sale_ts.strftime("%Y-%m-%d") if last_sale_ts is not None else None,
            "days_since_last_sale": days_since_last,
            "data_sufficiency": sufficiency,
            "unit": getattr(product, "unit", "piece") if product is not None else "piece",
            "synthetic_records_count": synth_sales,
            "genuine_records_count": max(0, total_sales_rows - synth_sales),
            "has_synthetic_data": has_synth,
            "synthetic_ratio": round(synth_sales / total_sales_rows, 4) if total_sales_rows > 0 else (1.0 if product_is_synth else 0.0),
            "receipts_count": len(receipts_df) if receipts_df is not None else 0,
            "ledger_entries_count": len(stock_logs_df) if stock_logs_df is not None else 0,
        }
