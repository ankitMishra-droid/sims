"""Phase 8 test suite: document ingestion, multilingual RAG, hybrid retrieval eval, business tools, and security."""

from __future__ import annotations

from decimal import Decimal
import hashlib
from io import BytesIO
import math
import os
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
from openpyxl import Workbook  # type: ignore[import-untyped]
import pytest
from pypdf import PdfWriter
from qdrant_client import QdrantClient
from qdrant_client.http import exceptions as qdrant_exceptions
from sqlalchemy import create_engine, event, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.ai_config import AIProviderSettings
from app.core.ai_exceptions import AIInvalidRequestError
from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db
from app.db_migrate import run_alembic_migrations
from app.main import app
from app.models.products import Product
from app.models.purchase_order import PurchaseOrder
from app.models.sales import Sale
from app.models.supplier import Supplier
from app.services.ai.container import AIRuntimeContainer
from app.services.ai.document_validation import validate_uploaded_document
from app.services.ai.gemini_client import GeminiClientManager
from app.services.ai.ingestion_service import DocumentIngestionService
from app.services.ai.language_detection import detect_language
from app.services.ai.qdrant_service import QdrantVectorService
from app.services.ai.retrieval_eval import RetrievalEvalCase, evaluate_retrieval_suite
from app.services.ai.retrieval_service import TenantHybridRetrievalService
from app.services.ai.text_normalization import normalize_text_preserve_scripts


# ---------------------------------------------------------------------------
# Helpers: Real PDF/DOCX/XLSX/CSV generators & deterministic multilingual vecs
# ---------------------------------------------------------------------------


def _build_extractable_pdf_bytes(pages_text: List[str]) -> bytes:
    """Create a valid, multi-page PDF 1.4 byte stream with standard Helvetica text objects."""
    objects: List[bytes] = []

    # Object 1: Catalog, Object 2: Pages (placeholder), Object 3: Font
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    page_obj_nums = [4 + idx * 2 for idx in range(len(pages_text))]
    kids_str = " ".join(f"{n} 0 R" for n in page_obj_nums).encode("ascii")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [" + kids_str + b"] /Count " + str(len(pages_text)).encode("ascii") + b" >>\nendobj\n")
    objects.append(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    for idx, txt in enumerate(pages_text):
        page_num = 4 + idx * 2
        content_num = page_num + 1
        escaped = txt.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_data = f"BT\n/F1 12 Tf\n72 720 Td\n({escaped}) Tj\nET\n".encode("latin-1", errors="replace")
        page_obj = (
            f"{page_num} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>\n"
            f"endobj\n"
        ).encode("ascii")
        content_obj = (
            f"{content_num} 0 obj\n<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
            + stream_data
            + b"endstream\nendobj\n"
        )
        objects.append(page_obj)
        objects.append(content_obj)

    header = b"%PDF-1.4\n"
    offsets = [0]
    body = bytearray(header)
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)

    xref_pos = len(body)
    xref = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    body.extend(b"".join(xref))
    body.extend(trailer)
    return bytes(body)


def _build_blank_scanned_pdf_bytes() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def _build_encrypted_pdf_bytes() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.encrypt("secret123")
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def _build_docx_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_heading("Warehouse Receiving SOP", level=1)
    doc.add_paragraph("Partial goods receipt updates stock incrementally as batches pass QA.")
    doc.add_heading("Returns SLA", level=2)
    tbl = doc.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "SKU"
    tbl.cell(0, 1).text = "Warranty"
    tbl.cell(1, 0).text = "BASMATI-5KG-PREM"
    tbl.cell(1, 1).text = "14 days sealed return policy"
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "SupplierCatalog"
    ws.append(["SKU", "ProductName", "MOQ", "LeadTimeDays"])
    ws.append(["BASMATI-5KG-PREM", "Royal Basmati Rice 5kg", 20, 4])
    ws.append(["MUSTARD-1L-ORG", "Cold Pressed Mustard Oil 1L", 12, 6])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Bilingual concept map so semantic vector simulation also bridges Hindi <-> English concepts cleanly
