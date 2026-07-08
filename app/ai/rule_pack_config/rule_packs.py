"""Placeholder rule packs for content generation.

These are generic, reasonable-default constraints (word counts, tone,
error tolerance) — NOT real compliance/style business rules. There is no
existing definition of the real rule packs anywhere in this codebase; swap
the contents of ``RULE_PACKS`` for the actual business rules when available.
"""

from __future__ import annotations

DEFAULT_FAMILY = "general"

_BASE_ERROR_TOLERANCE = {"max_retries_per_step": 3}

_BASE_STYLE_CONSTRAINTS = {
    "voice": "clear, professional, second-person instructional",
    "tone": "neutral",
}

RULE_PACKS: dict[str, dict[str, dict]] = {
    DEFAULT_FAMILY: {
        "basic": {
            "family": DEFAULT_FAMILY,
            "version": "placeholder-1",
            "active_difficulty": "basic",
            "word_count": {"min_per_subtopic": 100, "max_per_subtopic": 400},
            "style_constraints": _BASE_STYLE_CONSTRAINTS,
            "error_tolerance": _BASE_ERROR_TOLERANCE,
        },
        "intermediate": {
            "family": DEFAULT_FAMILY,
            "version": "placeholder-1",
            "active_difficulty": "intermediate",
            "word_count": {"min_per_subtopic": 150, "max_per_subtopic": 600},
            "style_constraints": _BASE_STYLE_CONSTRAINTS,
            "error_tolerance": _BASE_ERROR_TOLERANCE,
        },
        "advanced": {
            "family": DEFAULT_FAMILY,
            "version": "placeholder-1",
            "active_difficulty": "advanced",
            "word_count": {"min_per_subtopic": 200, "max_per_subtopic": 900},
            "style_constraints": _BASE_STYLE_CONSTRAINTS,
            "error_tolerance": _BASE_ERROR_TOLERANCE,
        },
    }
}

__all__ = ["DEFAULT_FAMILY", "RULE_PACKS", "TO_RULE_PACKS", "resolve_rule_pack"]


# ─────────────────────────────────────────────────────────────────────────────
# Timed-Outline (TO) generation pipeline — rule-family packs
# ─────────────────────────────────────────────────────────────────────────────
# Placeholder rule packs for the TO (A0/S1/A1) pipeline, keyed by the
# compliance "rule family" the frontend/A0 classification resolves to (see
# ``to_generation_pipeline/step_01_parse_and_generate_outline/shared/constants
# /rule_families.py`` — VALID_RULE_FAMILIES = {insurance_ce, iarce,
# firm_element}). As with ``RULE_PACKS`` above, there is no existing
# definition of the real compliance business rules anywhere in this
# codebase; these are generic, reasonable defaults — swap them out when the
# real rule packs are available.
#
# Unlike ``RULE_PACKS`` (nested by difficulty), each TO family here resolves
# to a single flat pack — TO pacing/structure rules do not vary by difficulty.

_TO_BASE_CONTENT_RULES: dict[str, object] = {
    "require_timed_outline": False,
    "must_map_to_learning_objectives": True,
    # 9,000 words == 1 base CE credit hour (matches the TO generation pacing
    # formula in generate_outline/constants/prompts.py).
    "words_per_credit_hour": 9000,
}

TO_RULE_PACKS: dict[str, dict] = {
    "insurance_ce": {
        "family": "insurance_ce",
        "id": "insurance_ce",
        "version": "placeholder-1",
        "content_rules": dict(_TO_BASE_CONTENT_RULES),
    },
    "iarce": {
        "family": "iarce",
        "id": "iarce",
        "version": "placeholder-1",
        "content_rules": dict(_TO_BASE_CONTENT_RULES),
    },
    "firm_element": {
        "family": "firm_element",
        "id": "firm_element",
        "version": "placeholder-1",
        "content_rules": dict(_TO_BASE_CONTENT_RULES),
    },
}


def resolve_rule_pack(rule_family_key: str, difficulty: str | None = None) -> dict | None:
    """Resolve a rule pack dict for ``rule_family_key`` (+ optional ``difficulty``).

    Checks the TO rule-family packs first (flat, no difficulty axis), then
    falls back to the content-generation ``RULE_PACKS`` (nested by
    difficulty). Returns ``None`` when the family key is unknown to either.
    """
    if rule_family_key in TO_RULE_PACKS:
        return TO_RULE_PACKS[rule_family_key]

    family_packs = RULE_PACKS.get(rule_family_key)
    if not family_packs:
        return None
    if difficulty and difficulty in family_packs:
        return family_packs[difficulty]
    return next(iter(family_packs.values()), None)
