import sys
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import base, get_db
from app.models.users import User
from app.models.products import Product
from app.models.supplier import Supplier

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(scope="session")
def engine():
    test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    base.metadata.create_all(bind=test_engine)
    return test_engine

@pytest.fixture(scope="function")
def db_session(engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
