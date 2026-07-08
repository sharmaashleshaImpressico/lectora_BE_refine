"""Thresholds and weights for multi-strategy image-to-section mapping."""

from __future__ import annotations

from typing import Final

HEADING_ANCHOR_MIN_SCORE: Final[float] = 0.45
TEXT_FUZZY_MIN_SCORE: Final[float] = 0.40
VECTOR_MIN_SCORE: Final[float] = 0.35
PARA_RANGE_MIN_SCORE: Final[float] = 0.30
MIN_WEIGHTED_SCORE: Final[float] = 0.28

STRATEGY_WEIGHTS_ESTIMATED_PARA: Final[dict[str, float]] = {
    "heading_anchor": 1.0,
    "text_fuzzy": 0.95,
    "vector_search": 0.90,
    "para_range": 0.35,
}

STRATEGY_WEIGHTS_RELIABLE_PARA: Final[dict[str, float]] = {
    "heading_anchor": 1.0,
    "text_fuzzy": 0.85,
    "vector_search": 0.80,
    "para_range": 1.0,
}

PARA_RANGE_MATCH_SCORE: Final[float] = 0.55
