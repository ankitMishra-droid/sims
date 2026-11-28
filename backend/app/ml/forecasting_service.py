from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.intelligence import ModelEvaluation, ModelTrainingRun, ProductForecast
from ..models.products import Product
from ..models.sales import Sale
from .evaluation_service import (
    MODEL_VERSION,
    PRIMARY_DISPLAY_MAP,
    PRIMARY_ROSTER_ORDER,
    ModelEvaluationService,
)
from .ingestion_service import DataIngestionService
from .models import ColdStartForecaster
from .preprocess_service import DataPreprocessingService, MAX_HISTORY_LOOKBACK_DAYS

logger = logging.getLogger("sims.ml.forecasting")

MODEL_ARTIFACTS_DIR = Path(
    os.getenv(
        "MODEL_ARTIFACTS_DIR",
        str(Path(__file__).resolve().parents[2] / "artifacts" / "models"),
    )
)

_LOCKS_MUTEX = threading.Lock()
_TRAINING_LOCKS: Dict[Tuple[int, int, int], threading.RLock] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_training_lock(business_id: int, product_id: int, horizon_days: int) -> threading.RLock:
    key = (business_id, product_id, horizon_days)
    with _LOCKS_MUTEX:
        lock = _TRAINING_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _TRAINING_LOCKS[key] = lock
        return lock


