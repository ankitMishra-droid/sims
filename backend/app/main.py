from fastapi import FastAPI
from .database import base, engine
from . import models
from .routers import products, sales

base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Smart Inventory Management System",
    version="0.1.0"
)

app.include_router(products.router)
app.include_router(sales.router)

@app.get("/")
def home():
    return {"message": "Smart Inventory Management System API is running"}