import logging
from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app import models
from app.core.rate_limiter import check_rate_limit, extract_client_ip, reset_rate_limits
from app.core.security import validate_jwt_secret
from app.database import _set_sqlite_pragma, base, get_db
from app.main import app, resolve_cors_origins
from app.services.auth import AuthService
from app.services.product_service import ProductService


def _make_client():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False), testing_session


def _auth_headers(token: str, biz_id: int | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if biz_id is not None:
        headers["X-Business-Id"] = str(biz_id)
    return headers


def test_cors_allowlist_and_security_headers(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    assert resolve_cors_origins() == []

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://sims.example.com,*, https://app.example.com/")
    assert resolve_cors_origins() == ["https://sims.example.com", "https://app.example.com"]

    client, _ = _make_client()
    try:
        # Allowed origin in local dev defaults
        ok_preflight = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert ok_preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert ok_preflight.headers.get("access-control-allow-credentials") == "true"

        # Arbitrary evil website rejected by CORS
        evil_res = client.get("/health", headers={"Origin": "https://evil.example"})
        assert evil_res.status_code == 200
        assert evil_res.headers.get("access-control-allow-origin") is None
        assert evil_res.headers.get("x-content-type-options") == "nosniff"
        assert evil_res.headers.get("x-frame-options") == "DENY"
        assert evil_res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert evil_res.headers.get("x-request-id")
    finally:
        app.dependency_overrides.clear()


def test_production_jwt_secret_guard():
    with pytest.raises(RuntimeError):
        validate_jwt_secret("short-secret", app_env="production")
    with pytest.raises(RuntimeError):
        validate_jwt_secret("replace-with-a-production-secret-key-32-chars", app_env="production")
    with pytest.raises(RuntimeError):
        validate_jwt_secret("changeme-please-this-is-32-plus-characters", app_env="production")

    strong = "K9mP4xR7vN2qW8zT5yB1cF6hJ3nL0pQ9sD4uG7jM2wZ"
    assert validate_jwt_secret(strong, app_env="production") == strong


def test_privilege_and_business_type_escalation_blocked():
    client, _ = _make_client()
    try:
        # 1. Public registration without workspace cannot self-grant owner/admin
        reg_staff = client.post(
            "/api/auth/register",
            json={
                "name": "External User",
                "email": "ext@sims.in",
                "password": "Password123!",
                "role": "admin",
                "create_workspace": False,
            },
        )
        assert reg_staff.status_code == 201, reg_staff.text
        assert reg_staff.json()["role"] == "staff"

        # 2. Registering with business_type=supplier even if requesting role=owner forces supplier role
        reg_sup = client.post(
            "/api/auth/register",
            json={
                "name": "Supplier Hub",
                "email": "sup@sims.in",
                "password": "Password123!",
                "role": "owner",
                "business_name": "Vendor Corp",
                "business_type": "supplier",
            },
        )
        assert reg_sup.status_code == 201, reg_sup.text
        sup_tok = client.post(
            "/api/auth/login",
            json={"email": "sup@sims.in", "password": "Password123!"},
        ).json()["access_token"]

        cur_ws = client.get("/api/businesses/current", headers=_auth_headers(sup_tok)).json()
        assert cur_ws["role"] == "supplier"
        assert cur_ws["business"]["business_type"] == "supplier"

        # 3. Supplier cannot mutate business_type to retailer via settings or onboarding
        upd = client.put(
            "/api/businesses/current",
            headers=_auth_headers(sup_tok),
            json={"business_type": "retailer"},
        )
        assert upd.status_code == 400

        onb = client.post(
            "/api/onboarding/step",
            headers=_auth_headers(sup_tok),
            json={"step": 2, "action": "complete", "data": {"business_type": "retailer"}},
        )
        assert onb.status_code == 400

        # 4. All buyer ERP/ML endpoints reject supplier workspace with 403
        for method, path in (
            ("GET", "/api/products/"),
            ("GET", "/api/sales/"),
            ("GET", "/api/inventory/positions"),
            ("GET", "/api/suppliers/"),
            ("GET", "/api/purchase-orders/"),
            ("GET", "/dashboard/summary"),
            ("GET", "/api/decision/recommendations"),
            ("GET", "/api/forecast/1"),
            ("GET", "/api/analytics/anomalies/1"),
        ):
            resp = client.request(method, path, headers=_auth_headers(sup_tok))
            assert resp.status_code == 403, f"Expected 403 for {path}, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


def test_error_responses_sanitize_internal_exceptions(monkeypatch):
    client, _ = _make_client()
    try:
        client.post(
            "/api/auth/register",
            json={
                "name": "Owner",
                "email": "owner@err.in",
                "password": "Password123!",
                "business_name": "Err Store",
            },
        )
        tok = client.post(
            "/api/auth/login",
            json={"email": "owner@err.in", "password": "Password123!"},
        ).json()["access_token"]

        def _boom(*args, **kwargs):
            raise RuntimeError("sqlite3.OperationalError: secret_internal_table_leak")

        monkeypatch.setattr(ProductService, "list_products", _boom)
        res = client.get("/api/products/", headers=_auth_headers(tok))
        assert res.status_code == 500
        assert "secret_internal_table_leak" not in res.text
        assert res.headers.get("x-request-id")
    finally:
        app.dependency_overrides.clear()


def test_rate_limiter_proxy_ip_extraction_and_isolation():
    reset_rate_limits()
    scope_template = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "client": ("10.0.0.1", 12345),
        "headers": [(b"x-forwarded-for", b"203.0.113.10, 10.0.0.1")],
    }
    req_a = Request(scope_template)
    assert extract_client_ip(req_a) == "203.0.113.10"

    req_bad = Request(
        {
            **scope_template,
            "headers": [(b"x-forwarded-for", b"not-an-ip-spoof")],
        }
    )
    assert extract_client_ip(req_bad) == "10.0.0.1"

    check_rate_limit("login:203.0.113.10", max_requests=1, window_seconds=60)
    with pytest.raises(Exception):
        check_rate_limit("login:203.0.113.10", max_requests=1, window_seconds=60)
    # Different client IP behind same proxy is unaffected
    check_rate_limit("login:203.0.113.11", max_requests=1, window_seconds=60)


def test_password_reset_log_masks_email_and_oversized_upload_rejected(caplog, monkeypatch):
    client, _ = _make_client()
    try:
        monkeypatch.setattr(
            AuthService,
            "_dispatch_password_reset_notification",
            AuthService._dispatch_password_reset_notification,
        )
        client.post(
            "/api/auth/register",
            json={
                "name": "Alice",
                "email": "alice.secret@sims.in",
                "password": "Password123!",
                "business_name": "Alice Mart",
            },
        )
        with caplog.at_level(logging.INFO):
            client.post("/api/auth/password-reset/request", json={"email": "alice.secret@sims.in"})
        assert "alice.secret@sims.in" not in caplog.text
        assert "a***@sims.in" in caplog.text

        tok = client.post(
            "/api/auth/login",
            json={"email": "alice.secret@sims.in", "password": "Password123!"},
        ).json()["access_token"]
        monkeypatch.setenv("AI_MAX_DOCUMENT_MB", "1")
        oversized = BytesIO(b"A" * (1024 * 1024 + 64))
        resp = client.post(
            "/api/ai/documents",
            headers=_auth_headers(tok),
            files={"file": ("huge.txt", oversized, "text/plain")},
        )
        assert resp.status_code == 413
    finally:
        app.dependency_overrides.clear()
