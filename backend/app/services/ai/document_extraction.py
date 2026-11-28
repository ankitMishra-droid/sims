"""Format-specific document extraction preserving structure, page references, and tabular rows."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import BytesIO, StringIO
import re
from typing import Any, Dict, List, Optional

from charset_normalizer import from_bytes
from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from openpyxl import load_workbook  # type: ignore[import-untyped]
from pypdf import PdfReader

from ...core.ai_exceptions import AIErrorCode, AIInvalidRequestError
from .text_normalization import normalize_text_preserve_scripts

MAX_TABLE_ROWS_PER_DOC = 5000
_HEADING_MD_RE = re.compile(r"^#{1,6}\s+(.+)$")


@dataclass(frozen=True)
class ExtractedSegment:
    text: str
    page_number: Optional[int] = None
    section_heading: Optional[str] = None
    sheet_name: Optional[str] = None
    segment_type: str = "paragraph"  # paragraph | heading | table | row_group | page


@dataclass(frozen=True)
class ExtractionResult:
    segments: List[ExtractedSegment]
    total_pages: Optional[int]
    ocr_required: bool = False
    ocr_status: str = "not_needed"
    metadata: Dict[str, Any] = field(default_factory=dict)


def _decode_text_bytes(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return raw_bytes.decode("utf-8-sig", errors="replace")
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw_bytes.decode("utf-16", errors="replace")
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(raw_bytes).best()
        if best is not None:
            return str(best)
        return raw_bytes.decode("latin-1", errors="replace")


def _extract_pdf(raw_bytes: bytes) -> ExtractionResult:
    try:
        reader = PdfReader(BytesIO(raw_bytes), strict=False)
        if reader.is_encrypted:
            raise AIInvalidRequestError(
                "Encrypted or password-protected PDF documents are not supported.",
                provider="ingestion",
            )
    except AIInvalidRequestError:
        raise
    except Exception as exc:
        raise AIInvalidRequestError(
            f"Unable to parse PDF file: {type(exc).__name__}.",
            provider="ingestion",
        ) from exc

    total_pages = len(reader.pages)
    segments: List[ExtractedSegment] = []
    total_chars = 0
    image_pages = 0

    for page_idx, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception:
            raw_text = ""
        normalized = normalize_text_preserve_scripts(raw_text)
        try:
            if getattr(page, "images", None) and len(page.images) > 0:
                image_pages += 1
        except Exception:
            pass

        if normalized:
            total_chars += len(normalized)
            first_line = normalized.splitlines()[0].strip()
            heading = first_line[:140] if (len(first_line) <= 90 and not first_line.endswith((".", "।"))) else None
            segments.append(
                ExtractedSegment(
                    text=normalized,
                    page_number=page_idx,
                    section_heading=heading,
                    segment_type="page",
                )
            )

    if total_chars < 20 or not segments:
        is_scanned = total_pages > 0 and (image_pages > 0 or total_chars < 20)
        raise AIInvalidRequestError(
            "Scanned or image-based PDF contains no extractable text; OCR is not enabled.",
            provider="ingestion",
            error_code=AIErrorCode.INVALID_REQUEST,
        ) if is_scanned else AIInvalidRequestError(
            "No extractable text found in PDF document.",
            provider="ingestion",
        )

    return ExtractionResult(
        segments=segments,
        total_pages=total_pages,
        ocr_required=False,
        ocr_status="not_needed",
        metadata={"pages_with_text": len(segments), "image_pages": image_pages},
    )


def _extract_docx(raw_bytes: bytes) -> ExtractionResult:
    try:
        doc = DocxDocument(BytesIO(raw_bytes))
    except Exception as exc:
        raise AIInvalidRequestError(
            f"Corrupted or unreadable DOCX document: {type(exc).__name__}.",
            provider="ingestion",
        ) from exc

    segments: List[ExtractedSegment] = []
    current_heading: Optional[str] = None

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = DocxParagraph(child, doc)
            text = normalize_text_preserve_scripts(para.text)
            if not text:
                continue
            style_name = (para.style.name if para.style and para.style.name else "").lower()
            if "heading" in style_name or "title" in style_name:
                current_heading = text[:200]
                segments.append(
                    ExtractedSegment(
                        text=text,
                        section_heading=current_heading,
                        segment_type="heading",
                    )
                )
            else:
                segments.append(
                    ExtractedSegment(
                        text=text,
                        section_heading=current_heading,
                        segment_type="paragraph",
                    )
                )
        elif isinstance(child, CT_Tbl):
            tbl = DocxTable(child, doc)
            rows_text: List[str] = []
            headers: List[str] = []
            for r_idx, row in enumerate(tbl.rows):
                cells = [normalize_text_preserve_scripts(c.text).replace("\n", " ") for c in row.cells]
                if not any(cells):
                    continue
                if r_idx == 0:
                    headers = cells
                    rows_text.append("Headers: " + " | ".join(cells))
                elif headers and len(headers) == len(cells):
                    pairs = [f"{h}: {v}" for h, v in zip(headers, cells) if v]
                    if pairs:
                        rows_text.append("; ".join(pairs))
                else:
                    rows_text.append(" | ".join(c for c in cells if c))
            if rows_text:
                segments.append(
                    ExtractedSegment(
                        text="\n".join(rows_text),
                        section_heading=current_heading,
                        segment_type="table",
                    )
                )

    if not segments:
        raise AIInvalidRequestError("DOCX document contains no extractable text.", provider="ingestion")

    return ExtractionResult(
        segments=segments,
        total_pages=None,
        metadata={"segments": len(segments)},
    )


def _extract_txt(raw_bytes: bytes) -> ExtractionResult:
    decoded = normalize_text_preserve_scripts(_decode_text_bytes(raw_bytes))
    if not decoded:
        raise AIInvalidRequestError("TXT document contains no extractable text.", provider="ingestion")

    segments: List[ExtractedSegment] = []
    current_heading: Optional[str] = None
    for block in decoded.split("\n\n"):
        blk = block.strip()
        if not blk:
            continue
        lines = blk.splitlines()
        md_match = _HEADING_MD_RE.match(lines[0])
        if md_match:
            current_heading = md_match.group(1).strip()[:200]
            body = "\n".join(lines[1:]).strip()
            if body:
                segments.append(
                    ExtractedSegment(text=body, section_heading=current_heading, segment_type="paragraph")
                )
            else:
                segments.append(
                    ExtractedSegment(
                        text=current_heading, section_heading=current_heading, segment_type="heading"
                    )
                )
        else:
            segments.append(
                ExtractedSegment(text=blk, section_heading=current_heading, segment_type="paragraph")
            )

    return ExtractionResult(segments=segments, total_pages=None, metadata={"blocks": len(segments)})


def _format_table_rows(
    *,
    headers: List[str],
    rows: List[tuple[int, List[str]]],
    sheet_name: Optional[str] = None,
    group_size: int = 12,
) -> List[ExtractedSegment]:
    segments: List[ExtractedSegment] = []
    header_line = "Headers: " + " | ".join(h for h in headers if h) if any(headers) else ""
    prefix = f"Sheet: {sheet_name}\n" if sheet_name else ""
    if header_line:
        prefix = f"{prefix}{header_line}\n"

    for start in range(0, len(rows), group_size):
        batch = rows[start : start + group_size]
        lines = []
        for row_num, vals in batch:
            if headers and len(headers) >= len(vals):
                pairs = [f"{headers[i]}={vals[i]}" for i in range(len(vals)) if vals[i]]
                if pairs:
                    lines.append(f"Row {row_num}: " + ", ".join(pairs))
            else:
                joined = " | ".join(v for v in vals if v)
                if joined:
                    lines.append(f"Row {row_num}: {joined}")
        if lines:
            segments.append(
                ExtractedSegment(
                    text=(prefix + "\n".join(lines)).strip(),
                    sheet_name=sheet_name,
                    section_heading=sheet_name,
                    segment_type="row_group",
                )
            )
    return segments


def _extract_csv(raw_bytes: bytes) -> ExtractionResult:
    decoded = _decode_text_bytes(raw_bytes)
    if not decoded.strip():
        raise AIInvalidRequestError("CSV document is empty.", provider="ingestion")

    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(StringIO(decoded), dialect=dialect)
    all_rows = [[normalize_text_preserve_scripts(c) for c in r] for r in reader]
    non_empty = [r for r in all_rows if any(cell for cell in r)]
    if not non_empty:
        raise AIInvalidRequestError("CSV document contains no rows.", provider="ingestion")

    headers = non_empty[0]
    data_rows = [
        (idx, r)
        for idx, r in enumerate(non_empty[1 : MAX_TABLE_ROWS_PER_DOC + 1], start=1)
        if any(cell for cell in r)
    ]
    if not data_rows:
        data_rows = [(1, headers)]
        headers = []

    segments = _format_table_rows(headers=headers, rows=data_rows, sheet_name="csv")
    return ExtractionResult(
        segments=segments,
        total_pages=None,
        metadata={"row_count": len(data_rows), "columns": len(headers)},
    )


def _extract_xlsx(raw_bytes: bytes) -> ExtractionResult:
    try:
        wb = load_workbook(BytesIO(raw_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise AIInvalidRequestError(
            f"Corrupted or unreadable XLSX workbook: {type(exc).__name__}.",
            provider="ingestion",
        ) from exc

    segments: List[ExtractedSegment] = []
    total_rows = 0
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            headers: List[str] = []
            sheet_rows: List[tuple[int, List[str]]] = []
            for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                vals = [
                    normalize_text_preserve_scripts("" if cell is None else str(cell))
                    for cell in row
                ]
                if not any(vals):
                    continue
                if not headers:
                    headers = vals
                    continue
                total_rows += 1
                if total_rows > MAX_TABLE_ROWS_PER_DOC:
                    break
                sheet_rows.append((row_idx, vals))
            if not sheet_rows and headers:
                sheet_rows.append((1, headers))
                headers = []
            if sheet_rows:
                segments.extend(
                    _format_table_rows(
                        headers=headers,
                        rows=sheet_rows,
                        sheet_name=sheet_name,
                    )
                )
            if total_rows > MAX_TABLE_ROWS_PER_DOC:
                break
    finally:
        wb.close()

    if not segments:
        raise AIInvalidRequestError("XLSX workbook contains no extractable rows.", provider="ingestion")

    return ExtractionResult(
        segments=segments,
        total_pages=None,
        metadata={"sheet_count": len(wb.sheetnames), "rows_extracted": total_rows},
    )


def extract_document_content(file_type: str, raw_bytes: bytes) -> ExtractionResult:
    """Dispatch document extraction based on verified file type."""
    ft = file_type.lower().strip()
    if ft == "pdf":
        return _extract_pdf(raw_bytes)
    if ft == "docx":
        return _extract_docx(raw_bytes)
    if ft == "txt":
        return _extract_txt(raw_bytes)
    if ft == "csv":
        return _extract_csv(raw_bytes)
    if ft == "xlsx":
        return _extract_xlsx(raw_bytes)
    raise AIInvalidRequestError(f"Unsupported file type {file_type!r}.", provider="ingestion")