class ForecastingService:
    """
    Production Demand Forecasting Orchestrator:
    - Enforces strict tenant isolation (business_id) across DB queries and artifact paths.
    - Uses 0-7 year continuous calendar series with stockout, receipt, price, and promo signals.
    - Applies Level 1-4 hierarchical fallback without cross-tenant raw data leakage.
    - Uses single-flight concurrency locks and versioned dataset+model caching.
    """

    @staticmethod
    def _get_scoped_product(
        db: Session,
        product_id: int,
        business_id: Optional[int],
    ) -> Product:
        query = db.query(Product).filter(Product.id == product_id)
        if business_id is not None:
            query = query.filter(Product.business_id == business_id)
        product = query.first()
        if not product:
            raise ValueError(f"Product ID {product_id} not found.")
        return product

    @staticmethod
    def _get_latest_sale_marker(
        db: Session,
        business_id: int,
        product_id: int,
    ) -> tuple[Optional[datetime], int]:
        row = (
            db.query(func.max(Sale.sales_date), func.count(Sale.id))
            .filter(
                Sale.business_id == business_id,
                Sale.product_id == product_id,
                func.upper(func.coalesce(Sale.status, "COMPLETED")) != "CANCELLED",
            )
            .first()
        )
        if not row:
            return None, 0
        return row[0], row[1] or 0

    @staticmethod
    def resolve_artifact_path(
        business_id: int,
        product_id: int,
        horizon_days: int,
        dataset_version: str,
    ) -> Path:
        tenant_dir = MODEL_ARTIFACTS_DIR / f"tenant_{business_id}"
        tenant_dir.mkdir(parents=True, exist_ok=True)
        safe_ver = "".join(ch for ch in (dataset_version or "v0") if ch.isalnum() or ch in ("_", "-"))
        return tenant_dir / f"product_{product_id}_h{horizon_days}_{safe_ver}_{MODEL_VERSION}.json"

    @classmethod
    def _write_artifact(
        cls,
        *,
        business_id: int,
        product_id: int,
        horizon_days: int,
        dataset_version: str,
        payload: Dict[str, Any],
    ) -> Optional[str]:
        try:
            artifact_path = cls.resolve_artifact_path(
                business_id=business_id,
                product_id=product_id,
                horizon_days=horizon_days,
                dataset_version=dataset_version,
            )
            artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return f"tenant_{business_id}/{artifact_path.name}"
        except OSError as exc:
            logger.warning("Could not write tenant forecast artifact (%s)", exc)
            return None

    @classmethod
    def prepare_product_series(
        cls,
        db: Session,
        product: Product,
        as_of_date: Optional[datetime | date] = None,
    ) -> tuple[pd.DataFrame, Dict[str, Any]]:
        cutoff_dt = (
            _utcnow()
            if as_of_date is None
            else (
                as_of_date
                if isinstance(as_of_date, datetime)
                else datetime(as_of_date.year, as_of_date.month, as_of_date.day, 23, 59, 59)
            )
        )
        raw_df = DataIngestionService.load_from_database(
            db,
            business_id=product.business_id,
            product_id=product.id,
            as_of_date=cutoff_dt,
        )
        stock_logs_df = DataIngestionService.load_stock_ledger_for_product(
            db,
            business_id=product.business_id,
            product_id=product.id,
            as_of_date=cutoff_dt,
        )
        receipts_df = DataIngestionService.load_purchase_receipt_context(
            db,
            business_id=product.business_id,
            product_id=product.id,
            as_of_date=cutoff_dt,
        )
        daily_df = DataPreprocessingService.prepare_daily_series(
            raw_df,
            product_id=product.id,
            as_of_date=cutoff_dt,
            product_created_at=getattr(product, "created_at", None),
            stock_logs_df=stock_logs_df,
            receipts_df=receipts_df,
            current_stock=getattr(product, "current_stock", None),
            default_selling_price=getattr(product, "selling_price", None),
            is_product_active=product.is_active,
            lookback_cap_days=MAX_HISTORY_LOOKBACK_DAYS,
        )
        profile = DataPreprocessingService.analyze_demand_profile(
            daily_df,
            product=product,
            raw_df=raw_df,
            receipts_df=receipts_df,
            stock_logs_df=stock_logs_df,
        )
        profile["dataset_version"] = DataPreprocessingService.compute_dataset_version(
            daily_df,
            business_id=product.business_id,
            product_id=product.id,
            cutoff_dt=cutoff_dt,
        )
        if profile["data_sufficiency"] in {"NEW", "LIMITED"}:
            cat_ctx = DataIngestionService.load_category_benchmark_context(
                db,
                business_id=product.business_id,
                category=getattr(product, "category", None),
                exclude_product_id=product.id,
                as_of_date=cutoff_dt,
            )
            profile["_category_benchmark"] = cat_ctx
        else:
            profile["_category_benchmark"] = {}
        return daily_df, profile

    @classmethod
    def _build_historical_chart_points(
        cls,
        daily_df: pd.DataFrame,
        max_points: int = 180,
    ) -> List[Dict[str, Any]]:
        pts, _ = cls._build_historical_chart_window(daily_df, history_days=max_points, history_resolution="daily")
        return pts

    @classmethod
    def _build_historical_chart_window(
        cls,
        daily_df: pd.DataFrame,
        *,
        history_days: Optional[int] = 180,
        history_start_date: Optional[date | datetime] = None,
        history_end_date: Optional[date | datetime] = None,
        history_resolution: str = "auto",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if daily_df is None or daily_df.empty:
            return [], {
                "history_days_requested": history_days,
                "resolution_used": "daily",
                "points_returned": 0,
                "displayed_start_date": None,
                "displayed_end_date": None,
                "available_min_date": None,
                "available_max_date": None,
                "available_total_days": 0,
                "y_axis_unit": "units/day",
            }

        ordered = daily_df.sort_values("date").copy()
        ordered["date"] = pd.to_datetime(ordered["date"]).dt.normalize()
        avail_min_ts = pd.Timestamp(ordered["date"].min())
        avail_max_ts = pd.Timestamp(ordered["date"].max())
        avail_total = len(ordered)

        if history_start_date is not None or history_end_date is not None:
            start_ts = pd.Timestamp(history_start_date).normalize() if history_start_date is not None else avail_min_ts
            end_ts = pd.Timestamp(history_end_date).normalize() if history_end_date is not None else avail_max_ts
            if start_ts > end_ts:
                raise ValueError("history_start_date must be earlier than or equal to history_end_date.")
            sliced = ordered[(ordered["date"] >= start_ts) & (ordered["date"] <= end_ts)].copy()
        elif history_days is not None and history_days > 0:
            cutoff_start = avail_max_ts - pd.Timedelta(days=history_days - 1)
            sliced = ordered[ordered["date"] >= cutoff_start].copy()
        else:
            sliced = ordered.copy()

        if sliced.empty:
            return [], {
                "history_days_requested": history_days,
                "resolution_used": "daily" if history_resolution == "auto" else history_resolution,
                "points_returned": 0,
                "displayed_start_date": None,
                "displayed_end_date": None,
                "available_min_date": avail_min_ts.strftime("%Y-%m-%d"),
                "available_max_date": avail_max_ts.strftime("%Y-%m-%d"),
                "available_total_days": avail_total,
                "y_axis_unit": "units/day",
            }

        disp_min_ts = pd.Timestamp(sliced["date"].min())
        disp_max_ts = pd.Timestamp(sliced["date"].max())
        span_days = max(1, (disp_max_ts - disp_min_ts).days + 1)

        if history_resolution == "auto":
            if span_days <= 180:
                res_used = "daily"
            elif span_days <= 1095:
                res_used = "weekly"
            else:
                res_used = "monthly"
        else:
            res_used = history_resolution

        points: List[Dict[str, Any]] = []
        if res_used == "daily":
            for _, row in sliced.iterrows():
                raw_val = round(float(row["raw_demand"]), 2)
                points.append(
                    {
                        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                        "actual_demand": raw_val,
                        "cleaned_demand": round(float(row["demand"]), 2),
                        "total_demand": raw_val,
                        "bucket_days": 1,
                        "is_stockout_day": bool(row.get("is_stockout_day", False)),
                        "stockout_days": 1 if bool(row.get("is_stockout_day", False)) else 0,
                        "day_state": str(row.get("day_state", "NO_RECORDED_TRANSACTION")),
                        "is_promo_day": bool(row.get("is_promo_day", False)),
                        "is_festive_window": bool(row.get("is_festive_window", False)),
                    }
                )
        else:
            bucket_keys: List[str] = []
            for d_val in sliced["date"].tolist():
                ts = pd.Timestamp(d_val)
                b_ts = (ts - pd.Timedelta(days=ts.weekday())) if res_used == "weekly" else ts.replace(day=1)
                bucket_keys.append(b_ts.strftime("%Y-%m-%d"))
            sliced["_bucket_date"] = bucket_keys
            has_so = "is_stockout_day" in sliced.columns
            has_promo = "is_promo_day" in sliced.columns
            has_fest = "is_festive_window" in sliced.columns
            for bucket_key, grp in sliced.groupby("_bucket_date", sort=True):
                days_cnt = len(grp)
                so_cnt = int(grp["is_stockout_day"].sum()) if has_so else 0
                promo_cnt = int(grp["is_promo_day"].sum()) if has_promo else 0
                fest_cnt = int(grp["is_festive_window"].sum()) if has_fest else 0
                raw_sum = round(float(grp["raw_demand"].sum()), 2)
                points.append(
                    {
                        "date": str(bucket_key),
                        "actual_demand": round(float(grp["raw_demand"].mean()), 2),
                        "cleaned_demand": round(float(grp["demand"].mean()), 2),
                        "total_demand": raw_sum,
                        "bucket_days": days_cnt,
                        "is_stockout_day": so_cnt > 0,
                        "stockout_days": so_cnt,
                        "day_state": "AGGREGATED_BUCKET",
                        "is_promo_day": promo_cnt > 0,
                        "is_festive_window": fest_cnt > 0,
                    }
                )

        meta = {
            "history_days_requested": history_days,
            "resolution_used": res_used,
            "points_returned": len(points),
            "displayed_start_date": disp_min_ts.strftime("%Y-%m-%d"),
            "displayed_end_date": disp_max_ts.strftime("%Y-%m-%d"),
            "available_min_date": avail_min_ts.strftime("%Y-%m-%d"),
            "available_max_date": avail_max_ts.strftime("%Y-%m-%d"),
            "available_total_days": avail_total,
            "y_axis_unit": "units/day",
        }
        return points, meta

    @staticmethod
    def _data_quality_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "available_history_years": profile.get("available_history_years", 0.0),
            "valid_observation_days": profile.get("valid_observation_days", 0),
            "actual_zero_demand_days": profile.get("actual_zero_demand_days", 0),
            "no_recorded_transaction_days": profile.get("no_recorded_transaction_days", 0),
            "product_unavailable_days": profile.get("product_unavailable_days", 0),
            "missing_historical_days": profile.get("missing_historical_days", 0),
            "outlier_days_count": profile.get("outlier_days_count", 0),
            "outlier_frequency": profile.get("outlier_frequency", 0.0),
            "data_completeness_pct": profile.get("data_completeness_pct", 0.0),
            "missing_date_pct": profile.get("missing_date_pct", 100.0),
            "zero_demand_frequency": profile.get("zero_demand_frequency", 1.0),
            "stockout_frequency": profile.get("stockout_frequency", 0.0),
            "stockout_uncertainty": profile.get("stockout_uncertainty", "UNCONFIRMED_NO_LEDGER"),
            "synthetic_records_count": profile.get("synthetic_records_count", 0),
            "genuine_records_count": profile.get("genuine_records_count", 0),
            "has_synthetic_data": bool(profile.get("has_synthetic_data", False)),
            "synthetic_ratio": profile.get("synthetic_ratio", 0.0),
            "receipts_count": profile.get("receipts_count", 0),
            "ledger_entries_count": profile.get("ledger_entries_count", 0),
            "training_start_date": profile.get("training_start_date"),
            "training_end_date": profile.get("training_end_date"),
        }

    @classmethod
    def _serialize_cached_response(
        cls,
        db: Session,
        cached: ProductForecast,
        product: Product,
        daily_df: Optional[pd.DataFrame],
        *,
        history_days: Optional[int] = 180,
        history_start_date: Optional[date | datetime] = None,
        history_end_date: Optional[date | datetime] = None,
        history_resolution: str = "auto",
    ) -> Dict[str, Any]:
        forecast_series = json.loads(cached.daily_forecast_json or "[]")
        hist_summary = json.loads(cached.historical_summary_json or "{}")
        eval_summary = json.loads(cached.evaluation_summary_json or "{}") if cached.evaluation_summary_json else {}
        data_quality = json.loads(cached.data_quality_json or "{}") if getattr(cached, "data_quality_json", None) else {}
        training_cfg = json.loads(cached.training_config_json or "{}") if getattr(cached, "training_config_json", None) else {}
        expected_total = float(cached.expected_total_demand or 0.0)
        horizon = cached.horizon_days or 30

        persisted_evals = cls.get_persisted_evaluations(db, product.business_id, product.id)
        primary_leaderboard = cls._order_primary_leaderboard(persisted_evals)
        champ_name = cached.champion_model
        champ_display = PRIMARY_DISPLAY_MAP.get(champ_name, eval_summary.get("champion_display_name") or champ_name)
        champ_is_ml = champ_name in PRIMARY_DISPLAY_MAP or champ_name == "AdditiveProphet"
        fallback_used = bool(eval_summary.get("fallback_used", not champ_is_ml))
        if daily_df is not None:
            hist_pts, hist_win_meta = cls._build_historical_chart_window(
                daily_df,
                history_days=history_days,
                history_start_date=history_start_date,
                history_end_date=history_end_date,
                history_resolution=history_resolution,
            )
        else:
            hist_pts, hist_win_meta = [], {}

        return {
            "product_id": product.id,
            "business_id": product.business_id,
            "sku": product.sku,
            "product_name": product.name,
            "category": product.category,
            "unit": product.unit,
            "model_used": champ_name,
            "model_display_name": champ_display,
            "champion_is_ml": champ_is_ml,
            "fallback_used": fallback_used,
            "previous_champion_model": getattr(cached, "previous_champion_model", None),
            "model_version": cached.model_version,
            "dataset_version": getattr(cached, "dataset_version", None),
            "forecast_scope": getattr(cached, "forecast_scope", "workspace_product_horizon"),
            "hierarchical_level": getattr(cached, "hierarchical_level", "LEVEL_1_TENANT_PRODUCT"),
            "has_synthetic_data": cached.is_synthetic_dataset or product.is_synthetic,
            "horizon_days": horizon,
            "expected_total_demand": round(expected_total, 2),
            "avg_predicted_daily_demand": round(expected_total / max(horizon, 1), 3),
            "data_sufficiency": cached.data_sufficiency,
            "is_cold_start": cached.is_cold_start,
            "selection_reason": cached.selection_reason,
            "data_cutoff_date": cached.data_cutoff_date.strftime("%Y-%m-%d"),
            "stockout_days_count": cached.stockout_days_count or 0,
            "training_start_date": eval_summary.get("training_start_date") or hist_summary.get("training_start_date"),
            "training_end_date": eval_summary.get("training_end_date") or hist_summary.get("training_end_date"),
            "backtest_start_date": eval_summary.get("backtest_start_date"),
            "backtest_end_date": eval_summary.get("backtest_end_date"),
            "bias_convention": "Predicted - Actual (+ over-forecast, - under-forecast)",
            "training_config": training_cfg,
            "data_quality": data_quality,
            "historical_summary": hist_summary,
            "historical_series": hist_pts,
            "history_window_meta": hist_win_meta,
            "evaluation_metrics": eval_summary,
            "primary_leaderboard": primary_leaderboard,
            "backtest_comparison": training_cfg.get("backtest_comparison", []),
            "forecast_series": forecast_series,
            "cached": True,
            "generated_at": (cached.updated_at or _utcnow()).isoformat() + "Z",
        }

    @staticmethod
    def _order_primary_leaderboard(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_display: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            disp = r.get("display_name") or PRIMARY_DISPLAY_MAP.get(r.get("model_name", ""))
            if disp in PRIMARY_ROSTER_ORDER:
                by_display[disp] = r
        return [by_display[name] for name in PRIMARY_ROSTER_ORDER if name in by_display]

    @classmethod
    def generate_product_forecast(
        cls,
        db: Session,
        product_id: int,
        horizon_days: int = 30,
        model_choice: str = "auto",
        *,
        business_id: Optional[int] = None,
        force_refresh: bool = False,
        persist: bool = True,
        as_of_date: Optional[datetime | date] = None,
        include_historical_series: bool = True,
        generalized_baseline: Optional[Dict[str, Any]] = None,
        history_days: Optional[int] = 180,
        history_start_date: Optional[date | datetime] = None,
        history_end_date: Optional[date | datetime] = None,
        history_resolution: str = "auto",
    ) -> Dict[str, Any]:
        if history_start_date is not None and history_end_date is not None:
            if pd.Timestamp(history_start_date).normalize() > pd.Timestamp(history_end_date).normalize():
                raise ValueError("history_start_date must be earlier than or equal to history_end_date.")
        product = cls._get_scoped_product(db, product_id, business_id)
        now = _utcnow()
        cutoff_dt = (
            as_of_date
            if isinstance(as_of_date, datetime)
            else (
                datetime(as_of_date.year, as_of_date.month, as_of_date.day, 23, 59, 59)
                if isinstance(as_of_date, date)
                else now
            )
        )

        lock = _get_training_lock(product.business_id, product.id, horizon_days)
        with lock:
            # Serve persisted auto forecast if current up to cutoff date, version, & latest sale
            if model_choice == "auto" and not force_refresh and as_of_date is None:
                cached = (
                    db.query(ProductForecast)
                    .filter(
                        ProductForecast.business_id == product.business_id,
                        ProductForecast.product_id == product.id,
                        ProductForecast.horizon_days == horizon_days,
                        ProductForecast.model_version == MODEL_VERSION,
                    )
                    .first()
                )
                if cached is not None and cached.data_cutoff_date.date() >= cutoff_dt.date():
                    latest_sale_dt, sale_count = cls._get_latest_sale_marker(
                        db, product.business_id, product.id
                    )
                    hist_meta = json.loads(cached.historical_summary_json or "{}")
                    cached_sale_count = hist_meta.get("_sale_count", -1)
                    cached_init = hist_meta.get("_initial_daily_demand")
                    raw_init = product.initial_daily_demand
                    cur_init = float(raw_init) if raw_init is not None else None
                    no_newer_sale = latest_sale_dt is None or latest_sale_dt <= cached.updated_at
                    if cached_sale_count == sale_count and cached_init == cur_init and no_newer_sale:
                        daily_df = (
                            cls.prepare_product_series(db, product, as_of_date=cutoff_dt)[0]
                            if include_historical_series
                            else None
                        )
                        return cls._serialize_cached_response(
                            db,
                            cached,
                            product,
                            daily_df,
                            history_days=history_days,
                            history_start_date=history_start_date,
                            history_end_date=history_end_date,
                            history_resolution=history_resolution,
                        )

            run_started = _utcnow()
            daily_df, profile = cls.prepare_product_series(db, product, as_of_date=cutoff_dt)
            _, sale_count = cls._get_latest_sale_marker(db, product.business_id, product.id)

            raw_init_cmp = getattr(product, "initial_daily_demand", None)
            init_demand = float(raw_init_cmp) if raw_init_cmp is not None else None
            sufficiency = profile["data_sufficiency"]
            dataset_version = profile["dataset_version"]
            category_benchmark = profile.get("_category_benchmark") or {}
            is_cold_start = sufficiency in {"NEW", "DISCONTINUED"}

            eval_report = None
            hierarchical_level = "LEVEL_1_TENANT_PRODUCT"

            if model_choice == "auto":
                eval_report = ModelEvaluationService.evaluate_all_models(
                    daily_df,
                    target_col="demand",
                    test_days=min(14, max(3, horizon_days // 2)),
                    data_sufficiency=sufficiency,
                    initial_daily_demand=init_demand,
                    category_benchmark=category_benchmark,
                    generalized_baseline=generalized_baseline,
                    horizon_days=horizon_days,
                    dataset_version=dataset_version,
                )
                champion = eval_report["champion_instance"]
                selection_reason = eval_report["selection_reason"]
                leaderboard = eval_report["leaderboard"]
                primary_leaderboard = eval_report.get("primary_leaderboard") or []
                backtest_comparison = eval_report.get("backtest_comparison") or []
                champion_is_ml = bool(eval_report.get("champion_is_ml", False))
                fallback_used = bool(eval_report.get("fallback_used", False))
                champion_display = eval_report.get("champion_display_name") or PRIMARY_DISPLAY_MAP.get(
                    champion.model_name, champion.model_name
                )
                champion_metrics = next((r for r in leaderboard if r.get("is_champion")), {})
            else:
                champion = ModelEvaluationService.build_model_by_name(
                    model_choice,
                    initial_daily_demand=init_demand,
                    category_benchmark=category_benchmark,
                    generalized_baseline=generalized_baseline,
                )
                if champion is None:
                    raise ValueError(f"Unsupported forecast model override: '{model_choice}'")
                is_elig, elig_reason = champion.check_eligibility(daily_df)
                if not is_elig:
                    raise ValueError(elig_reason)
                selection_reason = f"Explicit user/API model selection: {champion.model_name} ({elig_reason})"
                champion_metrics = {}
                primary_leaderboard = []
                backtest_comparison = []
                champion_is_ml = champion.model_name in PRIMARY_DISPLAY_MAP or champion.model_name == "AdditiveProphet"
                fallback_used = not champion_is_ml
                champion_display = PRIMARY_DISPLAY_MAP.get(champion.model_name, champion.model_name)

            # Fit champion on full observed clean history (cold-start safe fallback if numerical failure occurs)
            try:
                champion.fit(daily_df, target_col="demand")
            except Exception as exc:
                logger.warning(
                    "Model %s fit failed for product_id=%s (%s); using ColdStartEstimator.",
                    champion.model_name,
                    product.id,
                    exc,
                )
                champion = ColdStartForecaster(
                    initial_daily_demand=init_demand,
                    category_benchmark=category_benchmark,
                    generalized_baseline=generalized_baseline,
                )
                champion.fit(daily_df, target_col="demand")
                is_cold_start = True
                champion_is_ml = False
                fallback_used = True
                champion_display = "Baseline (Insufficient Data)"
                selection_reason = f"Fallback to ColdStartEstimator after fit issue: {exc}"

            if isinstance(champion, ColdStartForecaster):
                hierarchical_level = getattr(champion, "hierarchy_level_", "LEVEL_4_COLD_START")
                is_cold_start = True

            pred = champion.predict(horizon_days=horizon_days)
            forecast_series = [
                {
                    "date": d,
                    "predicted_demand": p,
                    "lower_bound": lo,
                    "upper_bound": hi,
                }
                for d, p, lo, hi in zip(
                    pred["dates"],
                    pred["predictions"],
                    pred["lower_bounds"],
                    pred["upper_bounds"],
                )
            ]
            expected_total = round(float(sum(pred["predictions"])), 2)
            avg_pred_daily = round(expected_total / max(horizon_days, 1), 3)

            hist_summary = {
                "total_historical_days": profile["history_days_observed"],
                "available_history_years": profile["available_history_years"],
                "non_zero_demand_days": profile["non_zero_demand_days"],
                "zero_demand_days": profile["zero_demand_days"],
                "stockout_days_count": profile["stockout_days_count"],
                "total_units_sold": profile["total_units_sold"],
                "avg_daily_demand": profile["avg_daily_demand"],
                "demand_std_dev": profile["demand_std_dev"],
                "avg_weekly_demand": profile["avg_weekly_demand"],
                "avg_monthly_demand": profile["avg_monthly_demand"],
                "cv": profile["cv"],
                "adi": profile["adi"],
                "trend_pct_change": profile["trend_pct_change"],
                "trend_direction": profile["trend_direction"],
                "training_start_date": profile["training_start_date"],
                "training_end_date": profile["training_end_date"],
                "last_sale_date": profile["last_sale_date"],
                "days_since_last_sale": profile["days_since_last_sale"],
                "max_daily_demand": round(float(daily_df["raw_demand"].max()), 2) if not daily_df.empty else 0.0,
                "_sale_count": sale_count,
                "_initial_daily_demand": init_demand,
            }

            training_start_date = (
                eval_report.get("training_start_date") if eval_report else profile.get("training_start_date")
            )
            training_end_date = (
                eval_report.get("training_end_date") if eval_report else profile.get("training_end_date")
            )
            backtest_start_date = eval_report.get("backtest_start_date") if eval_report else None
            backtest_end_date = eval_report.get("backtest_end_date") if eval_report else None

            eval_summary = {
                "strategy": eval_report["evaluation_strategy"] if eval_report else "manual",
                "folds_evaluated": eval_report["folds_evaluated"] if eval_report else 0,
                "champion_display_name": champion_display,
                "champion_is_ml": champion_is_ml,
                "fallback_used": fallback_used,
                "mae": champion_metrics.get("mae"),
                "mse": champion_metrics.get("mse"),
                "rmse": champion_metrics.get("rmse"),
                "mape": champion_metrics.get("mape"),
                "smape": champion_metrics.get("smape"),
                "wape": champion_metrics.get("wape"),
                "mase": champion_metrics.get("mase"),
                "bias": champion_metrics.get("bias"),
                "bias_pct": champion_metrics.get("bias_pct"),
                "bias_direction": champion_metrics.get("bias_direction"),
                "stability_score": champion_metrics.get("stability_score"),
                "mape_limitation_note": champion_metrics.get("mape_limitation_note"),
                "training_start_date": training_start_date,
                "training_end_date": training_end_date,
                "backtest_start_date": backtest_start_date,
                "backtest_end_date": backtest_end_date,
            }

            data_quality = cls._data_quality_summary(profile)
            training_cfg = {
                "horizon_days": horizon_days,
                "max_history_days": MAX_HISTORY_LOOKBACK_DAYS,
                "model_version": MODEL_VERSION,
                "dataset_version": dataset_version,
                "hierarchical_level": hierarchical_level,
                "backtest_comparison": backtest_comparison,
            }

            previous_champion_model: Optional[str] = None
            if persist and model_choice == "auto":
                if eval_report is not None:
                    ModelEvaluationService.persist_evaluations(
                        db=db,
                        business_id=product.business_id,
                        product_id=product.id,
                        cutoff_dt=cutoff_dt,
                        eval_report=eval_report,
                        horizon_days=horizon_days,
                        dataset_version=dataset_version,
                    )

                existing = (
                    db.query(ProductForecast)
                    .filter(
                        ProductForecast.business_id == product.business_id,
                        ProductForecast.product_id == product.id,
                        ProductForecast.horizon_days == horizon_days,
                    )
                    .first()
                )
                if existing is None:
                    existing = ProductForecast(
                        business_id=product.business_id,
                        product_id=product.id,
                        horizon_days=horizon_days,
                    )
                    db.add(existing)
                else:
                    if existing.champion_model and existing.champion_model != champion.model_name:
                        previous_champion_model = existing.champion_model
                    else:
                        previous_champion_model = existing.previous_champion_model

                run_completed = _utcnow()
                existing.data_cutoff_date = cutoff_dt
                existing.data_sufficiency = sufficiency
                existing.champion_model = champion.model_name
                existing.previous_champion_model = previous_champion_model
                existing.model_version = MODEL_VERSION
                existing.dataset_version = dataset_version
                existing.forecast_scope = "workspace_product_horizon"
                existing.hierarchical_level = hierarchical_level
                existing.selection_reason = selection_reason
                existing.is_cold_start = is_cold_start
                existing.is_synthetic_dataset = bool(profile.get("has_synthetic_data", False))
                existing.history_days_observed = profile["history_days_observed"]
                existing.non_zero_demand_days = profile["non_zero_demand_days"]
                existing.stockout_days_count = profile["stockout_days_count"]
                existing.avg_daily_demand = profile["avg_daily_demand"]
                existing.demand_std_dev = profile["demand_std_dev"]
                existing.cv = profile["cv"]
                existing.adi = profile["adi"]
                existing.expected_total_demand = expected_total
                existing.daily_forecast_json = json.dumps(forecast_series)
                existing.historical_summary_json = json.dumps(hist_summary)
                existing.evaluation_summary_json = json.dumps(eval_summary)
                existing.training_config_json = json.dumps(training_cfg)
                existing.data_quality_json = json.dumps(data_quality)
                existing.champion_selected_at = run_completed
                existing.training_completed_at = run_completed
                existing.updated_at = now

                rel_artifact_path = cls._write_artifact(
                    business_id=product.business_id,
                    product_id=product.id,
                    horizon_days=horizon_days,
                    dataset_version=dataset_version,
                    payload={
                        "business_id": product.business_id,
                        "product_id": product.id,
                        "horizon_days": horizon_days,
                        "model_version": MODEL_VERSION,
                        "dataset_version": dataset_version,
                        "champion_model": champion.model_name,
                        "champion_display_name": champion_display,
                        "previous_champion_model": previous_champion_model,
                        "hierarchical_level": hierarchical_level,
                        "training_start_date": training_start_date,
                        "training_end_date": training_end_date,
                        "backtest_start_date": backtest_start_date,
                        "backtest_end_date": backtest_end_date,
                        "expected_total_demand": expected_total,
                    },
                )

                db.add(
                    ModelTrainingRun(
                        business_id=product.business_id,
                        product_id=product.id,
                        horizon_days=horizon_days,
                        forecast_scope="workspace_product_horizon",
                        status="COMPLETED",
                        dataset_version=dataset_version,
                        model_version=MODEL_VERSION,
                        champion_model=champion.model_name,
                        previous_champion_model=previous_champion_model,
                        selection_reason=selection_reason,
                        candidate_models_json=json.dumps(
                            [
                                {
                                    "model_name": r.get("model_name"),
                                    "display_name": r.get("display_name"),
                                    "status": r.get("status"),
                                    "wape": r.get("wape"),
                                    "mae": r.get("mae"),
                                    "bias": r.get("bias"),
                                }
                                for r in (eval_report["leaderboard"] if eval_report else [])
                            ]
                        ),
                        training_config_json=json.dumps(training_cfg),
                        artifact_path=rel_artifact_path,
                        started_at=run_started,
                        completed_at=run_completed,
                    )
                )

                db.commit()
                db.refresh(existing)

            if include_historical_series:
                hist_pts, hist_win_meta = cls._build_historical_chart_window(
                    daily_df,
                    history_days=history_days,
                    history_start_date=history_start_date,
                    history_end_date=history_end_date,
                    history_resolution=history_resolution,
                )
            else:
                hist_pts, hist_win_meta = [], {}

            return {
                "product_id": product.id,
                "business_id": product.business_id,
                "sku": product.sku,
                "product_name": product.name,
                "category": product.category,
                "unit": product.unit,
                "model_used": champion.model_name,
                "model_display_name": champion_display,
                "champion_is_ml": champion_is_ml,
                "fallback_used": fallback_used,
                "previous_champion_model": previous_champion_model,
                "model_version": MODEL_VERSION,
                "dataset_version": dataset_version,
                "forecast_scope": "workspace_product_horizon",
                "hierarchical_level": hierarchical_level,
                "has_synthetic_data": bool(profile.get("has_synthetic_data", False)),
                "horizon_days": horizon_days,
                "expected_total_demand": expected_total,
                "avg_predicted_daily_demand": avg_pred_daily,
                "data_sufficiency": sufficiency,
                "is_cold_start": is_cold_start,
                "selection_reason": selection_reason,
                "data_cutoff_date": cutoff_dt.strftime("%Y-%m-%d"),
                "stockout_days_count": profile["stockout_days_count"],
                "training_start_date": training_start_date,
                "training_end_date": training_end_date,
                "backtest_start_date": backtest_start_date,
                "backtest_end_date": backtest_end_date,
                "bias_convention": "Predicted - Actual (+ over-forecast, - under-forecast)",
                "training_config": training_cfg,
                "data_quality": data_quality,
                "historical_summary": hist_summary,
                "historical_series": hist_pts,
                "history_window_meta": hist_win_meta,
                "evaluation_metrics": eval_summary,
                "primary_leaderboard": primary_leaderboard,
                "backtest_comparison": backtest_comparison,
                "forecast_series": forecast_series,
                "cached": False,
                "generated_at": now.isoformat() + "Z",
            }

    @classmethod
    def compare_models_for_product(
        cls,
        db: Session,
        product_id: int,
        test_days: int = 14,
        *,
        business_id: Optional[int] = None,
        persist: bool = True,
        horizon_days: int = 30,
    ) -> Dict[str, Any]:
        product = cls._get_scoped_product(db, product_id, business_id)
        cutoff_dt = _utcnow()
        daily_df, profile = cls.prepare_product_series(db, product, as_of_date=cutoff_dt)
        raw_init_cmp = getattr(product, "initial_daily_demand", None)
        init_demand = float(raw_init_cmp) if raw_init_cmp is not None else None
        dataset_version = profile["dataset_version"]
        eval_report = ModelEvaluationService.evaluate_all_models(
            daily_df,
            target_col="demand",
            test_days=test_days,
            data_sufficiency=profile["data_sufficiency"],
            initial_daily_demand=init_demand,
            category_benchmark=profile.get("_category_benchmark") or {},
            horizon_days=horizon_days,
            dataset_version=dataset_version,
        )
        if persist:
            ModelEvaluationService.persist_evaluations(
                db=db,
                business_id=product.business_id,
                product_id=product.id,
                cutoff_dt=cutoff_dt,
                eval_report=eval_report,
                horizon_days=horizon_days,
                dataset_version=dataset_version,
            )
            db.commit()

        latest_run = cls.get_latest_training_run(db, product.business_id, product.id)

        return {
            "product_id": product.id,
            "business_id": product.business_id,
            "sku": product.sku,
            "product_name": product.name,
            "data_sufficiency": profile["data_sufficiency"],
            "evaluation_strategy": eval_report["evaluation_strategy"],
            "folds_evaluated": eval_report["folds_evaluated"],
            "total_days_observed": profile["history_days_observed"],
            "available_history_years": profile["available_history_years"],
            "non_zero_demand_days": profile["non_zero_demand_days"],
            "train_window_days": eval_report["train_days"],
            "test_window_days": eval_report["test_days"],
            "training_start_date": eval_report.get("training_start_date"),
            "training_end_date": eval_report.get("training_end_date"),
            "backtest_start_date": eval_report.get("backtest_start_date"),
            "backtest_end_date": eval_report.get("backtest_end_date"),
            "model_version": MODEL_VERSION,
            "dataset_version": dataset_version,
            "champion_model": eval_report["champion_model"],
            "champion_display_name": eval_report.get("champion_display_name"),
            "champion_is_ml": eval_report.get("champion_is_ml", False),
            "fallback_used": eval_report.get("fallback_used", False),
            "previous_champion_model": latest_run.get("previous_champion_model") if latest_run else None,
            "selection_reason": eval_report["selection_reason"],
            "bias_convention": "Predicted - Actual (+ over-forecast, - under-forecast)",
            "data_quality": cls._data_quality_summary(profile),
            "leaderboard": eval_report["leaderboard"],
            "primary_leaderboard": eval_report.get("primary_leaderboard", []),
            "backtest_comparison": eval_report.get("backtest_comparison", []),
            "failed_models": eval_report["failed_models"],
            "generated_at": cutoff_dt.isoformat() + "Z",
        }

    @classmethod
    def get_persisted_evaluations(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
    ) -> List[Dict[str, Any]]:
        rows = (
            db.query(ModelEvaluation)
            .filter(
                ModelEvaluation.business_id == business_id,
                ModelEvaluation.product_id == product_id,
            )
            .order_by(ModelEvaluation.is_champion.desc(), ModelEvaluation.id.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "model_name": r.model_name,
                "display_name": getattr(r, "display_name", None)
                or PRIMARY_DISPLAY_MAP.get(r.model_name, r.model_name),
                "is_primary_model": r.model_name in PRIMARY_DISPLAY_MAP,
                "is_baseline": r.is_baseline,
                "is_champion": r.is_champion,
                "evaluation_strategy": r.evaluation_strategy,
                "folds_evaluated": r.folds_evaluated,
                "train_window_days": r.train_window_days,
                "test_window_days": r.test_window_days,
                "forecast_horizon_days": getattr(r, "forecast_horizon_days", 30),
                "observations_count": getattr(r, "observations_count", 0),
                "training_start_date": r.training_start_date.strftime("%Y-%m-%d")
                if getattr(r, "training_start_date", None)
                else None,
                "training_end_date": r.training_end_date.strftime("%Y-%m-%d")
                if getattr(r, "training_end_date", None)
                else None,
                "backtest_start_date": r.backtest_start_date.strftime("%Y-%m-%d")
                if getattr(r, "backtest_start_date", None)
                else None,
                "backtest_end_date": r.backtest_end_date.strftime("%Y-%m-%d")
                if getattr(r, "backtest_end_date", None)
                else None,
                "mae": r.mae,
                "mse": getattr(r, "mse", None),
                "rmse": r.rmse,
                "mape": r.mape,
                "smape": r.smape,
                "wape": r.wape,
                "mase": r.mase,
                "bias": getattr(r, "bias", None),
                "stability_score": getattr(r, "stability_score", None),
                "model_version": getattr(r, "model_version", MODEL_VERSION),
                "dataset_version": getattr(r, "dataset_version", None),
                "training_time_seconds": r.training_time_seconds,
                "status": r.status,
                "eligibility_reason": getattr(r, "eligibility_reason", None) or r.notes,
                "notes": r.notes,
                "trained_at": r.trained_at.isoformat() + "Z" if getattr(r, "trained_at", None) else None,
                "evaluated_at": r.evaluated_at.isoformat() + "Z" if r.evaluated_at else None,
            }
            for r in rows
        ]

    @classmethod
    def get_latest_training_run(
        cls,
        db: Session,
        business_id: int,
        product_id: int,
    ) -> Optional[Dict[str, Any]]:
        run = (
            db.query(ModelTrainingRun)
            .filter(
                ModelTrainingRun.business_id == business_id,
                ModelTrainingRun.product_id == product_id,
            )
            .order_by(ModelTrainingRun.id.desc())
            .first()
        )
        if not run:
            return None
        return {
            "id": run.id,
            "horizon_days": run.horizon_days,
            "status": run.status,
            "dataset_version": run.dataset_version,
            "model_version": run.model_version,
            "champion_model": run.champion_model,
            "previous_champion_model": run.previous_champion_model,
            "selection_reason": run.selection_reason,
            "artifact_path": run.artifact_path,
            "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
            "completed_at": run.completed_at.isoformat() + "Z" if run.completed_at else None,
        }
