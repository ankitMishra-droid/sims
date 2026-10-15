import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_FILE = (BASE_DIR / "inventory.db").as_posix()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_FILE}")

# Render provides 'postgres://' or 'postgresql://'.
# SQLAlchemy 2+ requires explicit driver 'postgresql+psycopg2://' when using psycopg2.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {},
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

base = declarative_base()

def get_db():
    # STEP 1: Setup
    db = SessionLocal()
    print("1. Database connection opened!")
    try:
        # STEP 2: Handoff
        yield db
        # ⏸️ The function PAUSES right here! 
        # FastAPI takes this 'db' session and hands it to your API route.
        # Your API route runs its code, reads/writes data, and finishes.
    finally:
        # STEP 3: Cleanup
        # ▶️ The API route is done! FastAPI jumps back here to resume.
        db.close()
        print("3. Database connection closed safely!")