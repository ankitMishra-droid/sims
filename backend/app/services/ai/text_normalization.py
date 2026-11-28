"""Unicode-safe text normalization preserving Indic scripts, matras, conjuncts, and identifiers."""

from __future__ import annotations

import re
import unicodedata

# Preserve ZWJ (\u200d) and ZWNJ (\u200c) for Devanagari/Indic conjuncts; remove BOM/ZWSP/soft-hyphen
_JUNK_CHARS_RE = re.compile(r"[\ufeff\u200b\u00ad]")
_DEHYPHENATE_LATIN_RE = re.compile(r"([A-Za-z]{2,})-\n([a-z]{2,})")
_MULTI_SPACE_RE = re.compile(r"[^\S\n]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_text_preserve_scripts(text: str) -> str:
    """Normalize extracted text cleanly without damaging Devanagari or business SKUs."""
    if not text:
        return ""
    # NFC keeps base + matras + conjunct compositions consistent across SQL/Qdrant
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _JUNK_CHARS_RE.sub("", cleaned)
    cleaned = _DEHYPHENATE_LATIN_RE.sub(r"\1\2", cleaned)

    lines = []
    for line in cleaned.split("\n"):
        collapsed = _MULTI_SPACE_RE.sub(" ", line).strip()
        lines.append(collapsed)

    joined = "\n".join(lines)
    joined = _MULTI_NEWLINE_RE.sub("\n\n", joined)
    return joined.strip()
