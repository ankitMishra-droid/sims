"""Phase 7 AI infrastructure package for Gemini LLM, embeddings, Qdrant, and health."""

from .container import AIRuntimeContainer
from .gemini_client import GeminiClientManager
from .gemini_embeddings import EmbeddingBatchResult, GeminiEmbeddingService
from .gemini_llm import GroundedContextChunk, GeminiLLMService, LLMGenerationResult, TokenUsage
from .health import AIHealthService, ComponentHealthStatus
from .pipeline import GroundedAnswerResult, KnowledgeChunkInput, VectorKnowledgePipeline
from .qdrant_service import (
    QdrantCollectionStatus,
    QdrantSearchResult,
    QdrantUpsertResult,
    QdrantVectorService,
    VectorDocumentRecord,
    VectorSearchHit,
    compute_deterministic_point_id,
)

__all__ = [
    "AIHealthService",
    "AIRuntimeContainer",
    "ComponentHealthStatus",
    "EmbeddingBatchResult",
    "GeminiClientManager",
    "GeminiEmbeddingService",
    "GeminiLLMService",
    "GroundedAnswerResult",
    "GroundedContextChunk",
    "KnowledgeChunkInput",
    "LLMGenerationResult",
    "QdrantCollectionStatus",
    "QdrantSearchResult",
    "QdrantUpsertResult",
    "QdrantVectorService",
    "TokenUsage",
    "VectorDocumentRecord",
    "VectorKnowledgePipeline",
    "VectorSearchHit",
    "compute_deterministic_point_id",
]
