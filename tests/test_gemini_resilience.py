"""Comprehensive unit and integration resilience tests for Gemini error classification, retries, deadline, circuit breaker, and assistant UX."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
import threading
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.ai_config import AIProviderSettings
from app.core.ai_exceptions import (
    AIAuthenticationError,
    AICircuitOpenError,
    AIConfigurationError,
    AIErrorCode,
    AIInvalidRequestError,
    AIRateLimitError,
    AIServiceError,
    AITransientError,
    classify_gemini_error,
)
from app.core.ai_logging import redact_sensitive_text
from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db
from app.main import app
from app.services.ai.circuit_breaker import CircuitState, ProviderCircuitBreaker
from app.services.ai.container import AIRuntimeContainer
from app.services.ai.gemini_client import GeminiClientManager
from app.services.ai.gemini_llm import GeminiLLMService
from app.services.ai.qdrant_service import QdrantVectorService
from app.services.ai.retry import execute_with_retry


def _make_settings(**overrides: Any) -> AIProviderSettings:
    defaults: dict[str, Any] = {
        "app_env": "test",
        "gemini_api_key": "AQ.Ab8TestFakeVertexStyleSecretKey99887766",
        "gemini_llm_model": "gemini-3.5-flash-lite",
        "gemini_llm_fallback_models": (),
        "gemini_embedding_model": "gemini-embedding-001",
        "gemini_embedding_dimensions": 128,
        "gemini_embedding_normalize": True,
        "gemini_timeout_seconds": 15.0,
        "gemini_overall_deadline_seconds": 20.0,
        "gemini_max_retries": 2,
        "gemini_retry_base_seconds": 0.05,
        "gemini_retry_max_seconds": 0.5,
        "gemini_circuit_breaker_enabled": True,
        "gemini_circuit_failure_threshold": 3,
        "gemini_circuit_recovery_seconds": 30.0,
        "gemini_circuit_half_open_max_calls": 1,
        "gemini_max_concurrent_requests": 4,
        "gemini_quota_cooldown_seconds": 0.0,
        "qdrant_url": ":memory:",
        "ai_initial_grant_credits": Decimal("1000.0"),
        "ai_initial_grant_approved": True,
    }
    defaults.update(overrides)
    return AIProviderSettings(**defaults)


def _ok_resp(text: str = "OK") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        parsed=None,
        candidates=[
            SimpleNamespace(
                finish_reason="STOP",
                content=SimpleNamespace(parts=[SimpleNamespace(text=text, thought=False)]),
            )
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            thoughts_token_count=0,
            total_token_count=15,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Error Classification Across All Provider & Client Failures
# ---------------------------------------------------------------------------


def test_complete_gemini_error_classification_matrix():
    # Invalid API key (401)
    c_401 = classify_gemini_error(
        genai_errors.APIError(401, {"error": {"status": "UNAUTHENTICATED", "message": "API_KEY_INVALID"}})
    )
    assert isinstance(c_401, AIAuthenticationError)
    assert c_401.error_code == AIErrorCode.AUTHENTICATION_ERROR
    assert c_401.retryable is False

    # Permission denied (403)
    c_403 = classify_gemini_error(
        genai_errors.APIError(403, {"error": {"status": "PERMISSION_DENIED", "message": "Access denied"}})
    )
    assert isinstance(c_403, AIAuthenticationError)
    assert c_403.error_code == AIErrorCode.PERMISSION_DENIED
    assert c_403.retryable is False

    # Invalid / retired model (404)
    c_404 = classify_gemini_error(
        genai_errors.APIError(
            404,
            {"error": {"status": "NOT_FOUND", "message": "models/gemini-2.5-flash is no longer available"}},
        )
    )
    assert isinstance(c_404, AIConfigurationError)
    assert c_404.error_code == AIErrorCode.INVALID_MODEL
    assert c_404.retryable is False

    # HTTP 429 temporary RPM rate limit with Retry-After
    c_rpm = classify_gemini_error(
        genai_errors.APIError(
            429,
            {"error": {"status": "RESOURCE_EXHAUSTED", "message": "PerMinute RPM rate limit exceeded"}},
            response=SimpleNamespace(headers={"Retry-After": "3"}),
        )
    )
    assert isinstance(c_rpm, AIRateLimitError)
    assert c_rpm.error_code == AIErrorCode.RATE_LIMIT_RETRYABLE
    assert c_rpm.retryable is True
    assert c_rpm.retry_after_seconds == pytest.approx(3.0)

    # Real Google `limit: 0` quota message mentioning per minute MUST be non-retryable QUOTA_EXHAUSTED
    c_zero_limit = classify_gemini_error(
        genai_errors.APIError(
            429,
            {
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, per_minute limit exceeded on Free Tier.",
                }
            },
        )
    )
    assert isinstance(c_zero_limit, AIRateLimitError)
    assert c_zero_limit.error_code == AIErrorCode.QUOTA_EXHAUSTED
    assert c_zero_limit.retryable is False

    # HTTP 503 UNAVAILABLE & 504 DEADLINE_EXCEEDED
    c_503 = classify_gemini_error(
        genai_errors.APIError(503, {"error": {"status": "UNAVAILABLE", "message": "High demand"}})
    )
    assert isinstance(c_503, AITransientError)
    assert c_503.error_code == AIErrorCode.TRANSIENT_ERROR
    assert c_503.provider_status == "UNAVAILABLE"
    assert c_503.provider_error_code == 503

    c_504 = classify_gemini_error(
        genai_errors.APIError(504, {"error": {"status": "DEADLINE_EXCEEDED", "message": "Deadline expired"}})
    )
    assert isinstance(c_504, AITransientError)
    assert c_504.error_code == AIErrorCode.TIMEOUT_ERROR
    assert c_504.provider_status == "DEADLINE_EXCEEDED"
    assert c_504.provider_error_code == 504

    # Network timeout & connection failure
    c_to = classify_gemini_error(TimeoutError("socket timeout"))
    assert c_to.error_code == AIErrorCode.TIMEOUT_ERROR and c_to.retryable is True

    c_conn = classify_gemini_error(ConnectionError("reset by peer"))
    assert c_conn.error_code == AIErrorCode.TRANSIENT_ERROR and c_conn.retryable is True

    # Context/token limit
    c_ctx = classify_gemini_error(
        genai_errors.APIError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "The input token count exceeds the maximum number of tokens"}})
    )
    assert isinstance(c_ctx, AIInvalidRequestError)
    assert c_ctx.error_code == AIErrorCode.CONTEXT_LENGTH_EXCEEDED
    assert c_ctx.retryable is False

    # Invalid request vs unknown non-SDK error (must NOT blindly retry unknown bugs as TRANSIENT_ERROR)
    c_400 = classify_gemini_error(
        genai_errors.APIError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "Bad safety parameter"}})
    )
    assert c_400.error_code == AIErrorCode.INVALID_REQUEST and c_400.retryable is False

    c_unknown = classify_gemini_error(RuntimeError("unexpected parser crash"))
    assert c_unknown.error_code == AIErrorCode.PROVIDER_UNKNOWN_ERROR
    assert c_unknown.retryable is False
    assert c_unknown.exception_type == "RuntimeError"

    # AQ secret redaction
    assert "AQ.Ab8RealKeyToken123456" not in redact_sensitive_text("key=AQ.Ab8RealKeyToken123456 failed")


# ---------------------------------------------------------------------------
# 2. Deadline, Cancellation, Fallback & Circuit Breaker State Machine
# ---------------------------------------------------------------------------


def test_retry_deadline_cancellation_and_exhaustion():
    # Deadline exceeded prevents excessive backoff sleep & stops cleanly
    now = [100.0]
    sleeps: List[float] = []

    def _clock():
        return now[0]

    def _sleep(d: float):
        sleeps.append(d)
        now[0] += d

    attempts = 0

    def _always_503():
        nonlocal attempts
        attempts += 1
        now[0] += 4.5
        raise genai_errors.APIError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}})

    with pytest.raises(AITransientError):
        execute_with_retry(
            _always_503,
            classifier=classify_gemini_error,
            max_retries=5,
            base_seconds=1.0,
            max_seconds=5.0,
            deadline_monotonic=106.5,
            sleep_fn=_sleep,
            jitter_fn=lambda a, b: 1.0,
            clock_fn=_clock,
        )
    # 1st attempt took 4.5s -> 1.5s left -> retry 1s -> 2nd attempt ends at 110.0 (> 106 deadline) -> stops before retry 2!
    assert attempts == 2
    assert sleeps == [pytest.approx(1.0)]

    # Shutdown cancellation stops execution immediately
    ev = threading.Event()
    ev.set()
    with pytest.raises(AITransientError):
        execute_with_retry(
            lambda: "never",
            classifier=classify_gemini_error,
            max_retries=3,
            base_seconds=0.1,
            max_seconds=1.0,
            cancel_event=ev,
        )


def test_circuit_breaker_lifecycle_and_concurrency_protection():
    clock = [10.0]
    cb = ProviderCircuitBreaker(
        enabled=True,
        failure_threshold=2,
        recovery_seconds=30.0,
        half_open_max_calls=1,
        max_concurrent_requests=2,
        clock_fn=lambda: clock[0],
    )

    # Auth/invalid errors NEVER trip outage breaker
    cb.record_failure("gemini:m1", AIAuthenticationError("bad key", provider="gemini"))
    cb.record_failure("gemini:m1", AIInvalidRequestError("bad prompt", provider="gemini"))
    assert cb.get_snapshot("gemini:m1")["state"] == CircuitState.CLOSED.value

    # Two transient outages trip breaker OPEN
    cb.record_failure("gemini:m1", AITransientError("503", provider="gemini"))
    cb.record_failure("gemini:m1", AITransientError("504", provider="gemini", error_code=AIErrorCode.TIMEOUT_ERROR))
    assert cb.get_snapshot("gemini:m1")["state"] == CircuitState.OPEN.value

    with pytest.raises(AICircuitOpenError):
        cb.acquire_slot(key="gemini:m1", provider="gemini")

    # After recovery timeout -> transitions to HALF_OPEN, allows 1 probe, blocks 2nd concurrent probe
    clock[0] = 45.0
    assert cb.acquire_slot(key="gemini:m1", provider="gemini") is True
    with pytest.raises(AICircuitOpenError):
        cb.acquire_slot(key="gemini:m1", provider="gemini")

    # Success closes circuit and releases slot cleanly
    cb.record_success("gemini:m1")
    cb.release_slot()
    assert cb.get_snapshot("gemini:m1")["state"] == CircuitState.CLOSED.value

    # Concurrency limit check on semaphore
    assert cb.acquire_slot(key="gemini:m2", provider="gemini") is True
    assert cb.acquire_slot(key="gemini:m2", provider="gemini") is True
    with pytest.raises(AITransientError) as conc_err:
        cb.acquire_slot(key="gemini:m2", provider="gemini", wait_timeout=0.05)
    assert conc_err.value.error_code == AIErrorCode.RATE_LIMIT_RETRYABLE
    cb.release_slot()
    cb.release_slot()


def test_llm_fallback_and_structured_diagnostic_logging(caplog):
    settings = _make_settings(
        gemini_llm_model="gemini-3.8-flash",
        gemini_llm_fallback_models=("gemini-3.5-flash-lite",),
        gemini_max_retries=2,
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        genai_errors.APIError(504, {"error": {"status": "DEADLINE_EXCEEDED", "message": "timeout"}}),
        genai_errors.APIError(504, {"error": {"status": "DEADLINE_EXCEEDED", "message": "timeout"}}),
        _ok_resp("Healthy response from fallback model"),
    ]
    llm = GeminiLLMService(GeminiClientManager(settings, client=mock_client), sleep_fn=lambda _d: None)
    with caplog.at_level(logging.INFO, logger="sims.ai.gemini.llm"):
        res = llm.generate_text("test prompt", tenant_id=3, conversation_id=9, request_id="req-fallback")

    assert res.model == "gemini-3.5-flash-lite"
    assert res.text == "Healthy response from fallback model"
    log_blob = "\n".join(r.getMessage() for r in caplog.records)
    assert '"conversation_id": 9' in log_blob
    assert '"provider_status": "DEADLINE_EXCEEDED"' in log_blob
    assert '"http_status": 504' in log_blob
    assert settings.gemini_api_key not in log_blob


# ---------------------------------------------------------------------------
# 3. Assistant Resilience: Core Non-Fatal Boot, Context Reduction & Quota UX
# ---------------------------------------------------------------------------


def _setup_test_app_db():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return engine, TestingSession


def test_assistant_quota_unavailable_context_reduction_and_core_erp_unaffected():
    _setup_test_app_db()
    settings = _make_settings(gemini_llm_model="gemini-3.5-flash-lite", gemini_llm_fallback_models=())
    mock_genai = MagicMock()
    mem_qdrant = QdrantClient(":memory:")
    container = AIRuntimeContainer(
        settings=settings,
        gemini_client=GeminiClientManager(settings, client=mock_genai),
        qdrant_service=QdrantVectorService(settings, client=mem_qdrant, sleep_fn=lambda _d: None),
    )
    app.state.ai_container_override = container

    try:
        with TestClient(app) as client:
            assert client.post(
                "/api/auth/register",
                json={
                    "name": "Owner",
                    "email": "resil@sims.in",
                    "password": "Password123!",
                    "business_name": "Resilience Mart",
                    "business_type": "retailer",
                    "create_workspace": True,
                },
            ).status_code == 201
            tok = client.post("/api/auth/login", json={"email": "resil@sims.in", "password": "Password123!"}).json()["access_token"]
            hdr = {"Authorization": f"Bearer {tok}"}

            # 1. Quota exhausted -> HTTP 429, non-retryable, clear user message, conversation preserved, core ERP still 200!
            mock_genai.models.generate_content.side_effect = genai_errors.APIError(
                429,
                {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded limit: 0 on Free Tier"}},
            )
            quota_res = client.post("/api/ai/chat", headers=hdr, json={"message": "Show inventory status"})
            assert quota_res.status_code == 429
            qdetail = quota_res.json()["detail"]
            assert qdetail["error_code"] == "QUOTA_EXHAUSTED"
            assert qdetail["retryable"] is False
            assert "quota" in qdetail["message"].lower()
            conv_id = qdetail["conversation_id"]
            assert conv_id is not None

            # Core ERP endpoints remain 100% functional while Gemini is failing
            assert client.get("/health").status_code == 200
            assert client.get("/api/products/", headers=hdr).status_code == 200

            # 2. Context length exceeded triggers ONE clean reduced-context retry -> succeeds without duplicating user message!
            mock_genai.models.generate_content.side_effect = [
                genai_errors.APIError(
                    400,
                    {"error": {"status": "INVALID_ARGUMENT", "message": "input token count exceeds maximum context"}},
                ),
                _ok_resp("Recovered with reduced context."),
            ]
            ctx_res = client.post(
                "/api/ai/chat",
                headers=hdr,
                json={"conversation_id": conv_id, "message": "Show inventory status"},
            )
            assert ctx_res.status_code == 200, ctx_res.text
            assert ctx_res.json()["message"]["content"] == "Recovered with reduced context."

            msgs = client.get(f"/api/ai/conversations/{conv_id}", headers=hdr).json()["messages"]
            user_turns = [m for m in msgs if m["role"] == "user" and m["content"] == "Show inventory status"]
            assert len(user_turns) == 1

            # 3. Repeated 503 outage trips circuit breaker OPEN cleanly & surfaces structured CIRCUIT_OPEN
            mock_genai.models.generate_content.side_effect = genai_errors.APIError(
                503, {"error": {"status": "UNAVAILABLE", "message": "overloaded"}}
            )
            out1 = client.post("/api/ai/chat", headers=hdr, json={"conversation_id": conv_id, "message": "Second question"})
            assert out1.status_code == 503
            # Now circuit breaker (threshold=3; 1st attempt + 2 retries = 3 failures) is OPEN -> next call fails immediately without hitting mock_genai!
            call_count_when_opened = mock_genai.models.generate_content.call_count
            out2 = client.post("/api/ai/chat", headers=hdr, json={"conversation_id": conv_id, "message": "Second question"})
            assert out2.status_code == 503
            assert out2.json()["detail"]["error_code"] == "CIRCUIT_OPEN"
            assert mock_genai.models.generate_content.call_count == call_count_when_opened
            # Passive health reflects degraded circuit without throwing
            ai_health = client.get("/api/ai/health", headers=hdr).json()
            assert ai_health["components"]["gemini_llm"]["error_code"] == "CIRCUIT_OPEN"
    finally:
        app.state.ai_container_override = None
        app.state.ai_container = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
