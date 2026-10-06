import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inventory.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite')
    else{}
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