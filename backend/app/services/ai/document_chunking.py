"""Structure-aware multilingual chunking for documentation, FAQs, tables, and catalogs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import List, Optional, Sequence

from .document_extraction import ExtractedSegment
from .language_detection import detect_language

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[।.!?])\s+")
_FAQ_SPLIT_RE = re.compile(r"(?=(?:^|\n)(?:Q\d*[:.)]|Question[:\s]|प्रश्न[:\s]))", re.IGNORECASE)


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    chunk_uid: str
    text: str
    content_hash: str
    page_number: Optional[int]
    section_heading: Optional[str]
    sheet_name: Optional[str]
    language: str
    char_count: int
    token_estimate: int
    chunk_strategy: str


def _resolve_strategy(file_type: str, doc_category: str) -> str:
    cat = (doc_category or "general").strip().lower()
    if file_type in ("csv", "xlsx") or cat in ("table", "catalog"):
        return "table"
    if cat == "faq":
        return "faq"
    if cat == "manual":
        return "manual"
    return "general"


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _split_long_block(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
) -> List[str]:
    if len(text) <= chunk_size:
        return [text]

    parts: List[str] = []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        # Word-boundary sliding window fallback
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            if end < len(text):
                ws = text.rfind(" ", start + int(chunk_size * 0.5), end)
                if ws > start:
                    end = ws
            piece = text[start:end].strip()
            if piece:
                parts.append(piece)
            if end >= len(text):
                break
            next_start = max(start + 1, end - overlap)
            if next_start < len(text):
                ws_back = text.find(" ", next_start)
                if ws_back != -1 and ws_back < end:
                    next_start = ws_back + 1
            start = next_start
        return parts

    current = ""
    for sent in sentences:
        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                parts.append(current)
            if len(sent) > chunk_size:
                parts.extend(_split_long_block(sent, chunk_size=chunk_size, overlap=overlap))
                current = ""
            else:
                tail = current[-overlap:].strip() if (current and overlap > 0) else ""
                if tail:
                    space_idx = tail.find(" ")
                    if space_idx != -1:
                        tail = tail[space_idx + 1 :]
                current = f"{tail} {sent}".strip() if tail and len(tail) + len(sent) + 1 <= chunk_size else sent
    if current:
        parts.append(current)
    return parts


def chunk_extracted_segments(
    segments: Sequence[ExtractedSegment],
    *,
    file_type: str,
    doc_category: str = "general",
    chunk_size: int = 900,
    chunk_overlap: int = 120,
    min_chunk_chars: int = 30,
    max_chunks: int = 500,
) -> List[ChunkDraft]:
    """Convert extracted document segments into structure-preserving, metadata-rich chunks."""
    strategy = _resolve_strategy(file_type, doc_category)
    raw_entries: List[tuple[str, Optional[int], Optional[str], Optional[str]]] = []

    if strategy == "table":
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            if len(text) <= chunk_size:
                raw_entries.append((text, seg.page_number, seg.section_heading, seg.sheet_name))
            else:
                lines = text.splitlines()
                header_lines = [l for l in lines[:2] if l.startswith(("Sheet:", "Headers:"))]
                prefix = "\n".join(header_lines)
                body_lines = lines[len(header_lines) :]
                cur = prefix
                for row_line in body_lines:
                    candidate = f"{cur}\n{row_line}".strip() if cur else row_line
                    if len(candidate) <= chunk_size:
                        cur = candidate
                    else:
                        if cur and cur != prefix:
                            raw_entries.append((cur, seg.page_number, seg.section_heading, seg.sheet_name))
                        cur = f"{prefix}\n{row_line}".strip() if prefix else row_line
                if cur and cur != prefix:
                    raw_entries.append((cur, seg.page_number, seg.section_heading, seg.sheet_name))

    elif strategy == "faq":
        combined = "\n\n".join(seg.text for seg in segments if seg.text.strip())
        faq_blocks = [b.strip() for b in _FAQ_SPLIT_RE.split(combined) if b.strip()]
        for blk in faq_blocks:
            for piece in _split_long_block(blk, chunk_size=chunk_size, overlap=min(80, chunk_overlap)):
                raw_entries.append((piece, None, "FAQ", None))

    else:
        # General / Manual: keep same-page & same-heading blocks cohesive without spanning pages
        buf_text = ""
        buf_page: Optional[int] = None
        buf_heading: Optional[str] = None
        buf_sheet: Optional[str] = None

        def _flush() -> None:
            nonlocal buf_text
            if not buf_text.strip():
                buf_text = ""
                return
            for piece in _split_long_block(
                buf_text.strip(), chunk_size=chunk_size, overlap=chunk_overlap
            ):
                raw_entries.append((piece, buf_page, buf_heading, buf_sheet))
            buf_text = ""

        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            if seg.segment_type == "heading":
                _flush()
                buf_heading = seg.section_heading or text[:200]
                buf_page = seg.page_number
                continue

            context_changed = (
                (buf_text and seg.page_number != buf_page)
                or (buf_text and seg.section_heading != buf_heading)
            )
            if context_changed or (buf_text and len(buf_text) + len(text) + 2 > chunk_size):
                _flush()

            buf_page = seg.page_number
            buf_heading = seg.section_heading
            buf_sheet = seg.sheet_name
            if seg.segment_type == "table":
                _flush()
                for piece in _split_long_block(text, chunk_size=chunk_size, overlap=chunk_overlap):
                    raw_entries.append((piece, seg.page_number, seg.section_heading, seg.sheet_name))
            else:
                buf_text = f"{buf_text}\n\n{text}".strip() if buf_text else text

        _flush()

    # Merge tiny trailing fragments safely if below min_chunk_chars within same page/heading
    merged: List[tuple[str, Optional[int], Optional[str], Optional[str]]] = []
    for entry in raw_entries:
        txt, pg, hd, sh = entry
        if (
            merged
            and len(txt) < min_chunk_chars
            and merged[-1][1] == pg
            and merged[-1][2] == hd
            and len(merged[-1][0]) + len(txt) + 2 <= int(chunk_size * 1.25)
        ):
            prev = merged[-1]
            merged[-1] = (f"{prev[0]}\n\n{txt}".strip(), pg, hd, sh)
        else:
            merged.append(entry)

    drafts: List[ChunkDraft] = []
    seen_hashes: set[str] = set()
    for idx, (txt, pg, hd, sh) in enumerate(merged[:max_chunks]):
        c_hash = hashlib.sha256(txt.encode("utf-8")).hexdigest()
        # Deduplicate exact identical chunks (e.g., repeated PDF headers/boilerplate)
        dedup_key = f"{c_hash}:{pg}"
        if dedup_key in seen_hashes and len(txt) < 200:
            continue
        seen_hashes.add(dedup_key)

        lang = detect_language(txt).language
        c_idx = len(drafts)
        drafts.append(
            ChunkDraft(
                chunk_index=c_idx,
                chunk_uid=f"c{c_idx}_{c_hash[:12]}",
                text=txt,
                content_hash=c_hash,
                page_number=pg,
                section_heading=hd,
                sheet_name=sh,
                language=lang,
                char_count=len(txt),
                token_estimate=_estimate_tokens(txt),
                chunk_strategy=strategy,
            )
        )

    return drafts
