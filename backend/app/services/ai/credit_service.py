"""Atomic, concurrency-safe tenant credit accounting, reservation/capture/refund ledger, and usage policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import case, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.ai_config import AIProviderSettings
from ...core.ai_exceptions import (
    AICreditError,
    AIErrorCode,
    AIInvalidRequestError,
    AITenantQuotaError,
)
from ...core.ai_pricing import (
    AIPricingSchedule,
    CostBreakdown,
    credits_float,
    to_credit_units,
    to_signed_credit_units,
)
from ...models.ai_rag import AICreditAccount, AICreditTransaction, AIUsageLog

VALID_ADMIN_TX_TYPES = {
    "INITIAL_GRANT",
    "PURCHASE",
    "ADMIN_ADJUSTMENT",
    "MANUAL_ADJUSTMENT",
    "PROMOTIONAL_CREDIT",
    "PLAN_ALLOCATION",
    "EXPIRATION",
}

VALID_ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED", "EXHAUSTED"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_day_start() -> datetime:
    now = _utcnow()
    return datetime(now.year, now.month, now.day)


@dataclass(frozen=True)
class CreditReservation:
    reservation_active: bool
    business_id: int
    usage_log_id: int
    request_id: str
    base_idempotency_key: str
    attempt_idempotency_key: str
    reserved_units: int
    pricing_version: str
    idempotent_replay: bool = False
    replay_conversation_id: Optional[int] = None


def serialize_credit_account(
    acc: AICreditAccount,
    settings: AIProviderSettings,
) -> Dict[str, Any]:
    return {
        "business_id": acc.business_id,
        "status": acc.status,
        "plan_tier": acc.plan_tier,
        "available_credits": credits_float(acc.available_units),
        "reserved_credits": credits_float(acc.reserved_units),
        "lifetime_granted_credits": credits_float(acc.lifetime_granted_units),
        "lifetime_consumed_credits": credits_float(acc.lifetime_consumed_units),
        "lifetime_refunded_credits": credits_float(acc.lifetime_refunded_units),
        "credits_enforced": settings.ai_credits_enforced,
        "limits": {
            "rpm_limit": acc.rpm_limit or settings.ai_default_rpm_limit,
            "daily_request_limit": acc.daily_request_limit or settings.ai_default_daily_request_limit,
            "daily_token_limit": acc.daily_token_limit or settings.ai_default_daily_token_limit,
            "max_credits_per_operation": credits_float(
                acc.max_credits_per_operation_units
                if acc.max_credits_per_operation_units is not None
                else to_credit_units(settings.ai_default_max_credits_per_operation)
            ),
            "max_concurrent_requests": acc.max_concurrent_requests or settings.ai_default_max_concurrent_requests,
            "max_context_turns": acc.max_context_turns or settings.ai_max_conversation_turns,
            "max_document_mb": acc.max_document_mb or settings.ai_max_document_mb,
        },
        "policy_override_reason": acc.policy_override_reason,
        "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
    }


def serialize_credit_transaction(tx: AICreditTransaction) -> Dict[str, Any]:
    return {
        "id": tx.id,
        "transaction_uid": tx.transaction_uid,
        "business_id": tx.business_id,
        "user_id": tx.user_id,
        "usage_log_id": tx.usage_log_id,
        "request_id": tx.request_id,
        "idempotency_key": tx.idempotency_key,
        "transaction_type": tx.transaction_type,
        "credit_change": credits_float(tx.credit_delta_units),
        "amount": credits_float(tx.amount_units),
        "available_before": credits_float(tx.available_before_units),
        "available_after": credits_float(tx.available_after_units),
        "reserved_before": credits_float(tx.reserved_before_units),
        "reserved_after": credits_float(tx.reserved_after_units),
        "status": tx.status,
        "operation_type": tx.operation_type,
        "billing_reference": tx.billing_reference,
        "pricing_version": tx.pricing_version,
        "reason": tx.reason,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


class AICreditService:
    """Thread-safe, database-atomic tenant credit ledger, policy guard, and metering service."""

    def __init__(
        self,
        settings: AIProviderSettings,
        pricing: Optional[AIPricingSchedule] = None,
    ) -> None:
        self._settings = settings
        self._pricing = pricing or AIPricingSchedule.from_env()

    @property
    def pricing(self) -> AIPricingSchedule:
        return self._pricing

    def ensure_credit_account(
        self,
        db: Session,
        *,
        business_id: int,
        user_id: Optional[int] = None,
    ) -> AICreditAccount:
        """Return existing tenant credit account or create it safely without racing."""
        existing = (
            db.query(AICreditAccount)
            .filter(AICreditAccount.business_id == business_id)
            .first()
        )
        if existing is not None:
            initial_units = 0
            if self._settings.ai_initial_grant_credits > Decimal("0") and (
                self._settings.ai_initial_grant_approved or self._settings.app_env == "test"
            ):
                initial_units = to_credit_units(self._settings.ai_initial_grant_credits)

            if initial_units > 0:
                initial_tx_exists = (
                    db.query(AICreditTransaction)
                    .filter(
                        AICreditTransaction.business_id == business_id,
                        AICreditTransaction.transaction_type == "INITIAL_GRANT",
                        AICreditTransaction.idempotency_key == f"initial-grant:{business_id}",
                    )
                    .first()
                )
                if initial_tx_exists is None:
                    available_before = int(existing.available_units)
                    reserved_before = int(existing.reserved_units)
                    existing.available_units = available_before + initial_units
                    existing.lifetime_granted_units = int(existing.lifetime_granted_units) + initial_units
                    db.flush()
                    db.add(
                        AICreditTransaction(
                            transaction_uid=f"initial-grant-{business_id}",
                            business_id=business_id,
                            user_id=user_id,
                            request_id=f"init-{business_id}",
                            idempotency_key=f"initial-grant:{business_id}",
                            transaction_type="INITIAL_GRANT",
                            credit_delta_units=initial_units,
                            amount_units=initial_units,
                            available_before_units=available_before,
                            available_after_units=available_before + initial_units,
                            reserved_before_units=reserved_before,
                            reserved_after_units=reserved_before,
                            status="POSTED",
                            operation_type="account_initialization",
                            pricing_version=self._pricing.pricing_version,
                            reason="Existing workspace initial AI credit allocation",
                        )
                    )
                    try:
                        db.commit()
                        db.refresh(existing)
                    except IntegrityError:
                        db.rollback()
                        existing = (
                            db.query(AICreditAccount)
                            .filter(AICreditAccount.business_id == business_id)
                            .first()
                        )
                        if existing is None:
                            raise
            return existing

        initial_units = 0
        if self._settings.ai_initial_grant_credits > Decimal("0") and (
            self._settings.ai_initial_grant_approved or self._settings.app_env == "test"
        ):
            initial_units = to_credit_units(self._settings.ai_initial_grant_credits)

        acc = AICreditAccount(
            business_id=business_id,
            available_units=initial_units,
            reserved_units=0,
            lifetime_granted_units=initial_units,
            lifetime_consumed_units=0,
            lifetime_refunded_units=0,
            status="ACTIVE",
            plan_tier=self._settings.ai_default_plan_tier,
        )
        try:
            db.add(acc)
            db.flush()
            if initial_units > 0:
                tx = AICreditTransaction(
                    transaction_uid=str(uuid4()),
                    business_id=business_id,
                    user_id=user_id,
                    request_id=f"init-{business_id}",
                    idempotency_key=f"initial-grant:{business_id}",
                    transaction_type="INITIAL_GRANT",
                    credit_delta_units=initial_units,
                    amount_units=initial_units,
                    available_before_units=0,
                    available_after_units=initial_units,
                    reserved_before_units=0,
                    reserved_after_units=0,
                    status="POSTED",
                    operation_type="account_initialization",
                    pricing_version=self._pricing.pricing_version,
                    reason="Configured workspace initial AI credit allocation",
                )
                db.add(tx)
            db.commit()
            db.refresh(acc)
            return acc
        except IntegrityError:
            db.rollback()
            row = (
                db.query(AICreditAccount)
                .filter(AICreditAccount.business_id == business_id)
                .first()
            )
            if row is None:
                raise
            return row

    def check_tenant_policies(
        self,
        db: Session,
        *,
        account: AICreditAccount,
        estimated_reserve_units: int,
    ) -> None:
        """Enforce tenant account status, per-op cap, concurrency, RPM, and daily quotas."""
        if account.status == "SUSPENDED":
            raise AICreditError(
                "AI features are currently suspended for this workspace. Contact your workspace administrator.",
                error_code=AIErrorCode.AI_ACCOUNT_SUSPENDED,
                http_status=403,
                retryable=False,
            )

        max_op_units = (
            account.max_credits_per_operation_units
            if account.max_credits_per_operation_units is not None
            else to_credit_units(self._settings.ai_default_max_credits_per_operation)
        )
        if estimated_reserve_units > max_op_units:
            raise AITenantQuotaError(
                f"Estimated operation cost ({credits_float(estimated_reserve_units)} credits) exceeds the workspace per-operation limit ({credits_float(max_op_units)} credits).",
                retry_after_seconds=None,
            )

        now = _utcnow()
        # 1. Active in-flight concurrency check within recent 2-minute lease window
        eff_conc = account.max_concurrent_requests or self._settings.ai_default_max_concurrent_requests
        in_flight = (
            db.query(func.count(AIUsageLog.id))
            .filter(
                AIUsageLog.business_id == account.business_id,
                AIUsageLog.status == "reserved",
                AIUsageLog.created_at >= (now - timedelta(seconds=120)),
            )
            .scalar()
            or 0
        )
        if in_flight >= eff_conc:
            raise AITenantQuotaError(
                "Your workspace reached its concurrent AI request limit. Please wait a moment and try again.",
                retry_after_seconds=3.0,
            )

        # 2. Per-minute request limit
        eff_rpm = account.rpm_limit or self._settings.ai_default_rpm_limit
        recent_rpm = (
            db.query(func.count(AIUsageLog.id))
            .filter(
                AIUsageLog.business_id == account.business_id,
                AIUsageLog.created_at >= (now - timedelta(seconds=60)),
                AIUsageLog.status != "error",
            )
            .scalar()
            or 0
        )
        if recent_rpm >= eff_rpm:
            raise AITenantQuotaError(
                "Workspace AI requests-per-minute limit reached. Please try again in a few seconds.",
                retry_after_seconds=15.0,
            )

        # 3. Daily request & daily token limits (since UTC midnight)
        day_start = _utc_day_start()
        eff_daily_req = account.daily_request_limit or self._settings.ai_default_daily_request_limit
        eff_daily_tok = account.daily_token_limit or self._settings.ai_default_daily_token_limit
        daily_stats = (
            db.query(
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
            )
            .filter(
                AIUsageLog.business_id == account.business_id,
                AIUsageLog.created_at >= day_start,
                AIUsageLog.status == "ok",
            )
            .first()
        )
        daily_reqs = int(daily_stats[0] or 0) if daily_stats else 0
        daily_toks = int(daily_stats[1] or 0) if daily_stats else 0
        if daily_reqs >= eff_daily_req:
            raise AITenantQuotaError(
                f"Workspace daily AI request limit ({eff_daily_req}/day) reached.",
                retry_after_seconds=60.0,
            )
        if daily_toks >= eff_daily_tok:
            raise AITenantQuotaError(
                f"Workspace daily AI token limit ({eff_daily_tok} tokens/day) reached.",
                retry_after_seconds=60.0,
            )

    def reserve_credits(
        self,
        db: Session,
        *,
        business_id: int,
        user_id: Optional[int],
        operation_type: str,
        model_name: Optional[str],
        estimated_reserve_units: int,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        conversation_id: Optional[int] = None,
        document_id: Optional[int] = None,
        processing_stage: Optional[str] = None,
        provider: str = "gemini",
        reason: Optional[str] = None,
    ) -> CreditReservation:
        """Atomically validate policies, prevent duplicates, reserve credits, and release DB lock."""
        req_id = request_id or str(uuid4())
        base_idem = (idempotency_key or "").strip() or req_id
        account = self.ensure_credit_account(db, business_id=business_id, user_id=user_id)

        # Idempotency check BEFORE reserving
        existing_logs = (
            db.query(AIUsageLog)
            .filter(
                AIUsageLog.business_id == business_id,
                AIUsageLog.idempotency_key == base_idem,
            )
            .order_by(AIUsageLog.id.desc())
            .all()
        )
        for prev in existing_logs:
            if prev.status == "reserved":
                raise AICreditError(
                    "An identical AI request is already running. Please wait for it to finish.",
                    error_code=AIErrorCode.DUPLICATE_INFLIGHT_REQUEST,
                    http_status=409,
                    retryable=True,
                    retry_after_seconds=2.0,
                )
            if prev.status == "ok":
                return CreditReservation(
                    reservation_active=False,
                    business_id=business_id,
                    usage_log_id=prev.id,
                    request_id=prev.request_id or req_id,
                    base_idempotency_key=base_idem,
                    attempt_idempotency_key=base_idem,
                    reserved_units=0,
                    pricing_version=prev.pricing_version or self._pricing.pricing_version,
                    idempotent_replay=True,
                    replay_conversation_id=prev.conversation_id,
                )

        prior_failures = sum(1 for row in existing_logs if row.status == "error")
        attempt_idem = base_idem if prior_failures == 0 else f"{base_idem}:retry{prior_failures + 1}"

        reserve_amt = max(0, int(estimated_reserve_units)) if self._settings.ai_credits_enforced else 0
        self.check_tenant_policies(db, account=account, estimated_reserve_units=reserve_amt)

        now = _utcnow()
        avail_after = account.available_units
        resv_after = account.reserved_units

        if reserve_amt > 0:
            stmt = (
                update(AICreditAccount)
                .where(
                    AICreditAccount.business_id == business_id,
                    AICreditAccount.status == "ACTIVE",
                    AICreditAccount.available_units >= reserve_amt,
                )
                .values(
                    available_units=AICreditAccount.available_units - reserve_amt,
                    reserved_units=AICreditAccount.reserved_units + reserve_amt,
                    updated_at=now,
                )
                .returning(AICreditAccount.available_units, AICreditAccount.reserved_units)
            )
            row = db.execute(stmt).first()
            if row is None:
                db.rollback()
                db.refresh(account)
                if account.status != "ACTIVE":
                    raise AICreditError(
                        "Workspace AI account is not active.",
                        error_code=AIErrorCode.AI_ACCOUNT_SUSPENDED,
                        http_status=403,
                    )
                avail_display = credits_float(account.available_units)
                need_display = credits_float(reserve_amt)
                raise AICreditError(
                    f"Insufficient AI credits ({avail_display} available, {need_display} required for this request). Contact your administrator to add credits.",
                    error_code=AIErrorCode.INSUFFICIENT_AI_CREDITS,
                    http_status=402,
                    retryable=False,
                )
            avail_after = int(row[0])
            resv_after = int(row[1])

        usage_log = AIUsageLog(
            business_id=business_id,
            user_id=user_id,
            document_id=document_id,
            conversation_id=conversation_id,
            provider=provider,
            operation_type=operation_type,
            processing_stage=processing_stage,
            model_name=model_name,
            request_id=req_id,
            idempotency_key=base_idem,
            pricing_version=self._pricing.pricing_version,
            credits_reserved_units=reserve_amt,
            credits_consumed_units=0,
            credits_refunded_units=0,
            usage_source="pending",
            status="reserved",
            created_at=now,
        )
        db.add(usage_log)
        db.flush()

        if reserve_amt > 0:
            tx = AICreditTransaction(
                transaction_uid=str(uuid4()),
                business_id=business_id,
                user_id=user_id,
                usage_log_id=usage_log.id,
                request_id=req_id,
                idempotency_key=attempt_idem,
                transaction_type="REQUEST_RESERVATION",
                credit_delta_units=-reserve_amt,
                amount_units=reserve_amt,
                available_before_units=avail_after + reserve_amt,
                available_after_units=avail_after,
                reserved_before_units=resv_after - reserve_amt,
                reserved_after_units=resv_after,
                status="POSTED",
                operation_type=operation_type,
                pricing_version=self._pricing.pricing_version,
                reason=reason or f"Credit reservation for {operation_type}",
            )
            db.add(tx)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise AICreditError(
                "Duplicate request detected; please wait before retrying.",
                error_code=AIErrorCode.DUPLICATE_INFLIGHT_REQUEST,
                http_status=409,
                retryable=True,
                retry_after_seconds=2.0,
            ) from exc

        return CreditReservation(
            reservation_active=True,
            business_id=business_id,
            usage_log_id=usage_log.id,
            request_id=req_id,
            base_idempotency_key=base_idem,
            attempt_idempotency_key=attempt_idem,
            reserved_units=reserve_amt,
            pricing_version=self._pricing.pricing_version,
            idempotent_replay=False,
        )

    def capture_usage(
        self,
        db: Session,
        *,
        reservation: CreditReservation,
        breakdown: CostBreakdown,
        duration_ms: float,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        document_id: Optional[int] = None,
        embedding_inputs: Optional[int] = None,
        provider_metadata: Optional[Dict[str, Any]] = None,
    ) -> AIUsageLog:
        """Atomically capture actual metered credits, refund unused reservation delta, and persist usage log."""
        if reservation.idempotent_replay:
            existing = db.query(AIUsageLog).filter(AIUsageLog.id == reservation.usage_log_id).first()
            assert existing is not None
            return existing

        usage_log = (
            db.query(AIUsageLog)
            .filter(
                AIUsageLog.id == reservation.usage_log_id,
                AIUsageLog.business_id == reservation.business_id,
            )
            .first()
        )
        assert usage_log is not None

        if usage_log.status != "reserved":
            return usage_log

        now = _utcnow()
        reserved = max(0, int(reservation.reserved_units))
        if self._settings.ai_credits_enforced and reserved > 0:
            captured = min(reserved, max(0, int(breakdown.units)))
            refunded = max(0, reserved - captured)
        else:
            captured = 0
            refunded = 0

        if reserved > 0:
            existing_capture = (
                db.query(AICreditTransaction)
                .filter(
                    AICreditTransaction.business_id == reservation.business_id,
                    AICreditTransaction.transaction_type == "REQUEST_CAPTURE",
                    AICreditTransaction.idempotency_key == reservation.attempt_idempotency_key,
                )
                .first()
            )
            if existing_capture is None:
                stmt = (
                    update(AICreditAccount)
                    .where(
                        AICreditAccount.business_id == reservation.business_id,
                        AICreditAccount.reserved_units >= reserved,
                    )
                    .values(
                        reserved_units=AICreditAccount.reserved_units - reserved,
                        available_units=AICreditAccount.available_units + refunded,
                        lifetime_consumed_units=AICreditAccount.lifetime_consumed_units + captured,
                        lifetime_refunded_units=AICreditAccount.lifetime_refunded_units + refunded,
                        updated_at=now,
                    )
                    .returning(AICreditAccount.available_units, AICreditAccount.reserved_units)
                )
                row = db.execute(stmt).first()
                if row is not None:
                    avail_after = int(row[0])
                    resv_after = int(row[1])
                    resv_before = resv_after + reserved
                    avail_before = avail_after - refunded

                    if captured > 0:
                        db.add(
                            AICreditTransaction(
                                transaction_uid=str(uuid4()),
                                business_id=reservation.business_id,
                                user_id=user_id,
                                usage_log_id=usage_log.id,
                                request_id=reservation.request_id,
                                idempotency_key=reservation.attempt_idempotency_key,
                                transaction_type="REQUEST_CAPTURE",
                                credit_delta_units=0,
                                amount_units=captured,
                                available_before_units=avail_before,
                                available_after_units=avail_before,
                                reserved_before_units=resv_before,
                                reserved_after_units=resv_before - captured,
                                status="POSTED",
                                operation_type=breakdown.operation_type,
                                pricing_version=breakdown.pricing_version,
                                reason=f"Captured credits for {breakdown.operation_type} ({breakdown.model_name})",
                            )
                        )
                    if refunded > 0:
                        db.add(
                            AICreditTransaction(
                                transaction_uid=str(uuid4()),
                                business_id=reservation.business_id,
                                user_id=user_id,
                                usage_log_id=usage_log.id,
                                request_id=reservation.request_id,
                                idempotency_key=reservation.attempt_idempotency_key,
                                transaction_type="REQUEST_REFUND",
                                credit_delta_units=refunded,
                                amount_units=refunded,
                                available_before_units=avail_before,
                                available_after_units=avail_after,
                                reserved_before_units=resv_before - captured,
                                reserved_after_units=resv_after,
                                status="POSTED",
                                operation_type=breakdown.operation_type,
                                pricing_version=breakdown.pricing_version,
                                reason=f"Unused reserved credit refund for {breakdown.operation_type}",
                            )
                        )

        usage_log.model_name = breakdown.model_name
        usage_log.conversation_id = conversation_id if conversation_id is not None else usage_log.conversation_id
        usage_log.document_id = document_id if document_id is not None else usage_log.document_id
        usage_log.prompt_tokens = breakdown.prompt_tokens
        usage_log.candidates_tokens = breakdown.candidates_tokens
        usage_log.total_tokens = breakdown.total_tokens
        usage_log.estimated_tokens = breakdown.estimated_tokens
        usage_log.embedding_inputs = embedding_inputs if embedding_inputs is not None else usage_log.embedding_inputs
        usage_log.pricing_version = breakdown.pricing_version
        usage_log.usage_source = breakdown.usage_source
        usage_log.credits_consumed_units = captured
        usage_log.credits_refunded_units = refunded
        usage_log.duration_ms = round(float(duration_ms), 2)
        usage_log.status = "ok"
        if provider_metadata is not None:
            usage_log.provider_metadata_json = json.dumps(provider_metadata, ensure_ascii=False, default=str)

        db.commit()
        db.refresh(usage_log)
        return usage_log

    def refund_failed_reservation(
        self,
        db: Session,
        *,
        reservation: CreditReservation,
        error_code: str,
        error_category: str,
        duration_ms: float,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        document_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> AIUsageLog:
        """Idempotently refund 100% of reserved credits for failed/quota-exhausted operations."""
        if reservation.idempotent_replay:
            existing = db.query(AIUsageLog).filter(AIUsageLog.id == reservation.usage_log_id).first()
            assert existing is not None
            return existing

        usage_log = (
            db.query(AIUsageLog)
            .filter(
                AIUsageLog.id == reservation.usage_log_id,
                AIUsageLog.business_id == reservation.business_id,
            )
            .first()
        )
        assert usage_log is not None

        if usage_log.status != "reserved":
            return usage_log

        now = _utcnow()
        reserved = max(0, int(reservation.reserved_units))
        if reserved > 0:
            existing_ref = (
                db.query(AICreditTransaction)
                .filter(
                    AICreditTransaction.business_id == reservation.business_id,
                    AICreditTransaction.transaction_type == "REQUEST_REFUND",
                    AICreditTransaction.idempotency_key == reservation.attempt_idempotency_key,
                )
                .first()
            )
            if existing_ref is None:
                stmt = (
                    update(AICreditAccount)
                    .where(
                        AICreditAccount.business_id == reservation.business_id,
                        AICreditAccount.reserved_units >= reserved,
                    )
                    .values(
                        reserved_units=AICreditAccount.reserved_units - reserved,
                        available_units=AICreditAccount.available_units + reserved,
                        lifetime_refunded_units=AICreditAccount.lifetime_refunded_units + reserved,
                        updated_at=now,
                    )
                    .returning(AICreditAccount.available_units, AICreditAccount.reserved_units)
                )
                row = db.execute(stmt).first()
                if row is not None:
                    avail_after = int(row[0])
                    resv_after = int(row[1])
                    db.add(
                        AICreditTransaction(
                            transaction_uid=str(uuid4()),
                            business_id=reservation.business_id,
                            user_id=user_id,
                            usage_log_id=usage_log.id,
                            request_id=reservation.request_id,
                            idempotency_key=reservation.attempt_idempotency_key,
                            transaction_type="REQUEST_REFUND",
                            credit_delta_units=reserved,
                            amount_units=reserved,
                            available_before_units=avail_after - reserved,
                            available_after_units=avail_after,
                            reserved_before_units=resv_after + reserved,
                            reserved_after_units=resv_after,
                            status="POSTED",
                            operation_type=usage_log.operation_type,
                            pricing_version=usage_log.pricing_version,
                            reason=reason or f"Full refund due to failed operation ({error_code})",
                        )
                    )

        usage_log.conversation_id = conversation_id if conversation_id is not None else usage_log.conversation_id
        usage_log.document_id = document_id if document_id is not None else usage_log.document_id
        usage_log.status = "error"
        usage_log.usage_source = "not_billed"
        usage_log.error_code = error_code
        usage_log.error_category = error_category
        usage_log.credits_consumed_units = 0
        usage_log.credits_refunded_units = reserved
        usage_log.duration_ms = round(float(duration_ms), 2)
        db.commit()
        db.refresh(usage_log)
        return usage_log

    def admin_adjust_credits(
        self,
        db: Session,
        *,
        business_id: int,
        admin_user_id: int,
        credit_delta: Decimal | float | int | str,
        transaction_type: str,
        reason: str,
        idempotency_key: str,
        billing_reference: Optional[str] = None,
    ) -> Tuple[AICreditAccount, AICreditTransaction]:
        """Atomically grant, adjust, purchase, or expire tenant credits with mandatory audit reason."""
        tx_type = transaction_type.strip().upper()
        if tx_type not in VALID_ADMIN_TX_TYPES:
            raise AIInvalidRequestError(f"Unsupported transaction_type {transaction_type!r}.", provider="billing")
        clean_reason = (reason or "").strip()
        if len(clean_reason) < 3:
            raise AIInvalidRequestError("A clear audit reason is required for credit adjustments.", provider="billing")
        clean_idem = (idempotency_key or "").strip()
        if not clean_idem:
            raise AIInvalidRequestError("idempotency_key is required for credit adjustments.", provider="billing")

        delta_units = to_signed_credit_units(credit_delta)
        if delta_units == 0:
            raise AIInvalidRequestError("Credit adjustment amount must be non-zero.", provider="billing")
        if tx_type in ("INITIAL_GRANT", "PURCHASE", "PROMOTIONAL_CREDIT", "PLAN_ALLOCATION") and delta_units < 0:
            raise AIInvalidRequestError(f"{tx_type} requires a positive credit amount.", provider="billing")
        if tx_type == "EXPIRATION" and delta_units > 0:
            delta_units = -delta_units

        account = self.ensure_credit_account(db, business_id=business_id, user_id=admin_user_id)

        # Idempotent replay guard
        existing_tx = (
            db.query(AICreditTransaction)
            .filter(
                AICreditTransaction.business_id == business_id,
                AICreditTransaction.transaction_type == tx_type,
                AICreditTransaction.idempotency_key == clean_idem,
            )
            .first()
        )
        if existing_tx is not None:
            return account, existing_tx

        now = _utcnow()
        abs_units = abs(delta_units)
        conds = [AICreditAccount.business_id == business_id]
        if delta_units < 0:
            conds.append(AICreditAccount.available_units >= abs_units)

        grant_inc = delta_units if delta_units > 0 else 0
        stmt = (
            update(AICreditAccount)
            .where(*conds)
            .values(
                available_units=AICreditAccount.available_units + delta_units,
                lifetime_granted_units=AICreditAccount.lifetime_granted_units + grant_inc,
                updated_at=now,
            )
            .returning(AICreditAccount.available_units, AICreditAccount.reserved_units)
        )
        row = db.execute(stmt).first()
        if row is None:
            db.rollback()
            raise AICreditError(
                "Credit adjustment would result in a negative balance.",
                error_code=AIErrorCode.INSUFFICIENT_AI_CREDITS,
                http_status=400,
                retryable=False,
            )

        avail_after = int(row[0])
        resv_after = int(row[1])
        tx = AICreditTransaction(
            transaction_uid=str(uuid4()),
            business_id=business_id,
            user_id=admin_user_id,
            request_id=str(uuid4()),
            idempotency_key=clean_idem,
            transaction_type=tx_type,
            credit_delta_units=delta_units,
            amount_units=abs_units,
            available_before_units=avail_after - delta_units,
            available_after_units=avail_after,
            reserved_before_units=resv_after,
            reserved_after_units=resv_after,
            status="POSTED",
            operation_type="admin_credit_adjustment",
            billing_reference=(billing_reference or "").strip() or None,
            pricing_version=self._pricing.pricing_version,
            reason=clean_reason,
        )
        db.add(tx)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            replay = (
                db.query(AICreditTransaction)
                .filter(
                    AICreditTransaction.business_id == business_id,
                    AICreditTransaction.transaction_type == tx_type,
                    AICreditTransaction.idempotency_key == clean_idem,
                )
                .first()
            )
            if replay is not None:
                db.refresh(account)
                return account, replay
            raise AICreditError("Concurrent duplicate adjustment blocked.", http_status=409) from exc

        db.refresh(account)
        db.refresh(tx)
        return account, tx

    def update_tenant_policy(
        self,
        db: Session,
        *,
        business_id: int,
        admin_user_id: int,
        reason: str,
        status: Optional[str] = None,
        plan_tier: Optional[str] = None,
        rpm_limit: Optional[int] = None,
        daily_request_limit: Optional[int] = None,
        daily_token_limit: Optional[int] = None,
        max_credits_per_operation: Optional[Decimal | float | int] = None,
        max_concurrent_requests: Optional[int] = None,
        max_context_turns: Optional[int] = None,
        max_document_mb: Optional[int] = None,
    ) -> AICreditAccount:
        clean_reason = (reason or "").strip()
        if len(clean_reason) < 3:
            raise AIInvalidRequestError("A clear audit reason is required when updating usage policies.", provider="billing")
        account = self.ensure_credit_account(db, business_id=business_id, user_id=admin_user_id)
        if status is not None:
            st = status.strip().upper()
            if st not in VALID_ACCOUNT_STATUSES:
                raise AIInvalidRequestError(f"Unsupported account status {status!r}.", provider="billing")
            account.status = st
        if plan_tier is not None and plan_tier.strip():
            account.plan_tier = plan_tier.strip().lower()[:32]
        if rpm_limit is not None:
            account.rpm_limit = max(1, min(5000, int(rpm_limit)))
        if daily_request_limit is not None:
            account.daily_request_limit = max(1, min(1000000, int(daily_request_limit)))
        if daily_token_limit is not None:
            account.daily_token_limit = max(100, min(100000000, int(daily_token_limit)))
        if max_credits_per_operation is not None:
            account.max_credits_per_operation_units = max(1, to_credit_units(max_credits_per_operation))
        if max_concurrent_requests is not None:
            account.max_concurrent_requests = max(1, min(100, int(max_concurrent_requests)))
        if max_context_turns is not None:
            account.max_context_turns = max(2, min(30, int(max_context_turns)))
        if max_document_mb is not None:
            account.max_document_mb = max(1, min(100, int(max_document_mb)))

        account.policy_override_reason = clean_reason
        account.policy_updated_by_user_id = admin_user_id
        account.updated_at = _utcnow()
        db.commit()
        db.refresh(account)
        return account

    def list_transactions(
        self,
        db: Session,
        *,
        business_id: int,
        transaction_type: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Tuple[List[AICreditTransaction], int]:
        q = db.query(AICreditTransaction).filter(AICreditTransaction.business_id == business_id)
        if transaction_type and transaction_type.strip():
            q = q.filter(AICreditTransaction.transaction_type == transaction_type.strip().upper())
        total = q.count()
        rows = (
            q.order_by(AICreditTransaction.id.desc())
            .offset(max(0, offset))
            .limit(min(100, max(1, limit)))
            .all()
        )
        return rows, total

    def list_usage_logs(
        self,
        db: Session,
        *,
        business_id: int,
        status_filter: Optional[str] = None,
        operation_type: Optional[str] = None,
        error_category: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Tuple[List[AIUsageLog], int]:
        q = db.query(AIUsageLog).filter(AIUsageLog.business_id == business_id)
        if status_filter and status_filter.strip():
            q = q.filter(AIUsageLog.status == status_filter.strip().lower())
        if operation_type and operation_type.strip():
            q = q.filter(AIUsageLog.operation_type == operation_type.strip())
        if error_category and error_category.strip():
            q = q.filter(AIUsageLog.error_category == error_category.strip())
        total = q.count()
        rows = (
            q.order_by(AIUsageLog.id.desc())
            .offset(max(0, offset))
            .limit(min(100, max(1, limit)))
            .all()
        )
        return rows, total

    def get_usage_summary(
        self,
        db: Session,
        *,
        business_id: int,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Aggregate real metered usage by operation, model, error status, and day."""
        account = self.ensure_credit_account(db, business_id=business_id)
        window_days = max(1, min(365, int(days)))
        since = _utcnow() - timedelta(days=window_days)

        agg = (
            db.query(
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(case((AIUsageLog.status == "ok", 1), else_=0)), 0),
                func.coalesce(func.sum(case((AIUsageLog.status == "error", 1), else_=0)), 0),
                func.coalesce(func.sum(case((AIUsageLog.error_code == "QUOTA_EXHAUSTED", 1), else_=0)), 0),
                func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.candidates_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.credits_consumed_units), 0),
                func.coalesce(func.sum(AIUsageLog.credits_refunded_units), 0),
            )
            .filter(
                AIUsageLog.business_id == business_id,
                AIUsageLog.created_at >= since,
            )
            .first()
        )

        op_rows = (
            db.query(
                AIUsageLog.operation_type,
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.credits_consumed_units), 0),
                func.coalesce(func.sum(case((AIUsageLog.status == "error", 1), else_=0)), 0),
            )
            .filter(AIUsageLog.business_id == business_id, AIUsageLog.created_at >= since)
            .group_by(AIUsageLog.operation_type)
            .order_by(func.count(AIUsageLog.id).desc())
            .all()
        )

        model_rows = (
            db.query(
                func.coalesce(AIUsageLog.model_name, "unknown"),
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.credits_consumed_units), 0),
            )
            .filter(AIUsageLog.business_id == business_id, AIUsageLog.created_at >= since)
            .group_by(func.coalesce(AIUsageLog.model_name, "unknown"))
            .order_by(func.count(AIUsageLog.id).desc())
            .all()
        )

        # Daily bucket aggregation cleanly computed in Python for identical SQLite & PostgreSQL behavior
        raw_trend_rows = (
            db.query(
                AIUsageLog.created_at,
                AIUsageLog.status,
                AIUsageLog.total_tokens,
                AIUsageLog.credits_consumed_units,
                AIUsageLog.credits_refunded_units,
            )
            .filter(AIUsageLog.business_id == business_id, AIUsageLog.created_at >= since)
            .order_by(AIUsageLog.created_at.asc())
            .all()
        )
        trend_map: Dict[str, Dict[str, Any]] = {}
        for created_dt, st, tot_tok, cons_u, ref_u in raw_trend_rows:
            day_key = created_dt.strftime("%Y-%m-%d") if created_dt else "unknown"
            bucket = trend_map.setdefault(
                day_key,
                {
                    "date": day_key,
                    "requests": 0,
                    "failed_requests": 0,
                    "total_tokens": 0,
                    "credits_consumed_units": 0,
                    "credits_refunded_units": 0,
                },
            )
            bucket["requests"] += 1
            if st == "error":
                bucket["failed_requests"] += 1
            bucket["total_tokens"] += int(tot_tok or 0)
            bucket["credits_consumed_units"] += int(cons_u or 0)
            bucket["credits_refunded_units"] += int(ref_u or 0)

        daily_trends = [
            {
                "date": b["date"],
                "requests": b["requests"],
                "failed_requests": b["failed_requests"],
                "total_tokens": b["total_tokens"],
                "credits_consumed": credits_float(b["credits_consumed_units"]),
                "credits_refunded": credits_float(b["credits_refunded_units"]),
            }
            for b in trend_map.values()
        ]

        return {
            "window_days": window_days,
            "account": serialize_credit_account(account, self._settings),
            "totals": {
                "requests": int(agg[0] or 0) if agg else 0,
                "successful_requests": int(agg[1] or 0) if agg else 0,
                "failed_requests": int(agg[2] or 0) if agg else 0,
                "provider_quota_failures": int(agg[3] or 0) if agg else 0,
                "input_tokens": int(agg[4] or 0) if agg else 0,
                "output_tokens": int(agg[5] or 0) if agg else 0,
                "total_tokens": int(agg[6] or 0) if agg else 0,
                "credits_consumed": credits_float(int(agg[7] or 0) if agg else 0),
                "credits_refunded": credits_float(int(agg[8] or 0) if agg else 0),
            },
            "by_operation": [
                {
                    "operation_type": r[0],
                    "requests": int(r[1] or 0),
                    "total_tokens": int(r[2] or 0),
                    "credits_consumed": credits_float(int(r[3] or 0)),
                    "failed_requests": int(r[4] or 0),
                }
                for r in op_rows
            ],
            "by_model": [
                {
                    "model_name": r[0],
                    "requests": int(r[1] or 0),
                    "total_tokens": int(r[2] or 0),
                    "credits_consumed": credits_float(int(r[3] or 0)),
                }
                for r in model_rows
            ],
            "daily_trends": daily_trends,
        }
