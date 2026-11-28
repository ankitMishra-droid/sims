"""Multilingual language and script detection supporting English, Hindi, Hinglish, and future Indic packs."""

from __future__ import annotations

from dataclasses import dataclass
import re

_HINGLISH_MARKERS = {
    "kaise",
    "kaun",
    "kaunse",
    "kya",
    "kitna",
    "kitne",
    "kab",
    "kahan",
    "nahi",
    "nahin",
    "hain",
    "hai",
    "karo",
    "karein",
    "karte",
    "karna",
    "batao",
    "bataiye",
    "chahiye",
    "kam",
    "zyada",
    "mein",
    "mere",
    "humare",
    "hamare",
    "uska",
    "iski",
    "wale",
    "wala",
    "sakta",
    "sakte",
}

_TOKEN_RE = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class LanguageDetectionResult:
    language: str  # en | hi | mixed | indic_other | other
    confidence: float
    script: str  # latin | devanagari | mixed | other
    devanagari_chars: int
    latin_chars: int
    hinglish_matches: int


def _is_devanagari(ch: str) -> bool:
    code = ord(ch)
    return (0x0900 <= code <= 0x097F) or (0xA8E0 <= code <= 0xA8FF)


def _is_other_indic(ch: str) -> bool:
    code = ord(ch)
    # Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam, Arabic/Urdu
    return (
        (0x0980 <= code <= 0x0D7F)
        or (0x0600 <= code <= 0x06FF)
    )


def detect_language(text: str) -> LanguageDetectionResult:
    """Detect English, Hindi (Devanagari), mixed bilingual, or Hinglish query/document text."""
    if not text or not text.strip():
        return LanguageDetectionResult(
            language="en",
            confidence=0.5,
            script="latin",
            devanagari_chars=0,
            latin_chars=0,
            hinglish_matches=0,
        )

    devanagari_count = 0
    latin_count = 0
    other_indic_count = 0

    for ch in text:
        if _is_devanagari(ch):
            devanagari_count += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin_count += 1
        elif _is_other_indic(ch):
            other_indic_count += 1

    total_script_chars = devanagari_count + latin_count + other_indic_count
    latin_tokens = [tok.lower() for tok in _TOKEN_RE.findall(text)]
    hinglish_hits = sum(1 for tok in latin_tokens if tok in _HINGLISH_MARKERS)

    if total_script_chars == 0:
        return LanguageDetectionResult(
            language="other",
            confidence=0.4,
            script="other",
            devanagari_chars=0,
            latin_chars=0,
            hinglish_matches=0,
        )

    dev_ratio = devanagari_count / total_script_chars
    lat_ratio = latin_count / total_script_chars

    if dev_ratio >= 0.60:
        return LanguageDetectionResult(
            language="hi",
            confidence=round(min(0.99, 0.7 + dev_ratio * 0.3), 2),
            script="devanagari",
            devanagari_chars=devanagari_count,
            latin_chars=latin_count,
            hinglish_matches=hinglish_hits,
        )

    if devanagari_count >= 4 and lat_ratio >= 0.15:
        return LanguageDetectionResult(
            language="mixed",
            confidence=0.85,
            script="mixed",
            devanagari_chars=devanagari_count,
            latin_chars=latin_count,
            hinglish_matches=hinglish_hits,
        )

    if other_indic_count > latin_count and other_indic_count >= 6:
        return LanguageDetectionResult(
            language="indic_other",
            confidence=0.8,
            script="indic",
            devanagari_chars=devanagari_count,
            latin_chars=latin_count,
            hinglish_matches=hinglish_hits,
        )

    # Transliterated Hindi mixed with English inventory terms (Hinglish)
    if hinglish_hits >= 2 or (hinglish_hits == 1 and len(latin_tokens) <= 8):
        return LanguageDetectionResult(
            language="mixed",
            confidence=0.78,
            script="latin",
            devanagari_chars=devanagari_count,
            latin_chars=latin_count,
            hinglish_matches=hinglish_hits,
        )

    return LanguageDetectionResult(
        language="en",
        confidence=round(min(0.99, 0.65 + lat_ratio * 0.35), 2),
        script="latin",
        devanagari_chars=devanagari_count,
        latin_chars=latin_count,
        hinglish_matches=hinglish_hits,
    )
