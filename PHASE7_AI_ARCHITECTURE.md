# SIMS Phase 7 — Enterprise Gemini LLM & Qdrant Integration Architecture

## 1. Overview

Phase 7 establishes the production AI foundation for **SIMS (Smart Inventory Management System)** using the official **Google GenAI SDK (`google-genai==3.6.1`)** and **Qdrant Python Client (`qdrant-client==1.20.0`)**.

All provider logic is cleanly decoupled from FastAPI route handlers, strictly tenant-scoped via SIMS `BusinessContext` (`tenant_id = business_id`), safe under partial/missing credentials during startup, and designed with clean extension hooks for **Phase 8 (RAG ingestion & assistant)**, **Phase 9 (regional AI experience & quota/credits)**, and **Phase 10 (deployment hardening)**.

---

## 2. Module Layout

| Component | Path | Responsibility |
| :--- | :--- | :--- |
| **Configuration** | `backend/app/core/ai_config.py` | Loads and validates `AIProviderSettings` from environment variables, masks secrets in `repr()`, rejects placeholders/invalid dimensions/invalid URLs, computes versioned collection names. |
| **Exceptions & Classifiers** | `backend/app/core/ai_exceptions.py` | Normalizes provider errors into `AIServiceError` subclasses (`AIConfigurationError`, `AIAuthenticationError`, `AIRateLimitError`, `AITransientError`, `AIInvalidRequestError`, `QdrantCollectionMismatchError`, `TenantIsolationError`) and parses HTTP `Retry-After` headers. |
| **Telemetry & Redaction** | `backend/app/core/ai_logging.py` | Emits structured `sims.ai.*` metadata events (`provider`, `operation`, `status`, `tenant_id`, `model`, `latency_ms`, `retries`, `error_code`, token counts) while scrubbing API keys, bearer tokens, and URL credentials. |
| **Retry Policy** | `backend/app/services/ai/retry.py` | Bounded exponential backoff + jitter obeying `Retry-After` guidance exclusively for transient errors (`429` rate limit, `5xx`, timeouts/network failures). Never blindly retries auth errors (`401`/`403`), malformed inputs (`400`), or exhausted daily quota (`limit: 0`). |
| **Gemini Client Lifecycle** | `backend/app/services/ai/gemini_client.py` | Thread-safe `GeminiClientManager` configuring `google.genai.Client` with `HttpOptions(timeout=ms, retry_options=HttpRetryOptions(attempts=1))` and clean `.close()` shutdown. |
| **Gemini LLM Service** | `backend/app/services/ai/gemini_llm.py` | Text generation (`generate_text`), prompt-injection-isolated RAG synthesis (`generate_grounded_answer`), strict Pydantic JSON structured output (`generate_structured`), safety/empty checks, optional fallback models, and lightweight `probe_connectivity()`. |
| **Gemini Embedding Service** | `backend/app/services/ai/gemini_embeddings.py` | Batched `embed_documents` (`RETRIEVAL_DOCUMENT`), `embed_query` (`RETRIEVAL_QUERY`), model-aware `task_type` handling (`gemini-embedding-001` vs `gemini-embedding-2`), finite/dimension/zero-norm validation, and deterministic L2 normalization. |
| **Qdrant Vector Store** | `backend/app/services/ai/qdrant_service.py` | Lifecycle-safe `QdrantVectorService` enforcing schema alignment (`QdrantCollectionMismatchError`), payload index creation, deterministic UUIDv5 point IDs, mandatory `tenant_id` filters, defense-in-depth post-filtering, and tenant-scoped search/delete/count operations. |
| **Vector Knowledge Pipeline** | `backend/app/services/ai/pipeline.py` | Composable end-to-end integration layer (`index_chunks`, `semantic_search`, `answer_with_retrieved_context`) linking Gemini embeddings, Qdrant tenant search, and grounded Gemini synthesis. |
| **AI Health & Container** | `backend/app/services/ai/health.py`, `container.py` | `AIRuntimeContainer` wired into FastAPI `lifespan` (`app.state.ai_container`) and `AIHealthService` reporting distinct component states (`unconfigured`, `configured`, `operational`, `degraded`, `unavailable`) without secret exposure. |
| **Diagnostics API** | `backend/app/routers/ai.py`, `schemas/ai_schema.py` | RBAC-protected `GET /api/ai/health` (read readiness) and rate-limited admin/manager `POST /api/ai/health/probe` (live provider connectivity verification). |

---

## 3. Model, Deadline & Circuit-Breaker Design

