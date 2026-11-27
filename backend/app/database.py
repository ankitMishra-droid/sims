import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")

DEFAULT_DB_FILE = (BASE_DIR / "inventory.db").as_posix()


def normalize_database_url(raw_url: str | None) -> str:
    """Normalize local SQLite or Render/Supabase PostgreSQL URLs for SQLAlchemy 2+."""
    url = (raw_url or f"sqlite:///{DEFAULT_DB_FILE}").strip().strip('"').strip("'")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def get_connect_args(url: str) -> dict:
    """Build dialect-appropriate connection arguments including Supabase SSL enforcement."""
    if is_sqlite_url(url):
        return {"check_same_thread": False}

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    connect_args: dict = {}

    explicit_sslmode = os.getenv("DB_SSLMODE", "").strip()
    if explicit_sslmode:
        connect_args["sslmode"] = explicit_sslmode
    elif "sslmode" not in query_params:
        host = (parsed.hostname or "").lower()
        if host not in {"", "localhost", "127.0.0.1", "::1"}:
            connect_args["sslmode"] = "require"

    return connect_args


def get_engine_kwargs(url: str) -> dict:
    """Return engine pooling kwargs suited for SQLite or managed Supabase PostgreSQL."""
    kwargs: dict = {
        "connect_args": get_connect_args(url),
        "pool_pre_ping": True,
    }
    if is_sqlite_url(url):
        return kwargs

    use_null_pool = os.getenv("DB_USE_NULL_POOL", "false").strip().lower() in {"1", "true", "yes"}
    if use_null_pool:
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
        kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "300"))
    return kwargs


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL"))
engine = create_engine(DATABASE_URL, **get_engine_kwargs(DATABASE_URL))


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Configure per-connection safeguards for SQLite and UTC timezone on PostgreSQL."""
    module_name = dbapi_connection.__class__.__module__
    if module_name.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
    elif module_name.startswith("psycopg2"):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health(target_engine: Engine = engine) -> bool:
    """Verify active database connectivity with a lightweight SELECT 1 probe."""
    with target_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
