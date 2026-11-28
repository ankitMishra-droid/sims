from datetime import date
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles
from ..ml.decision_service import InventoryDecisionService
from ..ml.forecasting_service import ForecastingService
from ..ml.lead_time_service import SupplierLeadTimeService
from ..ml.recommendation_service import RecommendationLifecycleService
from ..models.products import Product

router = APIRouter(
    prefix="/api/intelligence",
    tags=["Inventory Intelligence"],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]
WRITE_ROLES = ["admin", "manager", "analyst"]
PO_WRITE_ROLES = ["admin", "manager"]


def _require_intelligence_access(allowed_roles: List[str]):
    role_dep = require_business_roles(allowed_roles)

    def checker(ctx: BusinessContext = Depends(role_dep)) -> BusinessContext:
        if (ctx.business.business_type or "").lower() == "supplier":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inventory forecasting and replenishment endpoints apply to retailer/wholesaler workspaces.",
            )
        return ctx

    return checker


class RefreshForecastsRequest(BaseModel):
    product_id: Optional[int] = None
    horizon_days: int = Field(30, ge=7, le=90)
    sync_recommendations: bool = True


class AcceptRecommendationRequest(BaseModel):
    adjusted_order_qty: Optional[int] = Field(None, gt=0)


class DismissRecommendationRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class ConvertRecommendationPORequest(BaseModel):
    supplier_id: Optional[int] = None
    ordered_quantity: Optional[int] = Field(None, gt=0)
    expected_delivery_date: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)
    confirmed: bool = True


def _require_workspace_product(db: Session, product_id: int, business_id: int) -> Product:
    prod = (
        db.query(Product)
        .filter(Product.id == product_id, Product.business_id == business_id)
        .first()
    )
    if not prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in workspace")
    return prod


