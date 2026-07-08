"""Text normalization and fuzzy similarity helpers for image mapping."""

from __future__ import annotations

import difflib
import re

_NUMBER_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*[\s.\-:]*")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")


def normalize_title(text: str) -> str:
    """Lowercase, strip numbering prefixes, and collapse whitespace."""
    cleaned = _NUMBER_PREFIX_RE.sub("", str(text or "").lower())
    cleaned = _NON_ALNUM_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def fuzzy_ratio(left: str, right: str) -> float:
    """Return a 0–1 similarity ratio between two strings."""
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    return difflib.SequenceMatcher(None, left_norm, right_norm).ratio()


def best_fuzzy_match(query: str, candidates: list[str]) -> tuple[int, float]:
    """Return index and score of the best fuzzy match for query in candidates."""
    if not query.strip() or not candidates:
        return -1, 0.0

    best_idx = -1
    best_score = 0.0
    for idx, candidate in enumerate(candidates):
        score = fuzzy_ratio(query, candidate)
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx, best_score


def join_non_empty(parts: list[str | None]) -> str:
    """Join non-empty strings with a single space."""
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())
