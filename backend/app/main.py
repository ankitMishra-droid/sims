from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import time
from uuid import uuid4
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .database import check_database_health, engine
from .db_migrate import ensure_schema_and_backfill
from .models import *  # noqa: F403 - register all SQLAlchemy models
from .routers import (
    products,
    sales,
    inventory,
    dashboard,
    suppliers,
    purchase_orders,
    auth,
    business,
    members,
    onboarding,
    supplier_portal,
    forecast,
    decision,
    simulator,
    analytics,
    intelligence,
    ai,
)
from .services.ai.container import AIRuntimeContainer

_logger = logging.getLogger("sims.http")


def resolve_cors_origins() -> list[str]:
    """Parse explicit allowed CORS origins, refusing open wildcards in production."""
    app_env = (os.getenv("APP_ENV") or os.getenv("ENV") or "development").strip().lower()
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    origins = [item for item in origins if item != "*"]
    if origins:
        return origins
    if app_env == "production":
        frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
        return [frontend_url] if frontend_url and frontend_url != "*" else []
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("SKIP_DB_MIGRATIONS", "0") != "1":
        ensure_schema_and_backfill(engine)
    ai_container = getattr(_app.state, "ai_container_override", None) or AIRuntimeContainer.from_env()
    ai_container.startup()
    _app.state.ai_container = ai_container
    try:
        yield
    finally:
        ai_container.shutdown()
        _app.state.ai_container = None


app = FastAPI(
    title="StockSangati - Smart Inventory Demand Forecasting Platform",
    description="Integrated Inventory Management & Machine Learning Demand Forecasting Intelligence System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Business-Id", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.middleware("http")
async def security_and_correlation_middleware(request: Request, call_next):
    request_id = (request.headers.get("X-Request-ID") or "").strip()[:64] or str(uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if (os.getenv("APP_ENV") or "").strip().lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/auth"):
        response.headers["Cache-Control"] = "no-store"

    _logger.info(
        "http_request method=%s path=%s status=%s latency_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    _logger.exception("Unhandled error path=%s request_id=%s", request.url.path, request_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected internal error occurred.",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )

# Authentication & Workspace Governance Routers
app.include_router(auth.router)
app.include_router(business.router)
app.include_router(members.router)
app.include_router(onboarding.router)
app.include_router(supplier_portal.router)

# Operational ERP Routers
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(inventory.router)
app.include_router(dashboard.router)
app.include_router(suppliers.router)
app.include_router(purchase_orders.router)

# Machine Learning & Decision Intelligence Routers
app.include_router(intelligence.router)
app.include_router(forecast.router)
app.include_router(decision.router)
app.include_router(simulator.router)
app.include_router(analytics.router)

# AI Infrastructure Router
app.include_router(ai.router)


@app.get("/")
def home():
    return {
        "system": "StockSangati Smart Inventory Demand Forecasting Platform",
        "status": "operational",
        "version": "1.0.0",
        "features": [
            "User Authentication & RBAC",
            "Inventory & Stock Tracking",
            "Purchase Orders & Receiving Lifecycle",
            "4-Algorithm Demand Forecasting (ARIMA, XGBoost, Random Forest, LSTM)",
            "Safety Stock & Dynamic Reorder Points",
            "What-If Business Scenario Simulator",
            "Demand Spike & Anomaly Detection"
        ]
    }


@app.get("/health")
def health_check():
    """Render/uptime health check verifying database connectivity."""
    try:
        check_database_health(engine)
        container = getattr(app.state, "ai_container", None)
        ai_summary = (
            {
                "gemini_configured": container.gemini_client.is_configured,
                "qdrant_configured": container.qdrant_service.is_configured,
            }
            if container is not None
            else {"gemini_configured": False, "qdrant_configured": False}
        )
        return {
            "status": "ok",
            "database": "connected",
            "dialect": engine.dialect.name,
            "ai": ai_summary,
        }
    except Exception:
        _logger.exception("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database health check failed.",
        )


@app.get("/health/ready")
def readiness_check():
    """Readiness probe reporting database connectivity and initialized subsystems."""
    try:
        db_info = check_database_health(engine)
    except Exception:
        _logger.exception("Database readiness check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service dependencies unavailable.",
        )
    container = getattr(app.state, "ai_container", None)
    return {
        "status": "ready",
        "database": db_info,
        "ai_subsystem_initialized": container is not None and container.health_service is not None,
    }
