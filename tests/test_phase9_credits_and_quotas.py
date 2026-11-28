"""Phase 9 test suite: AI credits ledger, atomic reservation/settlement, quotas, idempotency, concurrency, ingestion recovery, RBAC & migrations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

from alembic import command
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, event, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.ai_config import AIProviderSettings
from app.core.ai_exceptions import AICreditError, AIErrorCode
from app.core.ai_pricing import AIPricingSchedule, credits_float, from_credit_units, to_credit_units
from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db, get_engine_kwargs
from app.db_migrate import _alembic_config
from app.main import app
from app.models.ai_rag import AIConversation, AICreditAccount, AICreditTransaction, AIDocument, AIMessage, AIUsageLog
from app.models.products import Product
from app.services.ai.circuit_breaker import ProviderCircuitBreaker
from app.services.ai.container import AIRuntimeContainer
from app.services.ai.gemini_client import GeminiClientManager
from app.services.ai.ingestion_service import DocumentIngestionService
from app.services.ai.qdrant_service import QdrantVectorService


def _vec(text_val: str, dims: int = 128) -> List[float]:
    v = [0.0] * dims
    for tok in (text_val or "default").split():
        d = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(d[:2], "big") % dims
        v[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _setup_memory_db():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return engine, SessionLocal


def _register_and_login(
    client: TestClient,
    *,
    name: str,
    email: str,
    biz_name: str,
) -> tuple[Dict[str, str], int]:
    res = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "Password123!",
            "business_name": biz_name,
            "business_type": "retailer",
            "create_workspace": True,
        },
    )
    assert res.status_code == 201, res.text
    tok = client.post("/api/auth/login", json={"email": email, "password": "Password123!"}).json()["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    biz_id = client.get("/api/auth/me", headers=hdr).json()["active_business_id"]
    return hdr, int(biz_id)


def _make_container(
    tmp_dir: str,
    *,
    initial_grant: Decimal = Decimal("0.000"),
    initial_approved: bool = False,
    quota_cooldown_seconds: float = 120.0,
    llm_reply_fn=None,
    omit_usage_metadata: bool = False,
) -> tuple[AIRuntimeContainer, QdrantClient, MagicMock]:
    settings = AIProviderSettings(
        app_env="test",
        gemini_api_key="AIzaSyPhase9FakeKeyValue1234567890",
        gemini_llm_model="gemini-3.8-flash",
        gemini_llm_fallback_models=(),
        gemini_embedding_model="gemini-embedding-001",
        gemini_embedding_dimensions=128,
        gemini_embedding_normalize=True,
        gemini_max_retries=1,
        gemini_retry_base_seconds=0.01,
        gemini_retry_max_seconds=0.02,
        gemini_quota_cooldown_seconds=quota_cooldown_seconds,
        ai_credits_enforced=True,
        ai_initial_grant_credits=initial_grant,
        ai_initial_grant_approved=initial_approved,
        ai_upload_dir=tmp_dir,
        ai_chunk_size_chars=180,
        ai_chunk_overlap_chars=20,
        qdrant_url=":memory:",
        qdrant_max_retries=1,
    )
    mock_genai = MagicMock()

    def _embed(*, model, contents, config):
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(
                    values=_vec(t, 128),
                    statistics=SimpleNamespace(token_count=max(4, len(t) // 4)),
                )
                for t in contents
            ]
        )

    def _generate(*, model, contents, config):
        reply_text = llm_reply_fn(contents, config) if llm_reply_fn else "Your inventory summary looks healthy."
        usage_meta = (
            None
            if omit_usage_metadata
            else SimpleNamespace(
                prompt_token_count=120,
                candidates_token_count=40,
                thoughts_token_count=10,
                total_token_count=170,
            )
        )
        return SimpleNamespace(
            text=reply_text,
            parsed=None,
            candidates=[
                SimpleNamespace(
                    finish_reason="STOP",
                    content=SimpleNamespace(parts=[SimpleNamespace(text=reply_text, thought=False)]),
                )
            ],
            usage_metadata=usage_meta,
        )

    mock_genai.models.embed_content.side_effect = _embed
    mock_genai.models.generate_content.side_effect = _generate
    mem_qdrant = QdrantClient(":memory:")
    container = AIRuntimeContainer(
        settings=settings,
        gemini_client=GeminiClientManager(settings, client=mock_genai),
        qdrant_service=QdrantVectorService(settings, client=mem_qdrant, sleep_fn=lambda _d: None),
    )
    return container, mem_qdrant, mock_genai


# ---------------------------------------------------------------------------
# 1. Pricing Engine, Non-Invented Defaults & Decimal Precision
# ---------------------------------------------------------------------------


def test_pricing_precision_and_default_free_credits(tmp_path):
    pricing = AIPricingSchedule.from_env({})
    assert pricing.rate_approval_required is True
    assert pricing.pricing_version

    # New workspaces receive 3000 free AI credits by default.
    prod_like = AIProviderSettings(app_env="development")
    assert prod_like.ai_credits_enforced is True
    assert prod_like.ai_initial_grant_credits == Decimal("3000.000")
    assert prod_like.ai_initial_grant_approved is True

    # Missing provider usage metadata triggers conservative fallback estimation cleanly
    fallback_cost = pricing.calculate_text_generation_cost(
        model_name="gemini-3.8-flash",
        prompt_tokens=None,
        candidates_tokens=None,
        total_tokens=None,
        prompt_chars=400,
        response_chars=200,
    )
    assert fallback_cost.usage_source == "estimated_fallback"
    assert fallback_cost.units > 0
    assert fallback_cost.total_tokens >= 150

    # Scaled integer math avoids IEEE-754 drift across repeated tiny operations
    total_units = sum(to_credit_units("0.003") for _ in range(50))
    assert total_units == 150
    assert from_credit_units(total_units) == Decimal("0.150")


def test_dev_mode_initializes_zero_credits_unless_approved():
    engine, SessionLocal = _setup_memory_db()
    settings = AIProviderSettings(
        app_env="development",
        ai_initial_grant_credits=Decimal("500.0"),
        ai_initial_grant_approved=False,
    )
    container = AIRuntimeContainer(settings=settings)
    db = SessionLocal()
    try:
        from app.models.business import Business
        from app.models.users import User

        owner = User(name="ZeroOwner", email="zdef@sims.in", password_hash="x", role="owner")
        db.add(owner)
        db.flush()
        biz = Business(name="Zero Default Biz", business_type="retailer", owner_user_id=owner.id)
        db.add(biz)
        db.commit()
        db.refresh(biz)

        acc = container.credit_service.ensure_credit_account(db, business_id=biz.id)
        assert acc.available_units == 0
        assert acc.lifetime_granted_units == 0
    finally:
        db.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_new_workspace_receives_3000_default_free_credits():
    engine, SessionLocal = _setup_memory_db()
    settings = AIProviderSettings(app_env="development")
    container = AIRuntimeContainer(settings=settings)
    db = SessionLocal()
    try:
        from app.models.business import Business
        from app.models.users import User

        owner = User(name="FreeOwner", email="freeowner@sims.in", password_hash="x", role="owner")
        db.add(owner)
        db.flush()
        biz = Business(name="Free Credits Biz", business_type="retailer", owner_user_id=owner.id)
        db.add(biz)
        db.commit()
        db.refresh(biz)

        acc = container.credit_service.ensure_credit_account(
            db,
            business_id=biz.id,
            user_id=owner.id,
        )
        assert acc.available_units == 3_000_000
        assert acc.lifetime_granted_units == 3_000_000

        tx = (
            db.query(AICreditTransaction)
            .filter(AICreditTransaction.business_id == biz.id)
            .filter(AICreditTransaction.transaction_type == "INITIAL_GRANT")
            .one()
        )
        assert tx.credit_delta_units == 3_000_000
    finally:
        db.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_existing_workspace_without_initial_grant_receives_3000_once():
    engine, SessionLocal = _setup_memory_db()
    settings = AIProviderSettings(app_env="development", ai_initial_grant_approved=True)
    container = AIRuntimeContainer(settings=settings)
    db = SessionLocal()
    try:
        from app.models.business import Business
        from app.models.users import User
        from app.models.ai_rag import AICreditAccount

        owner = User(name="ExistingOwner", email="existing@sims.in", password_hash="x", role="owner")
        db.add(owner)
        db.flush()
        biz = Business(name="Existing Credits Biz", business_type="retailer", owner_user_id=owner.id)
        db.add(biz)
        db.flush()
        db.add(
            AICreditAccount(
                business_id=biz.id,
                available_units=125_000,
                reserved_units=0,
                lifetime_granted_units=125_000,
                lifetime_consumed_units=0,
                lifetime_refunded_units=0,
                status="ACTIVE",
                plan_tier="standard",
            )
        )
        db.commit()
        db.refresh(biz)

        acc = container.credit_service.ensure_credit_account(
            db,
            business_id=biz.id,
            user_id=owner.id,
        )
        assert acc.available_units == 125_000 + 3_000_000
        assert acc.lifetime_granted_units == 125_000 + 3_000_000

        acc_again = container.credit_service.ensure_credit_account(
            db,
            business_id=biz.id,
            user_id=owner.id,
        )
        assert acc_again.available_units == 125_000 + 3_000_000

        tx_count = (
            db.query(AICreditTransaction)
            .filter(
                AICreditTransaction.business_id == biz.id,
                AICreditTransaction.transaction_type == "INITIAL_GRANT",
            )
            .count()
        )
        assert tx_count == 1
    finally:
        db.close()
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# 2. Credit Reservation, Capture, Unused Refund, Failure 100% Refund
# ---------------------------------------------------------------------------


def test_credit_reservation_capture_and_failure_refund_lifecycle(tmp_path):
    engine, SessionLocal = _setup_memory_db()
    container, mem_qdrant, mock_genai = _make_container(
        str(tmp_path),
        initial_grant=Decimal("25.000"),
        initial_approved=True,
    )
    app.state.ai_container_override = container
    try:
        with TestClient(app) as client:
            hdr, biz_id = _register_and_login(
                client, name="Owner", email="owner_c1@sims.in", biz_name="Ledger Mart"
            )
            bal0 = client.get("/api/ai/credits/balance", headers=hdr).json()
            assert bal0["available_credits"] == 25.0
            assert bal0["reserved_credits"] == 0.0

            # Successful chat reserves upper bound, settles exact token cost (with thoughts tokens!), and refunds delta
            chat_res = client.post(
                "/api/ai/chat",
                headers=hdr,
                json={"message": "Give me a quick workspace overview"},
            )
            assert chat_res.status_code == 200, chat_res.text
            cdata = chat_res.json()
            assert cdata["credits_used"] > 0
            assert cdata["credits_reserved"] >= cdata["credits_used"]
            assert round(cdata["credits_used"] + cdata["credits_refunded"], 3) == round(
                cdata["credits_reserved"], 3
            )
            assert cdata["usage_source"] == "provider_reported"

            bal1 = client.get("/api/ai/credits/balance", headers=hdr).json()
            assert bal1["reserved_credits"] == 0.0
            assert round(bal1["available_credits"] + bal1["lifetime_consumed_credits"], 3) == 25.0

            # Failing Gemini turn MUST refund 100% of reservation and log zero consumed credits
            mock_genai.models.generate_content.side_effect = genai_errors.APIError(
                503, {"error": {"status": "UNAVAILABLE", "message": "temporary upstream error"}}
            )
            fail_res = client.post(
                "/api/ai/chat",
                headers=hdr,
                json={"message": "Second question fails"},
            )
            assert fail_res.status_code == 503
            bal2 = client.get("/api/ai/credits/balance", headers=hdr).json()
            assert bal2["available_credits"] == bal1["available_credits"]
            assert bal2["reserved_credits"] == 0.0
            assert bal2["lifetime_consumed_credits"] == bal1["lifetime_consumed_credits"]

            logs = client.get("/api/ai/usage/logs?status=error", headers=hdr).json()
            assert logs["total"] == 1
            err_log = logs["items"][0]
            assert err_log["credits_consumed"] == 0.0
            assert err_log["credits_refunded"] > 0.0
            assert err_log["usage_source"] == "not_billed"
            assert err_log["error_category"] == "transient"
    finally:
        app.state.ai_container_override = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_missing_provider_usage_metadata_uses_fallback_estimator(tmp_path):
    engine, SessionLocal = _setup_memory_db()
    container, mem_qdrant, _ = _make_container(
        str(tmp_path),
        initial_grant=Decimal("10.000"),
        initial_approved=True,
        omit_usage_metadata=True,
    )
    app.state.ai_container_override = container
    try:
        with TestClient(app) as client:
            hdr, _ = _register_and_login(
                client, name="FallbackOwner", email="fb@sims.in", biz_name="Fallback Store"
            )
            res = client.post("/api/ai/chat", headers=hdr, json={"message": "How is stock?"})
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["usage_source"] == "estimated_fallback"
            assert body["credits_used"] > 0
    finally:
        app.state.ai_container_override = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# 3. 402 Insufficient Credits vs 429 Provider Quota vs 429 Tenant Quota + ERP Isolation
# ---------------------------------------------------------------------------


def test_insufficient_credits_vs_gemini_quota_cooldown_and_tenant_policies(tmp_path):
    engine, SessionLocal = _setup_memory_db()
    container, mem_qdrant, mock_genai = _make_container(
        str(tmp_path),
        initial_grant=Decimal("0.000"),
        initial_approved=False,
        quota_cooldown_seconds=120.0,
    )
    app.state.ai_container_override = container
    try:
        with TestClient(app) as client:
            hdr, biz_id = _register_and_login(
                client, name="ZeroOwner", email="zero@sims.in", biz_name="Zero Credits Store"
            )

            # 1. Zero credits -> HTTP 402 INSUFFICIENT_AI_CREDITS before touching Gemini or creating conv
            res402 = client.post("/api/ai/chat", headers=hdr, json={"message": "Hello"})
            assert res402.status_code == 402
            assert res402.json()["detail"]["error_code"] == "INSUFFICIENT_AI_CREDITS"
            assert res402.json()["detail"]["retryable"] is False
            assert mock_genai.models.generate_content.call_count == 0
            assert client.get("/api/ai/conversations", headers=hdr).json() == []

            # Upload rejected cleanly with 402 when credits are 0
            up402 = client.post(
                "/api/ai/documents",
                headers=hdr,
                files={"file": ("sop.txt", b"Warehouse SOP content.", "text/plain")},
                data={"async_process": "false"},
            )
            assert up402.status_code == 402
            assert up402.json()["detail"]["error_code"] == "INSUFFICIENT_AI_CREDITS"

            # Core ERP endpoints stay 100% operational cleanly even with 0 credits!
            assert client.get("/health").status_code == 200
            assert client.get("/api/products/", headers=hdr).status_code == 200

            # 2. Admin tops up 50 credits -> check Tenant Policy enforcement (RPM & Suspension)
            adj = client.post(
                "/api/ai/admin/credits/adjust",
                headers=hdr,
                json={
                    "credit_delta": 50.0,
                    "transaction_type": "PURCHASE",
                    "reason": "Paid pack top-up",
                    "idempotency_key": "topup-1",
                },
            )
            assert adj.status_code == 200
            assert adj.json()["account"]["available_credits"] == 50.0

            # Restrict RPM limit to 1/min cleanly
            pol = client.put(
                "/api/ai/admin/policies",
                headers=hdr,
                json={"rpm_limit": 1, "reason": "Strict QA throttle test"},
            )
            assert pol.status_code == 200

            assert client.post("/api/ai/chat", headers=hdr, json={"message": "First allowed"}).status_code == 200
            rpm_hit = client.post("/api/ai/chat", headers=hdr, json={"message": "Second throttled"})
            assert rpm_hit.status_code == 429
            assert rpm_hit.json()["detail"]["error_code"] == "TENANT_QUOTA_EXCEEDED"
            assert rpm_hit.json()["detail"]["retryable"] is True

            # Raise RPM, test SUSPEND -> 403 AI_ACCOUNT_SUSPENDED
            assert client.put(
                "/api/ai/admin/policies",
                headers=hdr,
                json={"rpm_limit": 30, "status": "SUSPENDED", "reason": "Temporary hold"},
            ).status_code == 200
            susp = client.post("/api/ai/chat", headers=hdr, json={"message": "Blocked while suspended"})
            assert susp.status_code == 403
            assert susp.json()["detail"]["error_code"] == "AI_ACCOUNT_SUSPENDED"
            # Core ERP STILL 200 while AI suspended!
            assert client.get("/api/products/", headers=hdr).status_code == 200

            # Reactivate -> test Gemini QUOTA_EXHAUSTED triggers provider quota cooldown + 100% refund
            assert client.put(
                "/api/ai/admin/policies",
                headers=hdr,
                json={"status": "ACTIVE", "reason": "Reactivate"},
            ).status_code == 200
            bal_before_quota = client.get("/api/ai/credits/balance", headers=hdr).json()["available_credits"]

            mock_genai.models.generate_content.side_effect = genai_errors.APIError(
                429,
                {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: limit: 0"}},
            )
            q1 = client.post("/api/ai/chat", headers=hdr, json={"message": "Hits provider quota"})
            assert q1.status_code == 429
            assert q1.json()["detail"]["error_code"] == "QUOTA_EXHAUSTED"
            calls_after_q1 = mock_genai.models.generate_content.call_count

            # Subsequent call immediately short-circuits in cooldown WITHOUT calling Gemini again!
            q2 = client.post("/api/ai/chat", headers=hdr, json={"message": "Blocked by cooldown"})
            assert q2.status_code == 429
            assert q2.json()["detail"]["error_code"] == "QUOTA_EXHAUSTED"
            assert "Retry-After" in q2.headers
            assert mock_genai.models.generate_content.call_count == calls_after_q1

            # Health passively shows QUOTA_EXHAUSTED cooldown active
            h = client.get("/api/ai/health", headers=hdr).json()
            assert h["components"]["gemini_llm"]["error_code"] == "QUOTA_EXHAUSTED"

            # Credits 100% preserved across provider quota failures
            bal_after_quota = client.get("/api/ai/credits/balance", headers=hdr).json()["available_credits"]
            assert bal_after_quota == bal_before_quota
    finally:
        app.state.ai_container_override = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# 4. Idempotency (Chat Success Replay, Retry After Failure, Admin Credit Adjust)
# ---------------------------------------------------------------------------


def test_idempotent_chat_and_admin_credit_adjustments(tmp_path):
    engine, SessionLocal = _setup_memory_db()
    container, mem_qdrant, mock_genai = _make_container(
        str(tmp_path),
        initial_grant=Decimal("30.000"),
        initial_approved=True,
    )
    app.state.ai_container_override = container
    try:
        with TestClient(app) as client:
            hdr, _ = _register_and_login(
                client, name="IdemOwner", email="idem@sims.in", biz_name="Idem Store"
            )

            # A. Failed chat with Idempotency-Key -> refunded, then retry with SAME key succeeds and charges ONCE
            orig_gen = mock_genai.models.generate_content.side_effect
            mock_genai.models.generate_content.side_effect = genai_errors.APIError(
                503, {"error": {"status": "UNAVAILABLE", "message": "temporary bump"}}
            )
            fail_retry = client.post(
                "/api/ai/chat",
                headers={**hdr, "Idempotency-Key": "client-turn-abc"},
                json={"message": "Check status"},
            )
            assert fail_retry.status_code == 503
            conv_id = fail_retry.json()["detail"]["conversation_id"]
            assert client.get("/api/ai/credits/balance", headers=hdr).json()["available_credits"] == 30.0

            # Now upstream recovers -> retry with SAME Idempotency-Key & conv_id
            mock_genai.models.generate_content.side_effect = orig_gen
            ok1 = client.post(
                "/api/ai/chat",
                headers={**hdr, "Idempotency-Key": "client-turn-abc"},
                json={"conversation_id": conv_id, "message": "Check status"},
            )
            assert ok1.status_code == 200, ok1.text
            assert ok1.json()["idempotent_replay"] is False
            bal_after_ok = client.get("/api/ai/credits/balance", headers=hdr).json()["available_credits"]
            calls_after_ok = mock_genai.models.generate_content.call_count

            # Replay SAME Idempotency-Key -> returns identical response, 0 Gemini calls, 0 additional debit!
            replay = client.post(
                "/api/ai/chat",
                headers={**hdr, "Idempotency-Key": "client-turn-abc"},
                json={"conversation_id": conv_id, "message": "Check status"},
            )
            assert replay.status_code == 200
            rdata = replay.json()
            assert rdata["idempotent_replay"] is True
            assert rdata["message"]["id"] == ok1.json()["message"]["id"]
            assert mock_genai.models.generate_content.call_count == calls_after_ok
            assert client.get("/api/ai/credits/balance", headers=hdr).json()["available_credits"] == bal_after_ok

            # B. Duplicate admin adjustment idempotency key applies ONCE
            a1 = client.post(
                "/api/ai/admin/credits/adjust",
                headers=hdr,
                json={
                    "credit_delta": 20.0,
                    "transaction_type": "PROMOTIONAL_CREDIT",
                    "reason": "Launch promo",
                    "idempotency_key": "promo-100",
                },
            )
            a2 = client.post(
                "/api/ai/admin/credits/adjust",
                headers=hdr,
                json={
                    "credit_delta": 20.0,
                    "transaction_type": "PROMOTIONAL_CREDIT",
                    "reason": "Launch promo",
                    "idempotency_key": "promo-100",
                },
            )
            assert a1.status_code == 200 and a2.status_code == 200
            assert a1.json()["transaction"]["transaction_uid"] == a2.json()["transaction"]["transaction_uid"]
            assert a2.json()["account"]["available_credits"] == round(bal_after_ok + 20.0, 3)
    finally:
        app.state.ai_container_override = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# 5. Concurrent Reservation Protection & Negative Balance Guard
# ---------------------------------------------------------------------------


def test_concurrent_credit_reservations_prevent_overspend_sqlite(tmp_path):
    db_file = tmp_path / "concurrent_credits.db"
    url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    settings = AIProviderSettings(
        app_env="test",
        ai_credits_enforced=True,
        ai_initial_grant_credits=Decimal("0.500"),
        ai_initial_grant_approved=True,
        ai_default_max_concurrent_requests=20,
    )
    container = AIRuntimeContainer(settings=settings)

    # Seed business with exact 0.500 credits (500 units)
    seed_db = SessionLocal()
    try:
        from app.models.business import Business
        from app.models.users import User

        owner = User(name="RaceOwner", email="race@sims.in", password_hash="x", role="owner")
        seed_db.add(owner)
        seed_db.flush()
        biz = Business(name="Race Biz", business_type="retailer", owner_user_id=owner.id)
        seed_db.add(biz)
        seed_db.commit()
        seed_db.refresh(biz)
        biz_id = biz.id
        owner_id = owner.id
        container.credit_service.ensure_credit_account(seed_db, business_id=biz_id)
    finally:
        seed_db.close()

    def _worker(idx: int) -> str:
        s = SessionLocal()
        try:
            container.credit_service.reserve_credits(
                s,
                business_id=biz_id,
                user_id=None,
                operation_type="chat_rag",
                model_name="gemini-3.8-flash",
                estimated_reserve_units=400,
                request_id=f"race-{idx}",
                idempotency_key=f"race-{idx}",
            )
            return "RESERVED"
        except AICreditError as exc:
            return exc.error_code.value
        finally:
            s.close()

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(_worker, range(6)))

        assert outcomes.count("RESERVED") == 1
        assert outcomes.count("INSUFFICIENT_AI_CREDITS") == 5

        check_db = SessionLocal()
        try:
            acc = check_db.query(AICreditAccount).filter(AICreditAccount.business_id == biz_id).one()
            assert acc.available_units == 100
            assert acc.reserved_units == 400
            assert acc.available_units >= 0
            assert acc.reserved_units >= 0

            # Negative manual adjustment beyond available must also fail cleanly
            with pytest.raises(AICreditError) as neg_err:
                container.credit_service.admin_adjust_credits(
                    check_db,
                    business_id=biz_id,
                    admin_user_id=owner_id,
                    credit_delta=-5.0,
                    transaction_type="MANUAL_ADJUSTMENT",
                    reason="Should reject negative balance",
                    idempotency_key="neg-test-1",
                )
            assert neg_err.value.error_code == AIErrorCode.INSUFFICIENT_AI_CREDITS
        finally:
            check_db.close()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 6. Resumable Ingestion Checkpoint Metering, Recovery & Dimension Guard
# ---------------------------------------------------------------------------


def test_resumable_ingestion_metering_recovery_and_dimension_guard(tmp_path):
    engine, SessionLocal = _setup_memory_db()
    container, mem_qdrant, mock_genai = _make_container(
        str(tmp_path),
        initial_grant=Decimal("50.000"),
        initial_approved=True,
    )
    app.state.ai_container_override = container
    try:
        db = SessionLocal()
        try:
            from app.models.business import Business
            from app.models.users import User

            u = User(name="Ing", email="ing@sims.in", password_hash="x", role="owner")
            db.add(u)
            db.flush()
            biz = Business(name="Ing Store", business_type="retailer", owner_user_id=u.id)
            db.add(biz)
            db.commit()
            db.refresh(u)
            db.refresh(biz)

            content = "\n\n".join(
                f"Section {i}: Receiving batch policy step number {i} details warehouse safety checks and barcode verification."
                for i in range(1, 7)
            ).encode("utf-8")

            svc = DocumentIngestionService(container, batch_size=2)
            doc, is_dup = svc.upload_document(
                db,
                business_id=biz.id,
                user_id=u.id,
                filename="receiving_manual.txt",
                raw_bytes=content,
                mime_type="text/plain",
                title="Receiving Manual",
            )
            assert is_dup is False

            # Succeed Batch 1, fail Batch 2 with QUOTA_EXHAUSTED
            call_counter = {"n": 0}

            def _partial_embed(*, model, contents, config):
                call_counter["n"] += 1
                if call_counter["n"] == 2:
                    raise genai_errors.APIError(
                        429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded limit: 0"}}
                    )
                return SimpleNamespace(
                    embeddings=[
                        SimpleNamespace(values=_vec(t, 128), statistics=SimpleNamespace(token_count=12))
                        for t in contents
                    ]
                )

            mock_genai.models.embed_content.side_effect = _partial_embed
            paused = svc.process_document(db, doc_id=doc.id, business_id=biz.id)
            assert paused.status == "QUOTA_PAUSED"
            assert paused.indexed_chunks == 2
            assert paused.total_chunks >= 3
            assert paused.last_error_category == "quota"
            assert paused.next_retry_at is not None
            assert paused.job_id is not None
            consumed_after_b1 = paused.credits_consumed_units
            assert consumed_after_b1 > 0
            assert paused.credits_refunded_units > 0

            # Resuming with incompatible embedding dimensions MUST fail safely without mixing vectors!
            orig_dims = container.settings.gemini_embedding_dimensions
            object.__setattr__(container.settings, "gemini_embedding_dimensions", 768)
            with pytest.raises(Exception) as mismatch_err:
                svc.retry_document(db, doc_id=doc.id, business_id=biz.id)
            assert getattr(mismatch_err.value, "error_code", None) == AIErrorCode.COLLECTION_MISMATCH
            object.__setattr__(container.settings, "gemini_embedding_dimensions", orig_dims)

            # Restore healthy embedding -> manual resume clears cooldown & embeds remaining chunks ONLY!
            calls_before_resume = call_counter["n"]
            mock_genai.models.embed_content.side_effect = lambda *, model, contents, config: (
                call_counter.__setitem__("n", call_counter["n"] + 1)
                or SimpleNamespace(
                    embeddings=[
                        SimpleNamespace(values=_vec(t, 128), statistics=SimpleNamespace(token_count=12))
                        for t in contents
                    ]
                )
            )
            resumed = svc.retry_document(db, doc_id=doc.id, business_id=biz.id)
            assert resumed.status == "COMPLETED"
            assert resumed.indexed_chunks == resumed.total_chunks
            # Batch 1 (2 indexed chunks) was NOT re-embedded on resume!
            expected_remaining_batches = math.ceil((resumed.total_chunks - 2) / 2)
            assert call_counter["n"] - calls_before_resume == expected_remaining_batches
        finally:
            db.close()
    finally:
        app.state.ai_container_override = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# 7. RBAC, Multi-Tenant Isolation, Analytics & Admin Failures Recovery API
# ---------------------------------------------------------------------------


def test_rbac_multi_tenant_isolation_and_analytics_apis(tmp_path):
    engine, SessionLocal = _setup_memory_db()
    container, mem_qdrant, _ = _make_container(
        str(tmp_path),
        initial_grant=Decimal("40.000"),
        initial_approved=True,
    )
    app.state.ai_container_override = container
    try:
        with TestClient(app) as client:
            hdr_a, biz_a = _register_and_login(
                client, name="OwnerA", email="ownera@sims.in", biz_name="Tenant Alpha"
            )
            hdr_b, biz_b = _register_and_login(
                client, name="OwnerB", email="ownerb@sims.in", biz_name="Tenant Beta"
            )

            # Invite staff member into Tenant Alpha and log them in
            inv = client.post(
                "/api/members/invite",
                headers=hdr_a,
                json={"email": "staffa@sims.in", "role": "staff"},
            )
            assert inv.status_code in (200, 201), inv.text
            assert client.post(
                "/api/auth/register",
                json={
                    "name": "StaffA",
                    "email": "staffa@sims.in",
                    "password": "Password123!",
                    "create_workspace": False,
                },
            ).status_code == 201
            staff_tok = client.post(
                "/api/auth/login", json={"email": "staffa@sims.in", "password": "Password123!"}
            ).json()["access_token"]
            hdr_staff = {"Authorization": f"Bearer {staff_tok}"}
            # Accept pending invite cleanly
            my_invs = client.get("/api/members/my-invitations", headers=hdr_staff).json()
            assert len(my_invs) == 1
            client.post(
                "/api/members/accept-invitation",
                headers=hdr_staff,
                json={"token": my_invs[0]["token"]},
            )
            client.post("/api/businesses/switch", headers=hdr_staff, json={"business_id": biz_a})

            # Staff can read credit balance/pricing (`ai.credits.read`), CANNOT read usage analytics (`ai.usage.read`) or admin routes (`ai.credits.manage`)
            assert client.get("/api/ai/credits/balance", headers=hdr_staff).status_code == 200
            assert client.get("/api/ai/credits/pricing", headers=hdr_staff).status_code == 200
            assert client.get("/api/ai/usage/summary", headers=hdr_staff).status_code == 403
            assert (
                client.post(
                    "/api/ai/admin/credits/adjust",
                    headers=hdr_staff,
                    json={
                        "credit_delta": 100.0,
                        "transaction_type": "PURCHASE",
                        "reason": "Unauthorized staff attempt",
                        "idempotency_key": "staff-nope",
                    },
                ).status_code
                == 403
            )
            assert client.get("/api/ai/admin/failures", headers=hdr_staff).status_code == 403

            # Cross-tenant header tampering by Tenant Beta Owner against Tenant Alpha -> blocked cleanly (403)
            assert (
                client.get(
                    "/api/ai/credits/balance",
                    headers={**hdr_b, "X-Business-Id": str(biz_a)},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/ai/admin/credits/adjust",
                    headers={**hdr_b, "X-Business-Id": str(biz_a)},
                    json={
                        "credit_delta": 99.0,
                        "transaction_type": "PURCHASE",
                        "reason": "Cross tenant attempt",
                        "idempotency_key": "x-tenant",
                    },
                ).status_code
                == 403
            )

            # Tenant Alpha generates activity -> usage summary, transactions, logs & pricing endpoints reflect exact state
            assert client.post("/api/ai/chat", headers=hdr_a, json={"message": "Show summary"}).status_code == 200
            summary_a = client.get("/api/ai/usage/summary?days=30", headers=hdr_a).json()
            assert summary_a["totals"]["requests"] == 1
            assert summary_a["totals"]["credits_consumed"] > 0

            txs_a = client.get("/api/ai/credits/transactions?limit=10", headers=hdr_a).json()
            assert txs_a["total"] >= 3  # INITIAL_GRANT + REQUEST_RESERVATION + REQUEST_CAPTURE (+ optional REFUND)

            # Tenant Beta sees 0 usage & untouched balance (complete multi-tenant isolation)
            summary_b = client.get("/api/ai/usage/summary?days=30", headers=hdr_b).json()
            assert summary_b["totals"]["requests"] == 0
            assert summary_b["totals"]["credits_consumed"] == 0.0
            assert client.get("/api/ai/credits/balance", headers=hdr_b).json()["available_credits"] == 40.0

            failures_a = client.get("/api/ai/admin/failures", headers=hdr_a).json()
            assert "circuit_breakers" in failures_a
    finally:
        app.state.ai_container_override = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# 8. Alembic 0004 Migration Compatibility (SQLite + Optional PostgreSQL)
# ---------------------------------------------------------------------------


def test_alembic_0004_phase9_upgrade_and_downgrade_sqlite(tmp_path):
    db_file = tmp_path / "mig_phase9.db"
    url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        cfg = _alembic_config(url)
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0003_phase8_rag_assistant")
            conn.execute(
                text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES ('MigUser', 'm@sims.in', 'x', 'owner')"
                )
            )
            uid = conn.execute(text("SELECT id FROM users ORDER BY id DESC LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO businesses (name, business_type, owner_user_id) "
                    "VALUES ('PrePhase9 Biz', 'retailer', :uid)"
                ),
                {"uid": uid},
            )
            conn.commit()

            command.upgrade(cfg, "head")
            conn.commit()

        insp = sa_inspect(engine)
        tables = set(insp.get_table_names())
        assert {"ai_credit_accounts", "ai_credit_transactions"}.issubset(tables)

        usage_cols = {c["name"] for c in insp.get_columns("ai_usage_logs")}
        assert {"provider", "credits_reserved_units", "credits_consumed_units", "usage_source", "error_category"}.issubset(usage_cols)

        doc_cols = {c["name"] for c in insp.get_columns("ai_documents")}
        assert {"job_id", "last_error_category", "next_retry_at", "credits_consumed_units"}.issubset(doc_cols)

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT available_units, status, plan_tier FROM ai_credit_accounts")
            ).fetchone()
            assert row is not None and row[0] == 3_000_000 and row[1] == "ACTIVE"
            grant = conn.execute(
                text(
                    "SELECT transaction_type, amount_units, reason "
                    "FROM ai_credit_transactions"
                )
            ).fetchone()
            assert grant is not None
            assert grant[0] == "INITIAL_GRANT"
            assert grant[1] == 3_000_000
            assert grant[2] == "Existing workspace free AI credit allocation"

            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0003_phase8_rag_assistant")
            conn.commit()

        insp_down = sa_inspect(engine)
        assert "ai_credit_accounts" not in set(insp_down.get_table_names())
        assert "ai_credit_transactions" not in set(insp_down.get_table_names())

        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        assert "ai_credit_accounts" in set(sa_inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL not set")
def test_alembic_0004_and_atomic_debit_postgresql():
    pg_url = os.environ["TEST_POSTGRES_URL"]
    pg_engine = create_engine(pg_url, **get_engine_kwargs(pg_url))
    try:
        cfg = _alembic_config(pg_url)
        with pg_engine.connect() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"))
            conn.commit()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0003_phase8_rag_assistant")
            conn.execute(
                text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES ('PGOwner', 'pg@sims.in', 'x', 'owner')"
                )
            )
            uid = conn.execute(text("SELECT id FROM users ORDER BY id DESC LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO businesses (name, business_type, owner_user_id) "
                    "VALUES ('PG Biz', 'retailer', :uid)"
                ),
                {"uid": uid},
            )
            conn.commit()
            command.upgrade(cfg, "head")
            conn.commit()

        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)
        settings = AIProviderSettings(
            app_env="test",
            ai_credits_enforced=True,
            ai_initial_grant_credits=Decimal("0.000"),
            ai_default_max_concurrent_requests=20,
        )
        container = AIRuntimeContainer(settings=settings)
        db = SessionLocal()
        try:
            biz_id = int(db.execute(text("SELECT id FROM businesses LIMIT 1")).scalar_one())
            container.credit_service.admin_adjust_credits(
                db,
                business_id=biz_id,
                admin_user_id=None,  # type: ignore[arg-type]
                credit_delta=Decimal("0.500"),
                transaction_type="PURCHASE",
                reason="PG concurrency seed",
                idempotency_key="pg-seed-1",
            )
        finally:
            db.close()

        def _pg_worker(idx: int) -> str:
            s = SessionLocal()
            try:
                container.credit_service.reserve_credits(
                    s,
                    business_id=biz_id,
                    user_id=None,
                    operation_type="chat_rag",
                    model_name="gemini-3.8-flash",
                    estimated_reserve_units=400,
                    request_id=f"pg-race-{idx}",
                    idempotency_key=f"pg-race-{idx}",
                )
                return "RESERVED"
            except AICreditError as exc:
                return exc.error_code.value
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(_pg_worker, range(6)))

        assert outcomes.count("RESERVED") == 1
        assert outcomes.count("INSUFFICIENT_AI_CREDITS") == 5

        with pg_engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0003_phase8_rag_assistant")
            command.upgrade(cfg, "head")
            conn.commit()
    finally:
        pg_engine.dispose()
