import pytest
from app.core.security import hash_password, verify_password, create_access_token, decode_access_token
from app.services.auth import AuthService
from app.schemas.auth_schema import UserRegisterRequest, UserLoginRequest
from app.models.users import User
from app.core.permissions import UserRole, has_sufficient_permission

def test_password_hashing():
    raw_password = "SecurePassword123!"
    hashed = hash_password(raw_password)
    assert hashed != raw_password
    assert verify_password(raw_password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False

def test_jwt_token_generation_and_decoding():
    data = {"sub": "42", "email": "test@stocksangati.com", "role": "analyst"}
    token = create_access_token(data)
    assert isinstance(token, str)
    assert len(token) > 20

    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["email"] == "test@stocksangati.com"
    assert payload["role"] == "analyst"

def test_role_hierarchy_permissions():
    assert has_sufficient_permission(UserRole.ADMIN, UserRole.ADMIN) is True
    assert has_sufficient_permission(UserRole.ADMIN, UserRole.MANAGER) is True
    assert has_sufficient_permission(UserRole.ADMIN, UserRole.STAFF) is True
    assert has_sufficient_permission(UserRole.STAFF, UserRole.ADMIN) is False
    assert has_sufficient_permission(UserRole.MANAGER, UserRole.ADMIN) is False

def test_user_registration_and_authentication(db_session):
    user_in = UserRegisterRequest(
        name="Test Engineer",
        email="engineer@stocksangati.com",
        password="TestPassword123!",
        role="manager"
    )
    user = AuthService.register_user(db_session, user_in)
    assert user.id is not None
    assert user.email == "engineer@stocksangati.com"
    assert user.role == "manager"

    # Authenticate valid credentials
    login_req = UserLoginRequest(email="engineer@stocksangati.com", password="TestPassword123!")
    auth_user = AuthService.authenticate_user(db_session, login_req)
    assert auth_user.id == user.id

    # Authenticate invalid password should fail
    bad_login = UserLoginRequest(email="engineer@stocksangati.com", password="IncorrectPassword")
    with pytest.raises(Exception):
        AuthService.authenticate_user(db_session, bad_login)