@router.get("/overview")
def get_intelligence_overview(
    service_level: Annotated[Optional[float], Query(ge=0.80, le=0.999)] = None,
    sync: Annotated[bool, Query()] = True,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Unified tenant-isolated intelligence overview across forecasts, risks, recommendations, and suppliers."""
    decisions = InventoryDecisionService.get_all_recommendations(
        db=db, service_level=service_level, business_id=ctx.business_id
    )
    if sync:
        recs = RecommendationLifecycleService.sync_workspace_recommendations(
            db,
            business_id=ctx.business_id,
            service_level=service_level,
            decisions=decisions,
        )
    else:
        recs = RecommendationLifecycleService.list_recommendations(
            db, business_id=ctx.business_id, status_filter="OPEN"
        )
    supplier_stats = SupplierLeadTimeService.get_all_suppliers_lead_time_report(
        db=db, business_id=ctx.business_id
    )

    sufficiency_counts: dict[str, int] = {}
    stockout_risk_counts = {"CRITICAL": 0, "HIGH": 0, "OPTIMAL": 0, "OVERSTOCK": 0}
    total_excess_value = 0.0
    total_reorder_cost = 0.0
    reorder_candidates = 0

    for d in decisions:
        tier = d.get("data_sufficiency", "NEW")
        sufficiency_counts[tier] = sufficiency_counts.get(tier, 0) + 1
        sr = d.get("stockout_risk", "OPTIMAL")
        stockout_risk_counts[sr] = stockout_risk_counts.get(sr, 0) + 1
        total_excess_value += float(d.get("excess_inventory_value") or 0.0)
        if d.get("recommended_order_quantity", 0) > 0:
            reorder_candidates += 1
            total_reorder_cost += float(d.get("estimated_order_cost") or 0.0)

    open_recs = [r for r in recs if r["status"] in ("NEW", "VIEWED", "ACCEPTED")]
    return {
        "status": "success",
        "data": {
            "business_id": ctx.business_id,
            "total_active_products": len(decisions),
            "sufficiency_breakdown": sufficiency_counts,
            "stockout_risk_breakdown": stockout_risk_counts,
            "open_recommendations_count": len(open_recs),
            "reorder_candidates_count": reorder_candidates,
            "estimated_reorder_investment": round(total_reorder_cost, 2),
            "overstock_capital_tied_up": round(total_excess_value, 2),
            "high_delay_risk_suppliers": sum(1 for s in supplier_stats if s.get("delay_risk") == "HIGH"),
            "top_recommendations": open_recs[:10],
            "supplier_lead_times": supplier_stats[:10],
        },
    }


@router.get("/forecasts")
def list_workspace_forecasts(
    horizon_days: Annotated[int, Query(ge=7, le=90)] = 30,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """List latest forecast snapshots across active workspace products."""
    products = (
        db.query(Product)
        .filter(Product.business_id == ctx.business_id, Product.is_active.is_(True))
        .order_by(Product.id.asc())
        .all()
    )
    items = []
    for prod in products:
        f = ForecastingService.generate_product_forecast(
            db=db,
            product_id=prod.id,
            horizon_days=horizon_days,
            model_choice="auto",
            business_id=ctx.business_id,
            include_historical_series=False,
        )
        items.append(
            {
                "product_id": f["product_id"],
                "sku": f["sku"],
                "product_name": f["product_name"],
                "category": f.get("category"),
                "unit": f["unit"],
                "model_used": f["model_used"],
                "model_display_name": f.get("model_display_name", f["model_used"]),
                "champion_is_ml": f.get("champion_is_ml", False),
                "fallback_used": f.get("fallback_used", False),
                "previous_champion_model": f.get("previous_champion_model"),
                "model_version": f.get("model_version"),
                "dataset_version": f.get("dataset_version"),
                "has_synthetic_data": f.get("has_synthetic_data", False),
                "data_sufficiency": f["data_sufficiency"],
                "is_cold_start": f["is_cold_start"],
                "horizon_days": f["horizon_days"],
                "expected_total_demand": f["expected_total_demand"],
                "avg_predicted_daily_demand": f["avg_predicted_daily_demand"],
                "data_cutoff_date": f["data_cutoff_date"],
                "stockout_days_count": f["stockout_days_count"],
                "historical_summary": f["historical_summary"],
                "evaluation_metrics": f["evaluation_metrics"],
                "cached": f["cached"],
                "generated_at": f["generated_at"],
            }
        )
    return {"status": "success", "total_count": len(items), "data": items}


@router.get("/forecasts/{product_id}")
def get_product_intelligence_forecast(
    product_id: int,
    horizon_days: Annotated[int, Query(ge=7, le=90)] = 30,
    model: Annotated[str, Query()] = "auto",
    force_refresh: Annotated[bool, Query()] = False,
    history_days: Annotated[Optional[int], Query(ge=0, le=3653, description="History window days for chart (0 = all up to 10Y)")] = 180,
    history_start_date: Annotated[Optional[date], Query(description="Custom history chart start date (YYYY-MM-DD)")] = None,
    history_end_date: Annotated[Optional[date], Query(description="Custom history chart end date (YYYY-MM-DD)")] = None,
    history_resolution: Annotated[str, Query(pattern="^(auto|daily|weekly|monthly)$")] = "auto",
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Detailed product forecast with historical demand, stockout context, and model metrics."""
    _require_workspace_product(db, product_id, ctx.business_id)
    try:
        data = ForecastingService.generate_product_forecast(
            db=db,
            product_id=product_id,
            horizon_days=horizon_days,
            model_choice=model,
            business_id=ctx.business_id,
            force_refresh=force_refresh,
            history_days=history_days,
            history_start_date=history_start_date,
            history_end_date=history_end_date,
            history_resolution=history_resolution,
        )
        return {"status": "success", "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/forecasts/refresh")
def refresh_workspace_forecasts(
    req: RefreshForecastsRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(WRITE_ROLES)),
):
    """Force refresh forecast models & rolling-origin evaluations for one or all workspace SKUs."""
    if req.product_id is not None:
        prod = _require_workspace_product(db, req.product_id, ctx.business_id)
        products = [prod]
    else:
        products = (
            db.query(Product)
            .filter(Product.business_id == ctx.business_id, Product.is_active.is_(True))
            .order_by(Product.id.asc())
            .all()
        )

    refreshed = []
    for prod in products:
        f = ForecastingService.generate_product_forecast(
            db=db,
            product_id=prod.id,
            horizon_days=req.horizon_days,
            model_choice="auto",
            business_id=ctx.business_id,
            force_refresh=True,
        )
        refreshed.append({"product_id": prod.id, "model_used": f["model_used"], "data_sufficiency": f["data_sufficiency"]})

    if req.sync_recommendations:
        RecommendationLifecycleService.sync_workspace_recommendations(db, business_id=ctx.business_id)

    return {
        "status": "success",
        "refreshed_count": len(refreshed),
        "data": refreshed,
    }