_CONCEPT_GROUPS = {
    "reorder": ("reorder", "stock", "इन्वेंट्री", "रीऑर्डर", "स्टॉक", "threshold", "safety"),
    "purchase_order": ("purchase", "order", "po", "परचेज", "ऑर्डर", "खरीद", "supplier", "सप्लायर"),
    "receipt": ("receipt", "goods", "partial", "receiving", "प्राप्ति", "माल"),
    "basmati": ("basmati", "rice", "basmati-5kg-prem", "rice-5kg", "rice_5kg", "चावल"),
    "return": ("return", "warranty", "refund", "वापसी", "policy", "नियम"),
}


def _semantic_multilingual_vector(text: str, dims: int = 128) -> List[float]:
    vec = [0.0] * dims
    lowered = text.lower()
    for concept_idx, (concept, aliases) in enumerate(_CONCEPT_GROUPS.items()):
        if any(a in lowered for a in aliases):
            vec[concept_idx * 4] += 3.0
    for tok in lowered.split():
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = (int.from_bytes(digest[:2], "big") % (dims - 32)) + 32
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _make_runtime_container(tmp_upload_dir: str, *, llm_reply_fn=None) -> tuple[AIRuntimeContainer, QdrantClient, MagicMock]:
    settings = AIProviderSettings(
        app_env="test",
        gemini_api_key="AIzaSyPhase8FakeTestKey1234567890",
        gemini_llm_model="gemini-3.8-flash",
        gemini_llm_fallback_models=(),
        gemini_embedding_model="gemini-embedding-001",
        gemini_embedding_dimensions=128,
        gemini_embedding_normalize=True,
        gemini_max_retries=1,
        gemini_retry_base_seconds=0.01,
        gemini_retry_max_seconds=0.05,
        qdrant_url=":memory:",
        qdrant_max_retries=1,
        ai_upload_dir=tmp_upload_dir,
        ai_chunk_size_chars=450,
        ai_chunk_overlap_chars=60,
        ai_initial_grant_credits=Decimal("1000.0"),
        ai_initial_grant_approved=True,
    )
    mock_genai = MagicMock()

    def _embed(*, model, contents, config):
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=_semantic_multilingual_vector(t, 128)) for t in contents]
        )

    def _generate(*, model, contents, config):
        reply_text = llm_reply_fn(contents, config) if llm_reply_fn else "Grounded response based on [1]."
        return SimpleNamespace(
            text=reply_text,
            parsed=None,
            candidates=[
                SimpleNamespace(
                    finish_reason="STOP",
                    content=SimpleNamespace(parts=[SimpleNamespace(text=reply_text, thought=False)]),
                )
            ],
            usage_metadata=SimpleNamespace(
                prompt_token_count=45,
                candidates_token_count=18,
                thoughts_token_count=0,
                total_token_count=63,
            ),
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


def _make_memory_db():
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


# ---------------------------------------------------------------------------
# 1. File Validation, Unicode Hindi Normalization, Extraction & Scanned PDFs
# ---------------------------------------------------------------------------


def test_file_validation_multilingual_normalization_and_language_detection(tmp_path):
    settings = AIProviderSettings(ai_upload_dir=str(tmp_path), ai_max_document_mb=1)

    # Empty, unsupported, binary-in-txt, encrypted PDF, corrupted DOCX
    with pytest.raises(AIInvalidRequestError):
        validate_uploaded_document(filename="empty.txt", raw_bytes=b"", claimed_mime_type="text/plain", settings=settings)
    with pytest.raises(AIInvalidRequestError):
        validate_uploaded_document(filename="malware.exe", raw_bytes=b"MZ123", claimed_mime_type="application/octet-stream", settings=settings)
    with pytest.raises(AIInvalidRequestError):
        validate_uploaded_document(filename="fake.txt", raw_bytes=b"\x00\x01\x02\x03", claimed_mime_type="text/plain", settings=settings)
    with pytest.raises(AIInvalidRequestError):
        validate_uploaded_document(filename="oversized.txt", raw_bytes=b"a" * (1024 * 1024 + 5), claimed_mime_type="text/plain", settings=settings)
    with pytest.raises(AIInvalidRequestError):
        validate_uploaded_document(filename="locked.pdf", raw_bytes=_build_encrypted_pdf_bytes(), claimed_mime_type="application/pdf", settings=settings)
    with pytest.raises(AIInvalidRequestError):
        validate_uploaded_document(filename="broken.docx", raw_bytes=b"not-a-zip", claimed_mime_type="application/zip", settings=settings)

    # Unicode NFC normalization preserves Hindi Devanagari matras, conjuncts & punctuation
    hindi_text = "\ufeffकिराना स्टोर-\npolicy: परचेज ऑर्डर (PO-2026-01) की माल प्राप्ति प्रक्रिया।\n\n\nअगला भाग"
    normalized = normalize_text_preserve_scripts(hindi_text)
    assert "किराना" in normalized
    assert "परचेज ऑर्डर (PO-2026-01)" in normalized
    assert "प्रक्रिया।" in normalized

    assert detect_language("परचेज ऑर्डर कैसे बनाते हैं? स्टॉक अलर्ट की जानकारी।").language == "hi"
    assert detect_language("How do I create a purchase order?").language == "en"
    assert detect_language("Purchase order kaise create karte hain?").language == "mixed"


def test_all_supported_formats_and_scanned_pdf_rejection(tmp_path):
    container, mem_qdrant, _ = _make_runtime_container(str(tmp_path))
    engine, SessionLocal = _make_memory_db()
    try:
        db = SessionLocal()
        from app.models.users import User
        from app.models.business import Business

        user = User(name="Tester", email="t@sims.in", password_hash="x", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        biz = Business(name="Demo Mart", business_type="retailer", owner_user_id=user.id)
        db.add(biz)
        db.commit()
        db.refresh(biz)

        svc = DocumentIngestionService(container)

        samples = [
            ("guide.pdf", _build_extractable_pdf_bytes(["SIMS Guide Page 1: Creating products and SKU.", "SIMS Guide Page 2: Partial goods receipt updates PO stock."]), "manual"),
            ("sop.docx", _build_docx_bytes(), "policy"),
            ("notes_hi.txt", "गोदाम नीति: चावल (BASMATI-5KG-PREM) का न्यूनतम स्टॉक 20 इकाई रखना अनिवार्य है।".encode("utf-8"), "general"),
            ("orders.csv", b"PO_Number,Supplier,Status\nPO-2026-088,Agro Foods,SENT\nPO-2026-089,Metro Grain,DRAFT", "table"),
            ("catalog.xlsx", _build_xlsx_bytes(), "catalog"),
        ]

        for fname, raw, cat in samples:
            doc, is_dup = svc.upload_document(
                db, business_id=biz.id, user_id=user.id, filename=fname, raw_bytes=raw, mime_type=None, doc_category=cat
            )
            assert is_dup is False
            processed = svc.process_document(db, doc_id=doc.id, business_id=biz.id)
            assert processed.status == "COMPLETED", f"{fname}: {processed.error_message}"
            assert processed.indexed_chunks >= 1
            if fname == "guide.pdf":
                assert processed.total_pages == 2
            if fname == "notes_hi.txt":
                assert processed.detected_language == "hi"

        # Scanned PDF must fail explicitly with ocr_required=True (NOT silently index empty chunks)
        scanned_doc, _ = svc.upload_document(
            db, business_id=biz.id, user_id=user.id, filename="scanned.pdf", raw_bytes=_build_blank_scanned_pdf_bytes(), mime_type="application/pdf"
        )
        scanned_res = svc.process_document(db, doc_id=scanned_doc.id, business_id=biz.id)
        assert scanned_res.status == "FAILED"
        assert scanned_res.ocr_required is True
        assert scanned_res.ocr_status == "unsupported_scanned_pdf"
        db.close()
    finally:
        mem_qdrant.close()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Checkpointed Ingestion Recovery, Quota Pause, Duplicate & Controlled Delete
# ---------------------------------------------------------------------------


def test_resumable_ingestion_after_quota_pause_duplicate_and_controlled_delete(tmp_path):
    container, mem_qdrant, mock_genai = _make_runtime_container(str(tmp_path))
    engine, SessionLocal = _make_memory_db()
    try:
        db = SessionLocal()
        from app.models.users import User
        from app.models.business import Business

        user = User(name="IngestOwner", email="own@sims.in", password_hash="x", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        biz = Business(name="Kirana Store", business_type="retailer", owner_user_id=user.id)
        db.add(biz)
        db.commit()
        db.refresh(biz)

        # Create multi-chunk document (2 batches of size 1)
        svc = DocumentIngestionService(container, batch_size=1)
        multi_para = "\n\n".join(
            [
                "Section 1: Supplier lead times must be verified every quarter for staple grains and oils. " * 6,
                "Section 2: Partial goods receipt increases inventory only for physically accepted units. " * 6,
            ]
        ).encode("utf-8")

        doc, is_dup = svc.upload_document(
            db, business_id=biz.id, user_id=user.id, filename="ops_manual.txt", raw_bytes=multi_para, mime_type="text/plain"
        )
        assert is_dup is False

        # Duplicate upload blocked & detected cleanly
        dup_doc, is_dup_second = svc.upload_document(
            db, business_id=biz.id, user_id=user.id, filename="ops_manual_copy.txt", raw_bytes=multi_para, mime_type="text/plain"
        )
        assert is_dup_second is True
        assert dup_doc.id == doc.id

        # Simulate batch 1 embedding OK, batch 2 hitting Gemini daily quota exhaustion (429 limit: 0)
        quota_exc = genai_errors.APIError(
            429,
            {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric PerDay limit: 0"}},
        )
        mock_genai.models.embed_content.side_effect = [
            SimpleNamespace(embeddings=[SimpleNamespace(values=_semantic_multilingual_vector("batch1", 128))]),
            quota_exc,
        ]
        paused = svc.process_document(db, doc_id=doc.id, business_id=biz.id)
        assert paused.status == "QUOTA_PAUSED"
        assert paused.retryable is True
        assert paused.indexed_chunks == 1
        assert paused.total_chunks >= 2

        # Restore healthy Gemini embedder -> retry ONLY embeds remaining unindexed chunk(s)!
        embed_call_count_before = mock_genai.models.embed_content.call_count
        mock_genai.models.embed_content.side_effect = lambda *, model, contents, config: SimpleNamespace(
            embeddings=[SimpleNamespace(values=_semantic_multilingual_vector(t, 128)) for t in contents]
        )
        resumed = svc.retry_document(db, doc_id=doc.id, business_id=biz.id)
        assert resumed.status == "COMPLETED"
        assert resumed.indexed_chunks == resumed.total_chunks
        # Exactly remaining (total_chunks - 1) single-item batch calls were made!
        assert mock_genai.models.embed_content.call_count - embed_call_count_before == resumed.total_chunks - 1

        # Controlled deletion fails safely if Qdrant delete errors (stale vectors never orphaned silently)
        original_delete = container.qdrant_service.delete_document
        container.qdrant_service.delete_document = MagicMock(
            side_effect=lambda *a, **k: (_ for _ in ()).throw(
                qdrant_exceptions.UnexpectedResponse(503, "Busy", b"err", {})  # type: ignore[arg-type]
            )
        )
        with pytest.raises(Exception):
            svc.delete_document(db, doc_id=doc.id, business_id=biz.id)

        container.qdrant_service.delete_document = original_delete
        del_res = svc.delete_document(db, doc_id=doc.id, business_id=biz.id)
        assert del_res["status"] == "DELETED"
        assert container.qdrant_service.count_tenant_vectors(biz.id) == 0
        db.close()
    finally:
        mem_qdrant.close()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Multilingual Hybrid Retrieval Evaluation Suite (EN, HI, Mixed, Exact SKU)
# ---------------------------------------------------------------------------


def test_multilingual_hybrid_retrieval_and_evaluation_metrics(tmp_path):
    container, mem_qdrant, _ = _make_runtime_container(str(tmp_path))
    engine, SessionLocal = _make_memory_db()
    try:
        db = SessionLocal()
        from app.models.users import User
        from app.models.business import Business

        user = User(name="EvalUser", email="eval@sims.in", password_hash="x", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        biz = Business(name="Eval Mart", business_type="retailer", owner_user_id=user.id)
        db.add(biz)
        db.commit()
        db.refresh(biz)

        svc = DocumentIngestionService(container)
        docs_spec = [
            ("pdf_sop.pdf", _build_extractable_pdf_bytes(["Partial goods receipt receives partial ordered quantities and updates PO status."]), "manual"),
            ("hindi_policy.txt", "रिऑर्डर नियम: सुरक्षा स्टॉक और मांग पूर्वानुमान के आधार पर नया ऑर्डर तैयार किया जाता है।".encode("utf-8"), "policy"),
            ("catalog.xlsx", _build_xlsx_bytes(), "catalog"),
            ("po_tracker.csv", b"PO_Number,Supplier,Note\nPO-2026-088,Agro Foods,Awaiting supplier acknowledgement", "table"),
            ("returns.docx", _build_docx_bytes(), "policy"),
        ]
        created_ids = {}
        for fname, raw, cat in docs_spec:
            d, _ = svc.upload_document(
                db, business_id=biz.id, user_id=user.id, filename=fname, raw_bytes=raw, mime_type=None, doc_category=cat
            )
            svc.process_document(db, doc_id=d.id, business_id=biz.id)
            created_ids[fname] = d.id

        retrieval = TenantHybridRetrievalService(container)
        eval_cases = [
            RetrievalEvalCase("c_en", "How does partial goods receipt update PO?", "en_doc", [created_ids["pdf_sop.pdf"], created_ids["returns.docx"]]),
            RetrievalEvalCase("c_hi", "रिऑर्डर और सुरक्षा स्टॉक नियम क्या हैं?", "hi_doc", [created_ids["hindi_policy.txt"]]),
            RetrievalEvalCase("c_cross", "Reorder safety stock policy", "cross_lingual", [created_ids["hindi_policy.txt"]]),
            RetrievalEvalCase("c_mixed", "Partial goods receipt kaise kaam karta hai?", "mixed_doc", [created_ids["pdf_sop.pdf"], created_ids["returns.docx"]]),
            RetrievalEvalCase("c_sku", "MOQ and lead time for BASMATI-5KG-PREM", "exact_id", [created_ids["catalog.xlsx"], created_ids["returns.docx"]]),
            RetrievalEvalCase("c_po", "Status note for PO-2026-088", "exact_id", [created_ids["po_tracker.csv"]]),
            RetrievalEvalCase("c_oov", "Mars colony spacecraft nuclear propulsion rules", "insufficient_evidence", []),
        ]
        report = evaluate_retrieval_suite(
            db, retrieval_service=retrieval, business_id=biz.id, cases=eval_cases, k=3, min_score=0.25
        )
        assert report.total_cases == 7
        assert report.mean_recall_at_k >= 0.85
        assert report.mrr >= 0.80
        assert report.cases[-1].retrieved_doc_ids == []  # Insufficient evidence not forced!
        db.close()
    finally:
        mem_qdrant.close()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. E2E API: Multilingual Assistant, Live Tools, Confirm-Gated PO & Security
# ---------------------------------------------------------------------------


def test_e2e_rag_assistant_tenant_isolation_tools_confirm_and_supplier_portal(tmp_path):
    _engine, SessionLocal = _make_memory_db()
    captured_prompts: List[str] = []

    def _smart_llm(contents: str, config: Any) -> str:
        captured_prompts.append(contents)
        sys_inst = str(getattr(config, "system_instruction", "") or "")
        if "Respond naturally in Hindi" in sys_inst or "किराना" in contents or "मेरे कौनसे" in contents:
            return "आपके लाइव इन्वेंट्री डेटा [1] के अनुसार BASMATI-5KG का स्टॉक कम है (5 इकाइयां)।"
        if "CREATE_DRAFT_PO" in contents:
            return "I prepared a draft PO awaiting your confirmation based on [1]."
        return "Based on live workspace records and documents [1], BASMATI-5KG has 5 units on hand."

    container, mem_qdrant, mock_genai = _make_runtime_container(str(tmp_path), llm_reply_fn=_smart_llm)
    app.state.ai_container_override = container

    try:
        with TestClient(app) as client:
            # Workspace A (Retailer Admin + Staff)
            assert client.post(
                "/api/auth/register",
                json={
                    "name": "Store A Admin",
                    "email": "admina@sims.in",
                    "password": "Password123!",
                    "business_name": "Retailer A",
                    "business_type": "retailer",
                    "create_workspace": True,
                },
            ).status_code == 201
            tok_a = client.post("/api/auth/login", json={"email": "admina@sims.in", "password": "Password123!"}).json()["access_token"]
            hdr_a = {"Authorization": f"Bearer {tok_a}"}

            # Invite Staff in Workspace A
            assert client.post(
                "/api/auth/register",
                json={"name": "Staff A", "email": "staffa@sims.in", "password": "Password123!", "create_workspace": False},
            ).status_code == 201
            tok_staff = client.post("/api/auth/login", json={"email": "staffa@sims.in", "password": "Password123!"}).json()["access_token"]
            inv = client.post("/api/members/invite", headers=hdr_a, json={"email": "staffa@sims.in", "role": "staff"}).json()
            assert client.post("/api/members/accept-invitation", headers={"Authorization": f"Bearer {tok_staff}"}, json={"token": inv["token"]}).status_code == 200
            hdr_staff = {"Authorization": f"Bearer {tok_staff}", "X-Business-Id": str(inv["business_id"])}

            # Competitor Workspace B (Retailer B) & Supplier Workspace S
            assert client.post(
                "/api/auth/register",
                json={
                    "name": "Comp B",
                    "email": "compb@sims.in",
                    "password": "Password123!",
                    "business_name": "Retailer B",
                    "business_type": "retailer",
                    "create_workspace": True,
                },
            ).status_code == 201
            tok_b = client.post("/api/auth/login", json={"email": "compb@sims.in", "password": "Password123!"}).json()["access_token"]
            hdr_b = {"Authorization": f"Bearer {tok_b}"}

            assert client.post(
                "/api/auth/register",
                json={
                    "name": "Supplier S",
                    "email": "sups@sims.in",
                    "password": "Password123!",
                    "business_name": "Agro Supplier",
                    "business_type": "supplier",
                    "create_workspace": True,
                },
            ).status_code == 201
            tok_s = client.post("/api/auth/login", json={"email": "sups@sims.in", "password": "Password123!"}).json()["access_token"]
            hdr_s = {"Authorization": f"Bearer {tok_s}"}

            # Seed Workspace A Supplier, Product & Sale directly in test DB cleanly
            db = SessionLocal()
            biz_a_id = inv["business_id"]
            sup_a = Supplier(business_id=biz_a_id, name="Agro Foods", lead_time_days=4, is_active=True)
            db.add(sup_a)
            db.commit()
            db.refresh(sup_a)
            prod_a = Product(
                business_id=biz_a_id,
                sku="BASMATI-5KG",
                name="Basmati Rice 5kg",
                cost_price=240.0,
                selling_price=300.0,
                current_stock=5,
                reorder_level=15,
                min_order_quantity=10,
                supplier_id=sup_a.id,
            )
            db.add(prod_a)
            db.commit()
            db.refresh(prod_a)
            db.add(Sale(business_id=biz_a_id, product_id=prod_a.id, quantity_sold=4, selling_price=300.0, revenue=1200.0, status="COMPLETED"))
            db.commit()
            prod_a_id = prod_a.id
            db.close()

            # Upload Document into Workspace A (async_process=true runs via TestClient BackgroundTasks!)
            up_res = client.post(
                "/api/ai/documents",
                headers=hdr_a,
                files={"file": ("store_policy.txt", b"Secret Policy A: Minimum safety buffer for BASMATI-5KG is 15 units.", "text/plain")},
                data={"title": "Store A Policy", "doc_category": "policy", "async_process": "true"},
            )
            assert up_res.status_code == 202, up_res.text
            doc_a_id = up_res.json()["document"]["id"]
            st_res = client.get(f"/api/ai/documents/{doc_a_id}/status", headers=hdr_a)
            assert st_res.status_code == 200
            assert st_res.json()["status"] == "COMPLETED"
            assert st_res.json()["progress_percent"] == 100.0

            # Staff can read docs, CANNOT upload or delete docs
            assert client.get("/api/ai/documents", headers=hdr_staff).status_code == 200
            assert (
                client.post(
                    "/api/ai/documents",
                    headers=hdr_staff,
                    files={"file": ("x.txt", b"hello world", "text/plain")},
                ).status_code
                == 403
            )
            assert client.delete(f"/api/ai/documents/{doc_a_id}", headers=hdr_staff).status_code == 403

            # Cross-tenant isolation: Retailer B cannot view, retrieve, or delete Retailer A's doc!
            assert client.get("/api/ai/documents", headers=hdr_b).json() == []
            assert client.get(f"/api/ai/documents/{doc_a_id}", headers=hdr_b).status_code == 404
            assert client.post("/api/ai/retrieve", headers=hdr_b, json={"query": "BASMATI-5KG safety buffer"}).json()["evidence"] == []

            # Chat in English + Live Business Tools + Citation verification
            chat_en = client.post(
                "/api/ai/chat",
                headers=hdr_a,
                json={"message": "Which products are running low?", "page_context": {"route": "/inventory"}},
            )
            assert chat_en.status_code == 200, chat_en.text
            c_data = chat_en.json()
            conv_id = c_data["conversation"]["id"]
            assert any(t["tool"] == "get_low_stock_products" for t in c_data["tools_used"])
            assert any("BASMATI-5KG" in p for p in captured_prompts)

            # Follow-up in Hindi -> responds in Hindi, retains conversation ownership
            chat_hi = client.post(
                "/api/ai/chat",
                headers=hdr_a,
                json={"conversation_id": conv_id, "message": "मेरे कौनसे प्रोडक्ट्स का स्टॉक कम है?", "preferred_language": "hi"},
            )
            assert chat_hi.status_code == 200, chat_hi.text
            assert chat_hi.json()["response_language"] == "hi"

            # User-level conversation isolation: Staff in SAME business cannot access Admin's conversation!
            assert client.get(f"/api/ai/conversations/{conv_id}", headers=hdr_staff).status_code == 404

            # Confirmation-gated write action: chat proposes PO WITHOUT modifying DB until confirmed
            po_count_before = SessionLocal().query(PurchaseOrder).filter(PurchaseOrder.business_id == biz_a_id).count()
            chat_po = client.post(
                "/api/ai/chat",
                headers=hdr_a,
                json={"conversation_id": conv_id, "message": "Create draft PO for BASMATI-5KG 25 units"},
            )
            assert chat_po.status_code == 200, chat_po.text
            pending = chat_po.json()["pending_action"]
            assert pending["status"] == "PENDING_CONFIRMATION"
            assert pending["payload"]["ordered_quantity"] == 25
            msg_id = chat_po.json()["message"]["id"]
            assert SessionLocal().query(PurchaseOrder).filter(PurchaseOrder.business_id == biz_a_id).count() == po_count_before

            # Confirm executes PurchaseOrder via ProcurementService without touching stock
            conf = client.post(
                f"/api/ai/conversations/{conv_id}/actions/confirm",
                headers=hdr_a,
                json={"message_id": msg_id, "confirm": True},
            )
            assert conf.status_code == 200, conf.text
            assert conf.json()["status"] == "EXECUTED"
            assert SessionLocal().query(PurchaseOrder).filter(PurchaseOrder.business_id == biz_a_id).count() == po_count_before + 1
            prod_after = SessionLocal().query(Product).filter(Product.id == prod_a_id).first()
            assert prod_after is not None and prod_after.current_stock == 5

            # Staff cannot trigger draft PO proposal tool (permission denied safely in tool context)
            staff_po_chat = client.post(
                "/api/ai/chat",
                headers=hdr_staff,
                json={"message": "Create draft PO for BASMATI-5KG 15 units"},
            )
            assert staff_po_chat.status_code == 200
            assert staff_po_chat.json()["pending_action"] is None

            # Supplier workspace NEVER accesses buyer inventory/sales tools
            sup_chat = client.post(
                "/api/ai/chat",
                headers=hdr_s,
                json={"message": "Show me low stock inventory and shared purchase orders"},
            )
            assert sup_chat.status_code == 200
            assert all(t["tool"] == "get_supplier_portal_orders" for t in sup_chat.json()["tools_used"])

            # Provider failure during chat returns clean 503 + allows retry without duplicating user turn
            mock_genai.models.generate_content.side_effect = genai_errors.APIError(
                503, {"error": {"message": "Upstream overloaded"}}
            )
            fail_chat = client.post(
                "/api/ai/chat",
                headers=hdr_a,
                json={"conversation_id": conv_id, "message": "Summarize my sales"},
            )
            assert fail_chat.status_code == 503
            mock_genai.models.generate_content.side_effect = lambda *, model, contents, config: SimpleNamespace(
                text=_smart_llm(contents, config),
                parsed=None,
                candidates=[SimpleNamespace(finish_reason="STOP", content=SimpleNamespace(parts=[SimpleNamespace(text=_smart_llm(contents, config), thought=False)]))],
                usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0, total_token_count=15),
            )
            retry_chat = client.post(
                "/api/ai/chat",
                headers=hdr_a,
                json={"conversation_id": conv_id, "message": "Summarize my sales"},
            )
            assert retry_chat.status_code == 200
            conv_msgs = client.get(f"/api/ai/conversations/{conv_id}", headers=hdr_a).json()["messages"]
            sales_user_msgs = [m for m in conv_msgs if m["role"] == "user" and m["content"] == "Summarize my sales"]
            assert len(sales_user_msgs) == 1
    finally:
        app.state.ai_container_override = None
        app.state.ai_container = None
        mem_qdrant.close()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Alembic Migration Safety (SQLite & Optional Live PostgreSQL)
# ---------------------------------------------------------------------------


def test_alembic_phase8_tables_sqlite_upgrade_and_downgrade(tmp_path):
    from alembic import command
    from app.db_migrate import _alembic_config

    db_file = tmp_path / "phase8_alembic.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(db_url)
    try:
        run_alembic_migrations(engine)
        tables = set(sa_inspect(engine).get_table_names())
        expected_tables = (
            "ai_documents",
            "ai_document_chunks",
            "ai_conversations",
            "ai_messages",
            "ai_usage_logs",
        )
        for expected in expected_tables:
            assert expected in tables

        cfg = _alembic_config(db_url)
        command.downgrade(cfg, "0002_phase6_intelligence")
        tables_after_down = set(sa_inspect(engine).get_table_names())
        for expected in expected_tables:
            assert expected not in tables_after_down

        run_alembic_migrations(engine)
        tables_after_reup = set(sa_inspect(engine).get_table_names())
        for expected in expected_tables:
            assert expected in tables_after_reup
    finally:
        engine.dispose()


_PG_URL = os.getenv("TEST_POSTGRES_URL")


@pytest.mark.skipif(not _PG_URL, reason="TEST_POSTGRES_URL not set for live PostgreSQL check")
def test_alembic_phase8_tables_postgresql():
    assert _PG_URL is not None
    engine = create_engine(_PG_URL)
    try:
        run_alembic_migrations(engine)
        tables = set(sa_inspect(engine).get_table_names())
        for expected in (
            "ai_documents",
            "ai_document_chunks",
            "ai_conversations",
            "ai_messages",
            "ai_usage_logs",
        ):
            assert expected in tables
    finally:
        engine.dispose()
