from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/products", tags=["Products"])

# Create Product
@router.post("/", response_model=schemas.ProductOut)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Product).filter(models.Product.sku == product.sku).first()

    # if sku is already present in database
    if existing:
        raise(HTTPException(status_code=400, detail="SKU already exists"))

    db_product = models.Product(**product.model_dump()) #this method covert data into dictionary
    db.add(db_product) # store in databse
    db.commit()
    db.refresh(db_product)

    if db_product.current_stock > 0:
        db.add(models.InventoryLog(
            product_id = db_product.id,
            stock_in = db_product.current_stock,
            closing_stock = db_product.current_stock,
            reason="initial_stock"
        ))

        db.commit()

    return db_product

# Fetch product
@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    # find product by id
    product = db.query(models.Product).filter(models.Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="product not found")

    return product

# Update Product
@router.put("/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, updated: schemas.ProductCreate, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="product not found")

    for key, value in updated.model_dump().items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return product

# Delete Product
@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="product not found")

    db.delete(product)
    db.commit()

    return {"detail": "Product Deleted"}