@router.get("/evaluations/{product_id}")
def get_product_evaluations(
    product_id: int,
    test_days: Annotated[int, Query(ge=3, le=60)] = 14,
    force_refresh: Annotated[bool, Query()] = False,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Chronological rolling-origin CV leaderboard comparing baselines and ML candidates."""
    _require_workspace_product(db, product_id, ctx.business_id)
    if force_refresh:
        comparison = ForecastingService.compare_models_for_product(
            db=db, product_id=product_id, test_days=test_days, business_id=ctx.business_id
        )
        return {"status": "success", "data": comparison}

    persisted = ForecastingService.get_persisted_evaluations(db, ctx.business_id, product_id)
    if persisted:
        champ_row = next((r for r in persisted if r.get("is_champion")), None)
        champ = champ_row["model_name"] if champ_row else None
        primary_leaderboard = ForecastingService._order_primary_leaderboard(persisted)
        latest_run = ForecastingService.get_latest_training_run(db, ctx.business_id, product_id)
        champ_display = (
            champ_row.get("display_name") if champ_row else None
        ) or champ
        champ_is_ml = bool(champ_row and not champ_row.get("is_baseline", True))
        return {
            "status": "success",
            "data": {
                "product_id": product_id,
                "business_id": ctx.business_id,
                "champion_model": champ,
                "champion_display_name": champ_display,
                "champion_is_ml": champ_is_ml,
                "fallback_used": bool(champ_row and champ_row.get("is_baseline", True)),
                "previous_champion_model": latest_run.get("previous_champion_model") if latest_run else None,
                "selection_reason": latest_run.get("selection_reason") if latest_run else None,
                "model_version": (champ_row or {}).get("model_version") or (latest_run or {}).get("model_version"),
                "dataset_version": (champ_row or {}).get("dataset_version") or (latest_run or {}).get("dataset_version"),
                "training_start_date": (champ_row or {}).get("training_start_date"),
                "training_end_date": (champ_row or {}).get("training_end_date"),
                "backtest_start_date": (champ_row or {}).get("backtest_start_date"),
                "backtest_end_date": (champ_row or {}).get("backtest_end_date"),
                "bias_convention": "Predicted - Actual (+ over-forecast, - under-forecast)",
                "leaderboard": persisted,
                "primary_leaderboard": primary_leaderboard,
                "persisted": True,
            },
        }

    comparison = ForecastingService.compare_models_for_product(
        db=db, product_id=product_id, test_days=test_days, business_id=ctx.business_id
    )
    return {"status": "success", "data": comparison}


@router.get("/recommendations")
def list_intelligence_recommendations(
    status_filter: Annotated[str, Query(alias="status")] = "OPEN",
    recommendation_type: Annotated[Optional[str], Query()] = None,
    sync: Annotated[bool, Query()] = True,
    service_level: Annotated[Optional[float], Query(ge=0.80, le=0.999)] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """List persisted, deduplicated, explainable replenishment & risk recommendations."""
    if sync:
        RecommendationLifecycleService.sync_workspace_recommendations(
            db=db, business_id=ctx.business_id, service_level=service_level
        )
    items = RecommendationLifecycleService.list_recommendations(
        db=db,
        business_id=ctx.business_id,
        status_filter=status_filter,
        recommendation_type=recommendation_type,
    )
    return {"status": "success", "total_count": len(items), "data": items}


@router.get("/recommendations/{recommendation_id}")
def get_intelligence_recommendation_detail(
    recommendation_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Inspect detailed explanation and inventory snapshot for one recommendation."""
    rec = RecommendationLifecycleService.get_recommendation(
        db=db,
        business_id=ctx.business_id,
        recommendation_id=recommendation_id,
        mark_viewed=True,
    )
    return {"status": "success", "data": rec}


@router.post("/recommendations/{recommendation_id}/accept")
def accept_intelligence_recommendation(
    recommendation_id: int,
    req: AcceptRecommendationRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(WRITE_ROLES)),
):
    rec = RecommendationLifecycleService.accept_recommendation(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        recommendation_id=recommendation_id,
        adjusted_order_qty=req.adjusted_order_qty,
    )
    return {"status": "success", "data": rec}


