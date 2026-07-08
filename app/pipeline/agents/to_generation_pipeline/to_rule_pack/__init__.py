"""Timed-outline rule pack for the TO generation pipeline."""

from lectora_backend.pipeline.agent.to_generation_pipeline.to_rule_pack.constants import (
    TO_RULE_PACK_ID,
    TO_RULE_PACK_NAME,
    TO_RULE_PACK_VERSION,
)
from lectora_backend.pipeline.agent.to_generation_pipeline.to_rule_pack.general_timed_outline_rules import (
    GENERAL_TIMED_OUTLINE_RULES,
)

__all__ = [
    "GENERAL_TIMED_OUTLINE_RULES",
    "TO_RULE_PACK_ID",
    "TO_RULE_PACK_NAME",
    "TO_RULE_PACK_VERSION",
    "get_to_rule_pack",
]


def get_to_rule_pack() -> dict:
    """Return the active TO validation rule pack with metadata."""
    return {
        "id": TO_RULE_PACK_ID,
        "name": TO_RULE_PACK_NAME,
        "version": TO_RULE_PACK_VERSION,
        **GENERAL_TIMED_OUTLINE_RULES,
    }
