"""End-to-end Gemini-to-Qdrant embedding, indexing, retrieval, and grounded generation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from .gemini_embeddings import GeminiEmbeddingService
from .gemini_llm import GroundedContextChunk, GeminiLLMService, LLMGenerationResult
from .qdrant_service import (
    QdrantSearchResult,
    QdrantUpsertResult,
    QdrantVectorService,
    VectorDocumentRecord,
)


@dataclass(frozen=True)
class KnowledgeChunkInput:
    document_id: str
    source_id: str
    source_type: str
    chunk_id: str
    text: str
    document_version: str = "v1"
    content_type: str = "text/plain"
    language: str = "en"
    workspace_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GroundedAnswerResult:
    llm_result: LLMGenerationResult
    search_result: QdrantSearchResult


class VectorKnowledgePipeline:
    """Composes Gemini embeddings, Qdrant tenant storage, and Gemini grounded synthesis."""

    def __init__(
        self,
        *,
        embedding_service: GeminiEmbeddingService,
        qdrant_service: QdrantVectorService,
        llm_service: Optional[GeminiLLMService] = None,
    ) -> None:
        self._embeddings = embedding_service
        self._qdrant = qdrant_service
        self._llm = llm_service

    def index_chunks(
        self,
        tenant_id: int,
        chunks: Sequence[KnowledgeChunkInput],
        *,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> QdrantUpsertResult:
        req_id = request_id or str(uuid4())
        texts = [c.text for c in chunks]
        emb_batch = self._embeddings.embed_documents(
            texts,
            tenant_id=tenant_id,
            request_id=req_id,
        )
        settings = self._embeddings._settings
        records: List[VectorDocumentRecord] = [
            VectorDocumentRecord(
                tenant_id=tenant_id,
                workspace_id=chunk.workspace_id,
                document_id=chunk.document_id,
                source_id=chunk.source_id,
                source_type=chunk.source_type,
                chunk_id=chunk.chunk_id,
                document_version=chunk.document_version,
                embedding_model=emb_batch.model,
                embedding_version=settings.gemini_embedding_version,
                content_type=chunk.content_type,
                language=chunk.language,
                text=chunk.text,
                metadata=chunk.metadata,
            )
            for chunk in chunks
        ]
        return self._qdrant.upsert_documents(
            tenant_id,
            records,
            emb_batch.vectors,
            collection_name=collection_name,
            request_id=req_id,
        )

    def semantic_search(
        self,
        tenant_id: int,
        query: str,
        *,
        limit: int = 5,
        score_threshold: Optional[float] = None,
        workspace_id: Optional[int] = None,
        source_types: Optional[Sequence[str]] = None,
        document_ids: Optional[Sequence[str]] = None,
        languages: Optional[Sequence[str]] = None,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> QdrantSearchResult:
        req_id = request_id or str(uuid4())
        query_vec = self._embeddings.embed_query(
            query,
            tenant_id=tenant_id,
            request_id=req_id,
        )
        return self._qdrant.search(
            tenant_id,
            query_vec,
            limit=limit,
            score_threshold=score_threshold,
            workspace_id=workspace_id,
            source_types=source_types,
            document_ids=document_ids,
            languages=languages,
            collection_name=collection_name,
            request_id=req_id,
        )

    def answer_with_retrieved_context(
        self,
        tenant_id: int,
        query: str,
        *,
        limit: int = 5,
        score_threshold: Optional[float] = None,
        workspace_id: Optional[int] = None,
        source_types: Optional[Sequence[str]] = None,
        collection_name: Optional[str] = None,
        system_instruction: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> GroundedAnswerResult:
        if self._llm is None:
            raise RuntimeError("GeminiLLMService is required for grounded synthesis.")
        req_id = request_id or str(uuid4())
        search_result = self.semantic_search(
            tenant_id,
            query,
            limit=limit,
            score_threshold=score_threshold,
            workspace_id=workspace_id,
            source_types=source_types,
            collection_name=collection_name,
            request_id=req_id,
        )
        context_chunks = [
            GroundedContextChunk(
                chunk_id=hit.chunk_id,
                source_id=hit.source_id,
                source_type=hit.source_type,
                text=hit.text,
                score=hit.score,
            )
            for hit in search_result.hits
        ]
        llm_result = self._llm.generate_grounded_answer(
            query,
            context_chunks=context_chunks,
            system_instruction=system_instruction,
            tenant_id=tenant_id,
            request_id=req_id,
        )
        return GroundedAnswerResult(
            llm_result=llm_result,
            search_result=search_result,
        )
