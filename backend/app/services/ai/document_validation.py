"""Secure document validation, magic-byte/structural checks, and workspace file staging."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
import re
from typing import Optional
import zipfile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ...core.ai_config import AIProviderSettings
from ...core.ai_exceptions import AIInvalidRequestError

SUPPORTED_FILE_TYPES = {"pdf", "docx", "txt", "csv", "xlsx"}
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_UNCOMPRESSED_ZIP_RATIO_BYTES = 60 * 1024 * 1024  # 60 MB decompression cap against zip bombs


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    title: str
    file_type: str
    mime_type: str
    file_size_bytes: int
    content_hash: str
    total_pages: Optional[int]
    raw_bytes: bytes


def sanitize_filename(filename: Optional[str]) -> str:
    raw = (filename or "document").replace("\\", "/").split("/")[-1].strip()
    cleaned = _FILENAME_SAFE_RE.sub("_", raw).strip("._")
    if not cleaned:
        return "document.txt"
    return cleaned[:200]


def _detect_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FILE_TYPES:
        raise AIInvalidRequestError(
            f"Unsupported document format '.{ext or 'unknown'}'. Supported formats: {', '.join(sorted(SUPPORTED_FILE_TYPES))}.",
            provider="ingestion",
        )
    return ext


def _validate_zip_container(raw_bytes: bytes, *, required_member: str, format_label: str) -> None:
    if not raw_bytes.startswith(b"PK"):
        raise AIInvalidRequestError(
            f"Malformed {format_label} file: invalid archive signature.",
            provider="ingestion",
        )
    try:
        with zipfile.ZipFile(BytesIO(raw_bytes)) as zf:
            infos = zf.infolist()
            if not infos:
                raise AIInvalidRequestError(
                    f"Malformed {format_label} file: archive contains no entries.",
                    provider="ingestion",
                )
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > _MAX_UNCOMPRESSED_ZIP_RATIO_BYTES:
                raise AIInvalidRequestError(
                    f"{format_label} exceeds safe uncompressed size limits.",
                    provider="ingestion",
                )
            names = {info.filename for info in infos}
            if required_member not in names:
                raise AIInvalidRequestError(
                    f"Malformed {format_label} file: missing required structure '{required_member}'.",
                    provider="ingestion",
                )
    except zipfile.BadZipFile as exc:
        raise AIInvalidRequestError(
            f"Corrupted {format_label} file: unable to read archive.",
            provider="ingestion",
        ) from exc


def validate_uploaded_document(
    *,
    filename: Optional[str],
    raw_bytes: bytes,
    claimed_mime_type: Optional[str],
    settings: AIProviderSettings,
    title: Optional[str] = None,
) -> ValidatedUpload:
    """Validate file extension, size, magic signature, encryption, and safety constraints."""
    safe_name = sanitize_filename(filename)
    file_type = _detect_extension(safe_name)

    if not raw_bytes:
        raise AIInvalidRequestError("Uploaded document is empty (0 bytes).", provider="ingestion")

    max_bytes = getattr(settings, "ai_max_document_mb", 15) * 1024 * 1024
    if len(raw_bytes) > max_bytes:
        raise AIInvalidRequestError(
            f"Document exceeds maximum allowed size of {getattr(settings, 'ai_max_document_mb', 15)} MB.",
            provider="ingestion",
        )

    total_pages: Optional[int] = None
    max_pages = getattr(settings, "ai_max_pdf_pages", 150)

    if file_type == "pdf":
        header_idx = raw_bytes[:1024].find(b"%PDF-")
        if header_idx < 0:
            raise AIInvalidRequestError(
                "Malformed PDF file: missing %PDF- header signature.",
                provider="ingestion",
            )
        try:
            reader = PdfReader(BytesIO(raw_bytes), strict=False)
            if reader.is_encrypted:
                raise AIInvalidRequestError(
                    "Encrypted or password-protected PDF documents are not supported.",
                    provider="ingestion",
                )
            total_pages = len(reader.pages)
        except AIInvalidRequestError:
            raise
        except (PdfReadError, Exception) as exc:
            raise AIInvalidRequestError(
                f"Corrupted or unreadable PDF document: {type(exc).__name__}.",
                provider="ingestion",
            ) from exc

        if total_pages == 0:
            raise AIInvalidRequestError("PDF document contains 0 pages.", provider="ingestion")
        if total_pages > max_pages:
            raise AIInvalidRequestError(
                f"PDF exceeds maximum supported page count ({max_pages} pages).",
                provider="ingestion",
            )

    elif file_type == "docx":
        _validate_zip_container(
            raw_bytes,
            required_member="word/document.xml",
            format_label="DOCX",
        )

    elif file_type == "xlsx":
        _validate_zip_container(
            raw_bytes,
            required_member="xl/workbook.xml",
            format_label="XLSX",
        )

    elif file_type in ("txt", "csv"):
        is_utf16_bom = raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff"))
        if not is_utf16_bom and b"\x00" in raw_bytes[:4096]:
            raise AIInvalidRequestError(
                f"Malformed {file_type.upper()} file: binary null bytes detected.",
                provider="ingestion",
            )
        if raw_bytes.startswith(b"%PDF-") or raw_bytes.startswith(b"PK\x03\x04"):
            raise AIInvalidRequestError(
                f"File contents do not match .{file_type} text extension.",
                provider="ingestion",
            )

    derived_title = (title or "").strip() or Path(safe_name).stem.replace("_", " ").strip() or safe_name
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    canonical_mime = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "txt": "text/plain",
    }[file_type]

    return ValidatedUpload(
        filename=safe_name,
        title=derived_title[:250],
        file_type=file_type,
        mime_type=(claimed_mime_type or canonical_mime)[:120],
        file_size_bytes=len(raw_bytes),
        content_hash=content_hash,
        total_pages=total_pages,
        raw_bytes=raw_bytes,
    )


def save_staged_document(
    *,
    upload_dir: str,
    business_id: int,
    document_uuid: str,
    filename: str,
    raw_bytes: bytes,
) -> str:
    """Safely write uploaded bytes into a tenant-scoped directory with traversal guard."""
    base_path = Path(upload_dir).resolve()
    tenant_dir = (base_path / f"tenant_{business_id}").resolve()
    tenant_dir.mkdir(parents=True, exist_ok=True)
    target = (tenant_dir / f"{document_uuid}_{sanitize_filename(filename)}").resolve()
    if tenant_dir not in target.parents:
        raise AIInvalidRequestError("Unsafe file storage path resolved.", provider="ingestion")
    target.write_bytes(raw_bytes)
    return str(target)


def remove_staged_file(storage_path: Optional[str]) -> None:
    """Best-effort safe cleanup of staged document bytes."""
    if not storage_path:
        return
    try:
        p = Path(storage_path)
        if p.exists() and p.is_file():
            p.unlink()
    except OSError:
        pass
