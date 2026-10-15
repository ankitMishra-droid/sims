from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import base, engine
from .routers import products, sales, inventory, dashboard, suppliers, purchase_orders

base.metadata.create_all(bind=engine)

app = FastAPI(
    title="StockSangati - Smart Inventory Management System",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router)
app.include_router(sales.router)
app.include_router(inventory.router)
app.include_router(dashboard.router)
app.include_router(suppliers.router)
app.include_router(purchase_orders.router)

@app.get("/")
def home():
    return {"message": "StockSangati Smart Inventory Management System API is running"}