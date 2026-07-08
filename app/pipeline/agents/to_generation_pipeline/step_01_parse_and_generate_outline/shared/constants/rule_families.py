"""Rule-family resolution from frontend input."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_RULE_FAMILIES: frozenset[str] = frozenset({"insurance_ce", "iarce", "firm_element"})
DEFAULT_RULE_FAMILY = "insurance_ce"
FE_RULE_FAMILY_CONFIDENCE = 1.0
FE_RULE_FAMILY_REASONING = (
    "Rule family provided by the frontend — no LLM classification performed."
)

RULE_FAMILY_ALIASES: dict[str, str] = {
    "insurance": "insurance_ce",
    "ce": "insurance_ce",
    "iarce": "iarce",
    "iar": "iarce",
    "investment_adviser": "iarce",
    "firm": "firm_element",
    "firm_element": "firm_element",
    "finra": "firm_element",
}


class RuleFamilyResolver:
    """Normalises rule-family strings supplied by the frontend."""

    @classmethod
    def resolve(cls, raw_value: str | None) -> str | None:
        raw = (raw_value or "").strip().lower()
        if not raw:
            return None
        if raw in VALID_RULE_FAMILIES:
            return raw
        family = RULE_FAMILY_ALIASES.get(raw)
        if family in VALID_RULE_FAMILIES:
            logger.info("[A0] Rule family resolved from FE: %r → %r", raw, family)
            return family
        logger.warning(
            "[A0] Unknown rule_family %r from FE — falling back to %r",
            raw,
            DEFAULT_RULE_FAMILY,
        )
        return DEFAULT_RULE_FAMILY

    @classmethod
    def build_classification_result(cls, family: str, audience: str | None) -> dict:
        return {
            "rule_family": family,
            "confidence": FE_RULE_FAMILY_CONFIDENCE,
            "audience": audience,
            "topic": None,
            "course_type": None,
            "category": None,
            "reasoning": FE_RULE_FAMILY_REASONING,
        }
