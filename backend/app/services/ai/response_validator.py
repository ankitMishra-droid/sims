"""Layer 5: Response validation, leakage sanitization, and quality verification."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .user_facing_labels import INTERNAL_ENUM_REPLACEMENTS

_NUMERIC_CITATION_RE = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")

_LEAKED_INTERNAL_PHRASE_PATTERNS = (
    (re.compile(r"\bPhase\s*[0-9]+(?:\s*Demand\s*Forecast(?:\s*&\s*Replenishment)?(?:\s*Intelligence)?)?\b", re.IGNORECASE), ""),
    (re.compile(r"\bDemand\s+Forecast\s*&\s*Replenishment\s+Intelligence\b", re.IGNORECASE), "inventory forecast"),
    (re.compile(r"\b(?:get_low_stock_products|get_inventory_status|get_forecast_summary|get_sales_summary|get_purchase_order_status|get_supplier_details|get_stock_movements|get_inventory_valuation|prepare_draft_purchase_order)\b"), "inventory data"),
    (re.compile(r"</?retrieved_(?:evidence|context)[^>]*>", re.IGNORECASE), ""),
)

_PHASE_NAME_DETECT_RE = re.compile(r"\bPhase\s*[0-9]+\b", re.IGNORECASE)
_RAW_ENUM_DETECT_RE = re.compile(
    r"\b(?:REORDER_NOW|LOW_STOCK_RISK|OVERSTOCK_ALERT|COLD_START_REVIEW|INSUFFICIENT_DATA|DEMAND_INCREASING|DEMAND_DECREASING|SUPPLIER_LEAD_TIME_RISK|PARTIALLY_RECEIVED)\b"
)
_TECH_JARGON_DETECT_RE = re.compile(
    r"\b(?:RAG\s+retrieval|live\s+SQL|SQL\s+query|retrieved_evidence|tool_calls|product_forecasts|replenishment_recommendations)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResponseValidationResult:
    cleaned_text: str
    warnings: List[str] = field(default_factory=list)
    sanitized_citations: bool = False
    sanitized_enums: bool = False
    sanitized_internal_terms: bool = False
    passed_quality_checks: bool = True


def _cleanup_spacing(text: str) -> str:
    # Fix spaces left before punctuation after removing [1] citations
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", text)
    # Remove horizontal decorative markdown rules that clutter chat bubbles
    cleaned = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", cleaned)
    # Collapse excessive bolding of triple asterisks ***x*** -> **x**
    cleaned = re.sub(r"\*{3,}([^*\n]+)\*{3,}", r"**\1**", cleaned)
    # Collapse 3+ consecutive newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def validate_and_sanitize_response(
    raw_text: str,
    *,
    allow_document_citations: bool = False,
    valid_doc_citation_indices: Optional[Sequence[int]] = None,
    reconciled_summary: Optional[Dict[str, Any]] = None,
    expected_skus: Sequence[str] = (),
) -> ResponseValidationResult:
    """Validate grounded numbers/entities and remove leaked enums, phase names, or invalid citations."""
    text = (raw_text or "").strip()
    if not text:
        return ResponseValidationResult(
            cleaned_text="",
            warnings=["empty_response"],
            passed_quality_checks=False,
        )

    warnings: List[str] = []
    sanitized_citations = False
    sanitized_enums = False
    sanitized_internal = False

    # 1. Citation cleanup:
    #    - For ordinary live inventory/forecast queries (no document citations), strip all [1], [2] markers.
    #    - For document RAG answers, strip any out-of-range bracket index.
    if not allow_document_citations:
        if _NUMERIC_CITATION_RE.search(text):
            text = _NUMERIC_CITATION_RE.sub("", text)
            sanitized_citations = True
    else:
        allowed = set(valid_doc_citation_indices or ())

        def _filter_cite(match: re.Match[str]) -> str:
            nonlocal sanitized_citations
            nums = [int(n.strip()) for n in match.group(0).strip(" []").split(",") if n.strip().isdigit()]
            kept = [str(n) for n in nums if n in allowed]
            if len(kept) != len(nums):
                sanitized_citations = True
            return f" [{', '.join(kept)}]" if kept else ""

        text = _NUMERIC_CITATION_RE.sub(_filter_cite, text)

    # 2. Internal implementation phrase stripping
    for pattern, repl in _LEAKED_INTERNAL_PHRASE_PATTERNS:
        if pattern.search(text):
            text = pattern.sub(repl, text)
            sanitized_internal = True

    # 3. Clean up awkward phrasing artifacts left after phrase removal (e.g. "Based on the , ")
    text = re.sub(r"\bBased on (?:the\s*)?,", "Based on current records,", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAccording to (?:the\s*)?,", "According to current records,", text, flags=re.IGNORECASE)

    # 4. Raw enum translation
    for raw_enum, friendly in INTERNAL_ENUM_REPLACEMENTS:
        enum_pat = re.compile(rf"\b{re.escape(raw_enum)}\b")
        if enum_pat.search(text):
            text = enum_pat.sub(friendly, text)
            sanitized_enums = True

    # Translate standalone CRITICAL / HIGH / LOW uppercase status labels when not part of an uppercase SKU
    # Check SKUs first so we never modify tokens inside real SKU codes like ACC-HIGH-1
    sku_set = {s.upper() for s in expected_skus if s}
    for enum_word, friendly_word in (
        ("CRITICAL", "Critical priority"),
        ("OUT_OF_STOCK", "Out of stock"),
    ):
        pat = re.compile(rf"(?<![A-Z0-9_-])\b{enum_word}\b(?![A-Z0-9_-])")
        if enum_word not in sku_set and pat.search(text):
            text = pat.sub(friendly_word, text)
            sanitized_enums = True

    # 5. Formatting cleanup
    cleaned = _cleanup_spacing(text)

    # 6. Quality & grounding assertions (recorded as telemetry warnings)
    if _PHASE_NAME_DETECT_RE.search(cleaned):
        warnings.append("residual_phase_name")
    if _RAW_ENUM_DETECT_RE.search(cleaned):
        warnings.append("residual_internal_enum")
    if _TECH_JARGON_DETECT_RE.search(cleaned):
        warnings.append("technical_jargon_leak")
    if len(cleaned) > 120 and cleaned.count("**") > 24:
        warnings.append("excessive_bold_formatting")

    # Verify reported total product count if reconciled summary gives an exact count
    if reconciled_summary and "headline_count" in reconciled_summary and reconciled_summary["headline_count"] is not None:
        expected_n = int(reconciled_summary["headline_count"])
        claim = re.search(r"\b(\d+)\s+products?\s+(?:are|need|require|currently|running low|below)\b", cleaned, re.IGNORECASE)
        if claim and int(claim.group(1)) != expected_n:
            warnings.append(f"count_mismatch:claimed={claim.group(1)},actual={expected_n}")

    return ResponseValidationResult(
        cleaned_text=cleaned,
        warnings=warnings,
        sanitized_citations=sanitized_citations,
        sanitized_enums=sanitized_enums,
        sanitized_internal_terms=sanitized_internal,
        passed_quality_checks=len(warnings) == 0,
    )


def evaluate_response_quality(
    response_text: str,
    *,
    expected_terms: Iterable[str] = (),
    forbidden_terms: Iterable[str] = (),
    allow_citations: bool = False,
) -> Dict[str, Any]:
    """Deterministic quality evaluation helper used by test suites & offline evaluations."""
    issues: List[str] = []
    if not response_text or not response_text.strip():
        issues.append("empty_response")

    if _PHASE_NAME_DETECT_RE.search(response_text):
        issues.append("contains_phase_name")
    if _RAW_ENUM_DETECT_RE.search(response_text):
        issues.append("contains_internal_enum")
    if _TECH_JARGON_DETECT_RE.search(response_text):
        issues.append("contains_technical_jargon")
    if not allow_citations and _NUMERIC_CITATION_RE.search(response_text):
        issues.append("contains_numeric_citation_marker")

    lowered = response_text.lower()
    for term in expected_terms:
        if term.lower() not in lowered:
            issues.append(f"missing_expected_term:{term}")

    for bad in forbidden_terms:
        if bad.lower() in lowered:
            issues.append(f"contains_forbidden_term:{bad}")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "length": len(response_text),
    }
