"""Course-type → rule-pack resolution (single source of truth).

Maps a course type / rule family — however the caller has it (frontend
label like ``"Insurance CE"``, snake key like ``insurance_ce``, an alias,
or a persisted pack id like ``rp-insurance-ce-v3.4``) — to the real rule
pack defined in ``rule_pack_config/packs/``.

These packs drive **content generation and content validation** only. The
Timed Outline pipeline keeps its own dedicated validation pack
(``app/ai/agents/to_generation_pipeline/to_rule_pack``) — the two must not
be mixed.
"""

from __future__ import annotations

import copy
from typing import Any

from app.ai.rule_pack_config.packs import (
    FIRM_ELEMENT_PACK,
    IARCE_PACK,
    INSURANCE_CE_PACK,
)

DEFAULT_COURSE_RULE_FAMILY = "insurance_ce"

COURSE_RULE_PACKS: dict[str, dict[str, Any]] = {
    "insurance_ce": INSURANCE_CE_PACK,
    "iarce": IARCE_PACK,
    "firm_element": FIRM_ELEMENT_PACK,
}

# Every spelling we accept, lowercased with spaces/hyphens collapsed to "_".
# Covers: family keys, frontend course-type labels (COURSE_TYPE_OPTIONS),
# pack display names, pack ids, and the A0 rule-family aliases.
_FAMILY_KEY_ALIASES: dict[str, str] = {
    # insurance_ce
    "insurance_ce": "insurance_ce",
    "insurance": "insurance_ce",
    "ce": "insurance_ce",
    "insurance_continuing_education": "insurance_ce",
    "rp_insurance_ce_v3.4": "insurance_ce",
    # iarce
    "iarce": "iarce",
    "iar": "iarce",
    "investment_adviser": "iarce",
    "rp_iarce_v3.6": "iarce",
    # firm_element
    "firm_element": "firm_element",
    "firm": "firm_element",
    "finra": "firm_element",
    "firm_element_continuing_education": "firm_element",
    "rp_firm_element_v2.4": "firm_element",
}


def normalize_rule_family_key(value: str | None) -> str | None:
    """Normalize any course-type/rule-family/pack-id spelling to a family key.

    Returns ``None`` when the value is empty or not recognized.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return None
    normalized = raw.replace("-", "_").replace(" ", "_")
    return _FAMILY_KEY_ALIASES.get(normalized)


def resolve_course_rule_pack(
    course_type: str | None = None,
    rule_family: str | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Resolve the content-generation rule pack for a course.

    ``rule_family`` (the already-normalized key, when the caller has one)
    takes precedence over ``course_type`` (the wizard label). Returns
    ``(family_key, pack)`` or ``None`` when neither value is recognized.
    The pack is a deep copy — callers may annotate it freely.
    """
    family_key = normalize_rule_family_key(rule_family) or normalize_rule_family_key(course_type)
    if family_key is None:
        return None
    return family_key, copy.deepcopy(COURSE_RULE_PACKS[family_key])


__all__ = [
    "COURSE_RULE_PACKS",
    "DEFAULT_COURSE_RULE_FAMILY",
    "normalize_rule_family_key",
    "resolve_course_rule_pack",
]
