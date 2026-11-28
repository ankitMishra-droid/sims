# SIMS Phase 8 — RAG Ingestion Pipeline & Multilingual AI Assistant Architecture

## 1. Overview

Phase 8 delivers a production-grade Retrieval-Augmented Generation (RAG) document ingestion pipeline and a context-aware, multilingual (English, Hindi, Hinglish) conversational AI assistant integrated across the SIMS backend and React 19 UI, built strictly on top of Phase 7's Gemini (`google-genai`) and Qdrant (`qdrant-client`) infrastructure.

---

## 2. Phase 7 Audit Summary & Reused Components

- Reuses Phase 7 singletons from `AIRuntimeContainer` (`backend/app/services/ai/container.py`):
  - `GeminiClientManager` & `GeminiLLMService` (`gemini-3.8-flash`)
  - `GeminiEmbeddingService` (`gemini-embedding-001`, `1536` dimensions, MRL L2 normalization)
  - `QdrantVectorService` (`Cosine` distance verification, payload indexes, deterministic UUIDv5 point IDs, mandatory `tenant_id` filters, non-destructive collection mismatch guard)
  - Normalized error classifiers & `Retry-After` bounded backoff (`ai_exceptions.py`, `retry.py`)
  - Redacted structured telemetry (`ai_logging.py`)
- Zero duplicate Gemini or Qdrant clients were created.

---

## 3. Supported Document Formats, Validation & Extraction

| Format | Parser Library | Capabilities & Safety Guards |
| :--- | :--- | :--- |
| **PDF** (`.pdf`) | `pypdf==7.2.0` | Verifies `%PDF-` signature, rejects encrypted/password-protected files, enforces max page count (`AI_MAX_PDF_PAGES=150`), extracts page-by-page text preserving page citations (`page_number`). Explicitly detects image/scanned PDFs (`ocr_required=True`, `ocr_status="unsupported_scanned_pdf"`) rather than silently claiming success. |
| **DOCX** (`.docx`) | `python-docx==1.2.0` | Verifies ZIP container & `word/document.xml` signature + decompression cap (`60 MB` against ZIP bombs), preserves headings (`section_heading`), paragraphs, and structured tables in reading order. |
| **TXT** (`.txt`) | Stdlib + `charset-normalizer` | Verifies non-binary content, decodes UTF-8-SIG / UTF-8 / UTF-16 / detected encodings, preserves Markdown headings and paragraph blocks. |
| **CSV** (`.csv`) | Stdlib `csv` + `charset-normalizer` | Sniffs delimiter (` , ; \t | `), keeps header row attached to every chunk group (`Row N: col=val`) with `MAX_TABLE_ROWS_PER_DOC=5000`. |
| **XLSX** (`.xlsx`) | `openpyxl==3.1.5` (`read_only=True`) | Verifies ZIP & `xl/workbook.xml` + ZIP bomb guard, preserves sheet names (`sheet_name`), column headers, and row relationships cleanly. |

**OCR Support Status:** OCR is **not** enabled in Phase 8 to avoid external native dependencies. Scanned or image-only PDFs are reliably flagged with `ocr_required=True` and clear user guidance.

---

## 4. Multilingual Processing & Chunking