- **Default LLM:** `GEMINI_LLM_MODEL=gemini-3.5-flash-lite` paired with `GEMINI_LLM_FALLBACK_MODELS=gemini-3.1-flash-lite,gemini-3.8-flash` (empirically verified `<1.2s` latency on live API checks after observing upstream `503`/`504` congestion on `gemini-3.8-flash` and `404` deprecation on `gemini-2.5-flash`). All models remain env-overridable.
- **Deadlines & Circuit Breaker:** Calls share an overall request deadline (`GEMINI_OVERALL_DEADLINE_SECONDS=25`) with bounded per-model retries and an in-memory per-worker circuit breaker (`CLOSED -> OPEN -> HALF_OPEN`) plus concurrency semaphore (`GEMINI_MAX_CONCURRENT_REQUESTS=8`). Note: On multi-worker Render deployments, circuit state is per worker process rather than cross-worker global.
- **Default Embedding Model:** `GEMINI_EMBEDDING_MODEL=gemini-embedding-001` with `GEMINI_EMBEDDING_DIMENSIONS=1536` and `GEMINI_EMBEDDING_NORMALIZE=true`.
  - Uses explicit asymmetric retrieval task types (`RETRIEVAL_DOCUMENT` for indexing, `RETRIEVAL_QUERY` for search).
  - Applies L2 normalization whenever vectors are truncated below `3072` dimensions so **Cosine** similarity in Qdrant remains mathematically exact.
  - Also supports switching `GEMINI_EMBEDDING_MODEL=gemini-embedding-2` (automatically adapting task cue prompting since `gemini-embedding-2` deprecates explicit `task_type` config).

---

## 4. Qdrant Multi-Tenant Collection & Payload Contract

- **Versioned Collection Naming:** Defaults to `{QDRANT_COLLECTION_PREFIX}_{APP_ENV}_{QDRANT_COLLECTION_VERSION}_{embedding_model}_{dimensions}d` (e.g., `sims_kb_production_v1_gemini_embedding_001_1536d`), or explicit `QDRANT_COLLECTION_NAME`.
- **Schema Guard:** Existing collections are checked via `get_collection()` for matching vector `size` and `Cosine` distance; incompatible schemas raise `QdrantCollectionMismatchError` instead of dropping/corrupting vectors.
- **Indexed Payload Fields:** `tenant_id` (`INTEGER`), `workspace_id` (`INTEGER`), `document_id` (`KEYWORD`), `source_id` (`KEYWORD`), `source_type` (`KEYWORD`), `document_version` (`KEYWORD`), `embedding_model` (`KEYWORD`), `embedding_version` (`KEYWORD`), `language` (`KEYWORD`).
- **Deterministic Idempotency:** Point IDs are computed via UUIDv5 over `(tenant_id, document_id, document_version, chunk_id)`.
- **Tenant Isolation Guarantees:** Every write, count, search, and delete validates `tenant_id > 0`, overrides/blocks reserved key injection inside metadata, injects `FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))` server-side before querying Qdrant, and post-verifies every returned payload matches the caller's `tenant_id`.

---

## 5. Configuration & Deployment Environment Variables

See `backend/.env.example`:

- **Gemini:** `GEMINI_API_KEY`, `GEMINI_LLM_MODEL`, `GEMINI_LLM_FALLBACK_MODELS`, `GEMINI_EMBEDDING_MODEL`, `GEMINI_EMBEDDING_DIMENSIONS`, `GEMINI_EMBEDDING_NORMALIZE`, `GEMINI_EMBEDDING_VERSION`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_RETRIES`, `GEMINI_RETRY_BASE_SECONDS`, `GEMINI_RETRY_MAX_SECONDS`, `GEMINI_DEFAULT_TEMPERATURE`, `GEMINI_DEFAULT_MAX_OUTPUT_TOKENS`.
- **Qdrant:** `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX`, `QDRANT_COLLECTION_VERSION`, `QDRANT_COLLECTION_NAME`, `QDRANT_TIMEOUT_SECONDS`, `QDRANT_MAX_RETRIES`, `QDRANT_PREFER_GRPC`.
- **Runtime Behavior:** `AI_STRICT_STARTUP=false` keeps Render `/health` and FastAPI startup operational when AI provider keys are omitted or temporarily degraded; setting `AI_STRICT_STARTUP=true` enforces eager client & Qdrant collection readiness checks at startup.

---

## 6. Clean Extension Points for Phases 8–10

- **Phase 8 (RAG & Assistant):** `VectorKnowledgePipeline`, `KnowledgeChunkInput`, `GroundedContextChunk`, `GeminiLLMService.generate_grounded_answer()`, and `GeminiLLMService.generate_structured()` provide direct tenant-isolated primitives for document chunk ingestion, hybrid metadata filters (`source_types`, `language`, `document_version`), and grounded answer synthesis.
- **Phase 9 (Regional UX & Quotas):** `LLMGenerationResult.usage` exposes exact `prompt_tokens`, `candidates_tokens`, `thoughts_tokens`, and `total_tokens` per request for credit metering, while `language` payload indexing supports per-language retrieval filtering.
- **Phase 10 (Hardening):** `/api/ai/health` and `/api/ai/health/probe` expose machine-readable readiness and latency diagnostics ready for production monitoring alerts.