@router.post("/recommendations/{recommendation_id}/dismiss")
def dismiss_intelligence_recommendation(
    recommendation_id: int,
    req: DismissRecommendationRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(WRITE_ROLES)),
):
    rec = RecommendationLifecycleService.dismiss_recommendation(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        recommendation_id=recommendation_id,
        reason=req.reason,
    )
    return {"status": "success", "data": rec}


@router.post("/recommendations/{recommendation_id}/convert-to-po", status_code=status.HTTP_201_CREATED)
def convert_intelligence_recommendation_to_po(
    recommendation_id: int,
    req: ConvertRecommendationPORequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(PO_WRITE_ROLES)),
):
    """Create a DRAFT Purchase Order after explicit user review & confirmation."""
    if not req.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit confirmation (confirmed=true) is required to create a purchase order.",
        )
    return RecommendationLifecycleService.convert_recommendation_to_po(
        db=db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        recommendation_id=recommendation_id,
        supplier_id=req.supplier_id,
        ordered_quantity=req.ordered_quantity,
        expected_delivery_date=req.expected_delivery_date,
        notes=req.notes,
    )


@router.get("/stockout-risks")
def get_stockout_risks(
    service_level: Annotated[Optional[float], Query(ge=0.80, le=0.999)] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Products sorted by stockout risk using forecast demand and inventory position."""
    all_items = InventoryDecisionService.get_all_recommendations(
        db=db, service_level=service_level, business_id=ctx.business_id
    )
    risks = [r for r in all_items if r["stockout_risk"] in ("CRITICAL", "HIGH")]
    return {"status": "success", "total_count": len(risks), "data": risks}


@router.get("/overstock-risks")
def get_overstock_risks(
    service_level: Annotated[Optional[float], Query(ge=0.80, le=0.999)] = None,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Products exhibiting excessive cover or dead-stock inactivity."""
    all_items = InventoryDecisionService.get_all_recommendations(
        db=db, service_level=service_level, business_id=ctx.business_id
    )
    risks = [r for r in all_items if r.get("overstock_risk") not in ("NONE", None)]
    risks.sort(key=lambda r: float(r.get("excess_inventory_value") or 0.0), reverse=True)
    return {"status": "success", "total_count": len(risks), "data": risks}


@router.get("/suppliers/lead-times")
def get_suppliers_lead_time_intelligence(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(_require_intelligence_access(READ_ROLES)),
):
    """Empirical supplier lead times, variance, on-time rates, and manual fallback indicators."""
    report = SupplierLeadTimeService.get_all_suppliers_lead_time_report(
        db=db, business_id=ctx.business_id
    )
    return {"status": "success", "total_count": len(report), "data": report}