- **Unicode Normalization:** [text_normalization.py](file:///d:/sims/backend/app/services/ai/text_normalization.py) applies `unicodedata.normalize("NFC", ...)` while preserving Devanagari matras, conjunct ligatures (including ZWNJ/ZWJ), nuktas, Hindi danda punctuation (`।`), and exact SKU/PO codes.
- **Language Detection:** [language_detection.py](file:///d:/sims/backend/app/services/ai/language_detection.py) distinguishes English (`en`), Hindi Devanagari (`hi`), mixed bilingual / Hinglish (`mixed`), and future Indic scripts cleanly at both document and chunk levels.
- **Structure-Aware Chunking:** [document_chunking.py](file:///d:/sims/backend/app/services/ai/document_chunking.py) selects strategy (`general`, `faq`, `table`, `catalog`, `manual`), respects page/heading boundaries, keeps table headers attached to split row groups, and deduplicates exact boilerplate. Configurable defaults: `AI_CHUNK_SIZE_CHARS=900`, `AI_CHUNK_OVERLAP_CHARS=120`.

---

## 5. Resumable Ingestion & Failure Recovery

Persisted in PostgreSQL/SQLite via Alembic migration [0003_phase8_rag_assistant.py](file:///d:/sims/backend/migrations/versions/0003_phase8_rag_assistant.py):
- `ai_documents`: Ownership (`business_id`, `uploaded_by_user_id`), content SHA-256 hash duplicate detection, versioning (`version_label`), stage/progress counters (`total_chunks`, `embedded_chunks`, `indexed_chunks`, `last_checkpoint_stage`), `ocr_required`, `error_code`, `retryable`.
- `ai_document_chunks`: Persists normalized chunks + `embedding_status` (`PENDING` -> `INDEXED`) and deterministic `qdrant_point_id`.
- **Quota & Failure Resumption:** On `QUOTA_EXHAUSTED` or transient error mid-batch, completed chunk checkpoints remain committed (`QUOTA_PAUSED` / `PARTIALLY_COMPLETED`); calling `POST /api/ai/documents/{id}/retry` skips already-indexed chunks cleanly without duplicate embeddings or duplicate Qdrant vectors.
- **Controlled Two-Phase Deletion:** Marks `DELETING`, removes matching tenant+document vectors from Qdrant first, and only marks `DELETED` after Qdrant confirms removal.

---

## 6. Hybrid Retrieval, Grounded Generation & Live Business Tools

- **Hybrid Retrieval ([retrieval_service.py](file:///d:/sims/backend/app/services/ai/retrieval_service.py)):** Combines Qdrant semantic cosine similarity (`gemini-embedding-001`) with tenant-scoped exact identifier (`SKU`, `PO-xxx`) + lexical term scoring merged via Reciprocal Rank Fusion (RRF), duplicate suppression, and per-document diversity caps. Double security boundary cross-checks every Qdrant hit against active authorized SQL `ai_documents` (`deleted_at IS NULL`).
- **Retrieval Evaluation ([retrieval_eval.py](file:///d:/sims/backend/app/services/ai/retrieval_eval.py)):** Computes `Recall@K`, `Precision@K`, `MRR`, `NDCG@K`, and `latency_ms` across English, Hindi, cross-lingual EN↔HI, Hinglish, exact SKU/PO identifiers, and insufficient-evidence queries.
- **Authorized Business Tools ([business_tools.py](file:///d:/sims/backend/app/services/ai/business_tools.py)):**
  - Read tools strictly gated by `BusinessContext` + RBAC `role_has_permission` + `business_type`:
    - `get_inventory_status` / `get_low_stock_products` (`inventory.read`)
    - `get_purchase_order_status` / `get_supplier_details` (`po.read` / `suppliers.read`)
    - `get_sales_summary` (`sales.read`)
    - `get_forecast_summary` (`intelligence.read` — reuses Phase 6 `InventoryDecisionService` / `ProductForecast` / `ReplenishmentRecommendation`)
    - `get_supplier_portal_orders` (`supplier_portal.read` — isolated to linked POs for `supplier` workspaces)
  - **Confirmation-Gated Write Actions:** Draft PO proposals return `PENDING_CONFIRMATION` payloads without mutating inventory/orders until explicit `POST /api/ai/conversations/{id}/actions/confirm` re-validates `po.write` and invokes `ProcurementService.create_purchase_order`.
- **Conversation & Usage Telemetry (`ai_conversations`, `ai_messages`, `ai_usage_logs`):** User+workspace private conversations with bounded rolling summaries and token/model telemetry prepared cleanly for Phase 9 credit metering (no credits charged in Phase 8).

## 7. Retail Business Advisor Extensions

The assistant classifies retail education separately from tenant-specific analysis. Definition questions (for example, "What is forecasting?" or "Explain ARIMA") use Gemini's general knowledge and skip live business tools and document retrieval unless the user asks about workspace records or uploaded documents. The current question takes precedence over conversation history.

Tenant-authorized business tools provide sales summaries, product sales rankings, estimated gross-profit analysis, adjacent-period comparisons, business-health summaries, persisted demand/revenue projections, and supplier delivery/pricing comparisons. Tool queries remain scoped by `BusinessContext` and existing permission checks.

Financial results are bounded by available records: estimated gross profit uses current product cost prices because sale-time costs are not stored; net profit is not reported because operating expenses are absent; inventory turnover is unavailable without historical inventory valuation; customer behavior is unavailable because customer-level records are not stored. Revenue projections use persisted demand forecasts multiplied by current selling prices and disclose that assumption and forecast-data limitations. No forecast is created when a matching saved forecast is absent.

---

## 8. Frontend Integration (React 19 + Redux Toolkit + i18n)

- **Global Floating AI Assistant:** [FloatingAiAssistant.jsx](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/components/ai/FloatingAiAssistant.jsx) mounted inside [AppLayout.jsx](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/components/layout/AppLayout.jsx) (open/close, minimize, expand, history, new chat, clear confirmation, page route context, EN/HI/Hinglish reply selector, clickable citations, live/forecast badges, write confirmation cards, error retry).
- **Knowledge Base Manager:** [KnowledgeBasePage.jsx](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/pages/KnowledgeBasePage.jsx) (`/ai-knowledge` route, upload, live polling progress bars, scanned PDF warnings, Retry/Reindex/Cancel/Delete, chunk inspector modal, filters).
- **Tenant-Safe Store Reset & Localization:** [aiSlice.js](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/store/aiSlice.js) wiped automatically in [store/index.js](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/store/index.js) on workspace switch and logout; complete EN/HI translations in [translations.js](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/i18n/translations.js).
