from contextlib import asynccontextmanager
import os
from pathlib import Path
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
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
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("SKIP_DB_MIGRATIONS", "0") != "1":
        ensure_schema_and_backfill(engine)
    yield


app = FastAPI(
    title="StockSangati - Smart Inventory Demand Forecasting Platform",
    description="Integrated Inventory Management & Machine Learning Demand Forecasting Intelligence System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(forecast.router)
app.include_router(decision.router)
app.include_router(simulator.router)
app.include_router(analytics.router)


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
            "5-Algorithm Demand Forecasting (ARIMA, Prophet, RF, XGBoost, LSTM)",
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
        return {
            "status": "ok",
            "database": "connected",
            "dialect": engine.dialect.name,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database health check failed: {exc}",
        )
