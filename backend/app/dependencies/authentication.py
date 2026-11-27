from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.users import User, RevokedToken
from ..core.security import decode_access_token

security_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_jwt_user(token: str, expected_type: str, db: Session) -> tuple[User, dict]:
    payload = decode_access_token(token)
    if not payload:
        raise _unauthorized("Invalid or expired authentication token. Please log in again.")

    token_type = payload.get("type", "access")
    if token_type != expected_type:
        raise _unauthorized("Invalid token type for this operation.")

    jti = payload.get("jti")
    if jti:
        revoked = db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first()
        if revoked:
            raise _unauthorized("Session token has been revoked. Please log in again.")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise _unauthorized("Invalid token payload.")

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise _unauthorized("Invalid user identifier in token.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise _unauthorized("User associated with token no longer exists.")

    token_version = payload.get("token_version")
    if token_version is not None and int(token_version) != int(user.token_version or 1):
        raise _unauthorized("Session expired due to security update. Please log in again.")

    return user, payload


def get_current_user(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not auth_credentials or not auth_credentials.credentials:
        raise _unauthorized("Authentication token required. Please log in.")

    user, _ = validate_jwt_user(auth_credentials.credentials, expected_type="access", db=db)
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )
    return current_user
