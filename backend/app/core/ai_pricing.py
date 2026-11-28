"""Centralized, versioned AI credit pricing engine using exact scaled integer units (no float drift)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import os
from typing import Dict, Mapping, Optional, Sequence

# 1.000 credit = 1000 integer micro-units in persistent DB columns for zero IEEE-754 drift on SQLite & PostgreSQL
CREDIT_SCALE = 1000
_SCALE_DEC = Decimal(CREDIT_SCALE)
_UNIT_QUANT = Decimal("0.001")


def to_credit_units(credits: Decimal | int | float | str) -> int:
    """Convert human credit amount into exact non-negative integer scaled units (1 credit = 1000 units)."""
    dec = Decimal(str(credits))
    if dec < Decimal("0"):
        raise ValueError("Credit magnitude cannot be negative.")
    scaled = (dec * _SCALE_DEC).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled)


def to_signed_credit_units(credits: Decimal | int | float | str) -> int:
    dec = Decimal(str(credits))
    scaled = (dec * _SCALE_DEC).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled)


def from_credit_units(units: int) -> Decimal:
    """Convert stored integer micro-units back into exact Decimal credits (3 decimal places)."""
    return (Decimal(int(units)) / _SCALE_DEC).quantize(_UNIT_QUANT)


def credits_float(units: int) -> float:
    return float(from_credit_units(units))


@dataclass(frozen=True)
class CostBreakdown:
    """Itemized billing computation for one AI operation without storing provider secret details."""

    operation_type: str
    pricing_version: str
    model_name: str
    prompt_tokens: int
    candidates_tokens: int
    thoughts_tokens: int
    total_tokens: int
    estimated_tokens: int
    usage_source: str  # provider_reported | estimated_fallback | not_billed
    units: int
    credits: Decimal


@dataclass(frozen=True)
class AIPricingSchedule:
    """Versioned configurable pricing policy separating provider cost estimation & customer credits.

    NOTE: Default credit rates are configurable engineering placeholders and require commercial
    approval before general production billing rollouts.
    """

    pricing_version: str = "2026-11-phase9-v1"
    rate_approval_required: bool = True

    # Text generation configurable credit rates
    text_base_credits: Decimal = Decimal("0.100")
    text_input_per_1k_credits: Decimal = Decimal("0.500")
    text_output_per_1k_credits: Decimal = Decimal("1.500")
    text_min_credits: Decimal = Decimal("0.050")
    text_reserve_cap_credits: Decimal = Decimal("10.000")

    # Embedding configurable credit rates
    embedding_base_credits: Decimal = Decimal("0.010")
    embedding_per_1k_tokens_credits: Decimal = Decimal("0.100")
    embedding_min_credits: Decimal = Decimal("0.010")

    # Document ingestion orchestration fee + chunk fee
    ingestion_base_credits: Decimal = Decimal("0.100")
    ingestion_per_chunk_credits: Decimal = Decimal("0.050")

    # Vector retrieval search
    retrieval_base_credits: Decimal = Decimal("0.020")

    # Model-specific multipliers (extensible via config)
    model_multipliers: Dict[str, Decimal] = field(
        default_factory=lambda: {
            "gemini-3.5-flash-lite": Decimal("1.0"),
            "gemini-3.1-flash-lite": Decimal("1.0"),
            "gemini-3.8-flash": Decimal("1.25"),
            "gemini-embedding-001": Decimal("1.0"),
        }
    )

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AIPricingSchedule":
        src: Mapping[str, str] = os.environ if env is None else env

        def _dec(name: str, default: Decimal) -> Decimal:
            raw = src.get(name)
            if raw is None or not str(raw).strip():
                return default
            return max(Decimal("0"), Decimal(str(raw).strip()))

        return cls(
            pricing_version=(src.get("AI_PRICING_VERSION") or "2026-11-phase9-v1").strip(),
            rate_approval_required=(src.get("AI_RATES_APPROVED", "false").strip().lower() != "true"),
            text_base_credits=_dec("AI_PRICE_CHAT_BASE", Decimal("0.100")),
            text_input_per_1k_credits=_dec("AI_PRICE_CHAT_INPUT_PER_1K", Decimal("0.500")),
            text_output_per_1k_credits=_dec("AI_PRICE_CHAT_OUTPUT_PER_1K", Decimal("1.500")),
            text_min_credits=_dec("AI_PRICE_CHAT_MIN", Decimal("0.050")),
            text_reserve_cap_credits=_dec("AI_PRICE_CHAT_RESERVE_CAP", Decimal("10.000")),
            embedding_base_credits=_dec("AI_PRICE_EMBED_BASE", Decimal("0.010")),
            embedding_per_1k_tokens_credits=_dec("AI_PRICE_EMBED_PER_1K", Decimal("0.100")),
            embedding_min_credits=_dec("AI_PRICE_EMBED_MIN", Decimal("0.010")),
            ingestion_base_credits=_dec("AI_PRICE_INGEST_BASE", Decimal("0.100")),
            ingestion_per_chunk_credits=_dec("AI_PRICE_INGEST_PER_CHUNK", Decimal("0.050")),
            retrieval_base_credits=_dec("AI_PRICE_RETRIEVAL_BASE", Decimal("0.020")),
        )

    def multiplier_for(self, model_name: Optional[str]) -> Decimal:
        if not model_name:
            return Decimal("1.0")
        norm = model_name.strip().lower()
        for key, mult in self.model_multipliers.items():
            if norm.startswith(key.lower()):
                return mult
        return Decimal("1.0")

    def estimate_tokens_from_chars(self, text_len: int) -> int:
        """Conservative token estimation policy when provider usage metadata is absent (~4 chars/token)."""
        if text_len <= 0:
            return 0
        return max(1, (text_len + 3) // 4)

    def estimate_max_chat_reserve_units(
        self,
        *,
        model_name: Optional[str],
        prompt_chars: int = 2000,
        max_output_tokens: int = 1024,
    ) -> int:
        """Estimate conservative upper-bound reservation for a chat turn before invoking Gemini."""
        est_in_tokens = max(128, self.estimate_tokens_from_chars(prompt_chars))
        est_out_tokens = max(128, min(max_output_tokens, 2048))
        mult = self.multiplier_for(model_name)
        est_credits = (
            self.text_base_credits
            + (Decimal(est_in_tokens) / Decimal(1000)) * self.text_input_per_1k_credits
            + (Decimal(est_out_tokens) / Decimal(1000)) * self.text_output_per_1k_credits
        ) * mult
        bounded = max(self.text_min_credits, min(self.text_reserve_cap_credits, est_credits))
        return max(1, to_credit_units(bounded))

    def calculate_text_generation_cost(
        self,
        *,
        model_name: str,
        prompt_tokens: Optional[int],
        candidates_tokens: Optional[int],
        thoughts_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        prompt_chars: int = 0,
        response_chars: int = 0,
    ) -> CostBreakdown:
        """Calculate exact generation cost using provider metadata or conservative estimation fallback."""
        has_provider_usage = (prompt_tokens is not None and prompt_tokens >= 0) or (
            candidates_tokens is not None and candidates_tokens >= 0
        ) or (total_tokens is not None and total_tokens > 0)

        if has_provider_usage:
            in_tok = int(prompt_tokens or 0)
            out_tok = int((candidates_tokens or 0) + (thoughts_tokens or 0))
            if in_tok == 0 and out_tok == 0 and total_tokens:
                in_tok = max(1, int(total_tokens) // 2)
                out_tok = max(0, int(total_tokens) - in_tok)
            tot_tok = max(in_tok + out_tok, int(total_tokens or 0))
            est_tok = tot_tok
            usage_source = "provider_reported"
        else:
            in_tok = self.estimate_tokens_from_chars(max(1, prompt_chars))
            out_tok = self.estimate_tokens_from_chars(max(1, response_chars))
            tot_tok = in_tok + out_tok
            est_tok = tot_tok
            usage_source = "estimated_fallback"

        mult = self.multiplier_for(model_name)
        raw_credits = (
            self.text_base_credits
            + (Decimal(in_tok) / Decimal(1000)) * self.text_input_per_1k_credits
            + (Decimal(out_tok) / Decimal(1000)) * self.text_output_per_1k_credits
        ) * mult
        final_credits = max(self.text_min_credits, raw_credits).quantize(_UNIT_QUANT, rounding=ROUND_CEILING)
        units = max(1, to_credit_units(final_credits))
        return CostBreakdown(
            operation_type="chat_rag",
            pricing_version=self.pricing_version,
            model_name=model_name,
            prompt_tokens=in_tok,
            candidates_tokens=out_tok,
            thoughts_tokens=int(thoughts_tokens or 0),
            total_tokens=tot_tok,
            estimated_tokens=est_tok,
            usage_source=usage_source,
            units=units,
            credits=from_credit_units(units),
        )

    def estimate_embedding_batch_reserve_units(
        self,
        *,
        model_name: Optional[str],
        texts: Sequence[str],
        include_chunk_fee: bool = True,
    ) -> int:
        est_tokens = sum(self.estimate_tokens_from_chars(len(t)) for t in texts)
        mult = self.multiplier_for(model_name)
        chunk_fee = self.ingestion_per_chunk_credits * Decimal(len(texts)) if include_chunk_fee else Decimal("0")
        raw = (
            self.embedding_base_credits
            + (Decimal(est_tokens) / Decimal(1000)) * self.embedding_per_1k_tokens_credits
            + chunk_fee
        ) * mult
        bounded = max(self.embedding_min_credits, raw)
        return max(1, to_credit_units(bounded))

    def calculate_embedding_batch_cost(
        self,
        *,
        model_name: str,
        texts: Sequence[str],
        actual_tokens: Optional[int] = None,
        include_chunk_fee: bool = True,
        operation_type: str = "ingestion_embed",
    ) -> CostBreakdown:
        est_tokens = sum(self.estimate_tokens_from_chars(len(t)) for t in texts)
        has_provider = actual_tokens is not None and actual_tokens > 0
        eff_tokens = int(actual_tokens) if has_provider and actual_tokens is not None else est_tokens
        usage_source = "provider_reported" if has_provider else "estimated_fallback"

        mult = self.multiplier_for(model_name)
        chunk_fee = self.ingestion_per_chunk_credits * Decimal(len(texts)) if include_chunk_fee else Decimal("0")
        raw = (
            self.embedding_base_credits
            + (Decimal(eff_tokens) / Decimal(1000)) * self.embedding_per_1k_tokens_credits
            + chunk_fee
        ) * mult
        final_credits = max(self.embedding_min_credits, raw).quantize(_UNIT_QUANT, rounding=ROUND_CEILING)
        units = max(1, to_credit_units(final_credits))
        return CostBreakdown(
            operation_type=operation_type,
            pricing_version=self.pricing_version,
            model_name=model_name,
            prompt_tokens=eff_tokens,
            candidates_tokens=0,
            thoughts_tokens=0,
            total_tokens=eff_tokens,
            estimated_tokens=est_tokens,
            usage_source=usage_source,
            units=units,
            credits=from_credit_units(units),
        )

    def to_public_dict(self) -> Dict[str, object]:
        return {
            "pricing_version": self.pricing_version,
            "rate_approval_required": self.rate_approval_required,
            "approval_notice": (
                "Default credit rates are configurable placeholders pending explicit commercial approval."
                if self.rate_approval_required
                else "Commercial pricing schedule active."
            ),
            "text_generation": {
                "base_credits": float(self.text_base_credits),
                "input_credits_per_1k_tokens": float(self.text_input_per_1k_credits),
                "output_credits_per_1k_tokens": float(self.text_output_per_1k_credits),
                "min_credits": float(self.text_min_credits),
                "reserve_cap_credits": float(self.text_reserve_cap_credits),
            },
            "embedding": {
                "base_credits": float(self.embedding_base_credits),
                "credits_per_1k_tokens": float(self.embedding_per_1k_tokens_credits),
                "min_credits": float(self.embedding_min_credits),
            },
            "document_ingestion": {
                "base_credits": float(self.ingestion_base_credits),
                "per_chunk_credits": float(self.ingestion_per_chunk_credits),
            },
            "retrieval_search": {
                "base_credits": float(self.retrieval_base_credits),
            },
            "model_multipliers": {k: float(v) for k, v in self.model_multipliers.items()},
        }
