import hashlib
import os
from pathlib import Path
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
import jwt
from pwdlib import PasswordHash

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_BACKEND_ROOT / ".env")
load_dotenv(_BACKEND_ROOT.parent / ".env")

_APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
_ENV_SECRET = os.getenv("JWT_SECRET_KEY", "").strip()

if _APP_ENV == "production" and len(_ENV_SECRET) < 16:
    raise RuntimeError("JWT_SECRET_KEY environment variable must be set (min 16 chars) in production.")

# In non-production dev/test environments without .env key, generate a fresh per-process ephemeral key
SECRET_KEY = _ENV_SECRET if _ENV_SECRET else secrets.token_urlsafe(32)
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
REFRESH_TOKEN_EXPIRE_MINUTES = int(os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days

# Password hashing instance (Argon2 recommended)
_pwd_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash plaintext password securely using Argon2."""
    return _pwd_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against stored Argon2 hash."""
    return _pwd_hash.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create cryptographically signed JWT access token with unique JTI."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.setdefault("jti", uuid.uuid4().hex)
    to_encode.setdefault("type", "access")
    to_encode.update(
        {
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
    )
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create cryptographically signed JWT refresh token with unique JTI."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["jti"] = uuid.uuid4().hex
    to_encode["type"] = "refresh"
    to_encode.update(
        {
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
    )
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate signature and expiry of JWT token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def generate_reset_token() -> str:
    """Generate a high-entropy URL-safe reset token."""
    return secrets.token_urlsafe(32)


def hash_reset_token(raw_token: str) -> str:
    """Compute SHA-256 hex digest of reset token for safe persistence."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
