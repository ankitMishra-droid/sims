"""FastAPI lifespan runtime container holding Phase 7/8 AI singletons."""

from __future__ import annotations

import logging
from typing import Optional

from ...core.ai_config import AIProviderSettings
from ...core.ai_exceptions import AIServiceError
from ...core.ai_logging import get_ai_logger, log_ai_event
from ...core.ai_pricing import AIPricingSchedule
from .circuit_breaker import ProviderCircuitBreaker
from .credit_service import AICreditService
from .gemini_client import GeminiClientManager
from .gemini_embeddings import GeminiEmbeddingService
from .gemini_llm import GeminiLLMService
from .health import AIHealthService
from .pipeline import VectorKnowledgePipeline
from .qdrant_service import QdrantVectorService


class AIRuntimeContainer:
    """Manages startup/shutdown lifecycle and dependency composition for AI services."""

    def __init__(
        self,
        settings: Optional[AIProviderSettings] = None,
        *,
        gemini_client: Optional[GeminiClientManager] = None,
        qdrant_service: Optional[QdrantVectorService] = None,
        circuit_breaker: Optional[ProviderCircuitBreaker] = None,
        pricing: Optional[AIPricingSchedule] = None,
        credit_service: Optional[AICreditService] = None,
    ) -> None:
        self.settings = settings or AIProviderSettings.from_env()
        self.pricing = pricing or AIPricingSchedule.from_env()
        self.credit_service = credit_service or AICreditService(self.settings, self.pricing)
        self.gemini_client = gemini_client or GeminiClientManager(self.settings)
        self.circuit_breaker = circuit_breaker or ProviderCircuitBreaker(
            enabled=self.settings.gemini_circuit_breaker_enabled,
            failure_threshold=self.settings.gemini_circuit_failure_threshold,
            recovery_seconds=self.settings.gemini_circuit_recovery_seconds,
            quota_cooldown_seconds=self.settings.gemini_quota_cooldown_seconds,
            half_open_max_calls=self.settings.gemini_circuit_half_open_max_calls,
            max_concurrent_requests=self.settings.gemini_max_concurrent_requests,
        )
        self.llm_service = GeminiLLMService(
            self.gemini_client,
            circuit_breaker=self.circuit_breaker,
        )
        self.embedding_service = GeminiEmbeddingService(
            self.gemini_client,
            circuit_breaker=self.circuit_breaker,
        )
        self.qdrant_service = qdrant_service or QdrantVectorService(self.settings)
        self.pipeline = VectorKnowledgePipeline(
            embedding_service=self.embedding_service,
            qdrant_service=self.qdrant_service,
            llm_service=self.llm_service,
        )
        self.health_service = AIHealthService(
            settings=self.settings,
            gemini_client=self.gemini_client,
            llm_service=self.llm_service,
            embedding_service=self.embedding_service,
            qdrant_service=self.qdrant_service,
        )
        self._logger = get_ai_logger("container")

    @classmethod
    def from_env(cls) -> "AIRuntimeContainer":
        return cls(settings=AIProviderSettings.from_env())

    def startup(self) -> None:
        """Initialize configuration cleanly without blocking FastAPI boot on Gemini/Qdrant outages."""
        log_ai_event(
            self._logger,
            logging.INFO,
            provider="ai_runtime",
            operation="startup",
            status="initializing",
            gemini_configured=self.gemini_client.is_configured,
            qdrant_configured=self.qdrant_service.is_configured,
            collection_name=self.settings.effective_collection_name,
            llm_model=self.settings.gemini_llm_model,
            fallback_models=list(self.settings.gemini_llm_fallback_models),
            embedding_model=self.settings.gemini_embedding_model,
            embedding_dimensions=self.settings.gemini_embedding_dimensions,
        )
        if not self.gemini_client.is_configured:
            log_ai_event(
                self._logger,
                logging.WARNING,
                provider="gemini",
                operation="startup_config_check",
                status="unconfigured",
                error_code="PROVIDER_UNCONFIGURED",
            )
        if self.settings.ai_strict_startup:
            try:
                self.gemini_client.get_client()
                self.qdrant_service.ensure_collection()
            except AIServiceError as exc:
                log_ai_event(
                    self._logger,
                    logging.ERROR,
                    provider=exc.provider,
                    operation="startup_strict",
                    status="failed",
                    error_code=exc.error_code.value,
                )
                raise

    def shutdown(self) -> None:
        """Signal active retries to stop and gracefully close Gemini and Qdrant transports."""
        self.gemini_client.close()
        self.qdrant_service.close()
        log_ai_event(
            self._logger,
            logging.INFO,
            provider="ai_runtime",
            operation="shutdown",
            status="ok",
        )
