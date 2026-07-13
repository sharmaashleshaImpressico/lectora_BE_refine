"""Shared text utilities for A0 pipeline steps."""

import re
from typing import Any


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that some models insert."""
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def resolve_value(
    key: str, explicit: dict, rule_defaults: dict, inferred: dict
) -> tuple[Any, str]:
    """Resolve a value from three sources in priority order.

    Returns (value, source) where source is one of:
      'explicitly_provided', 'derived_from_rule_pack', 'inferred'
    """
    if key in explicit and explicit[key] is not None:
        return explicit[key], "explicitly_provided"
    if key in rule_defaults and rule_defaults[key] is not None:
        return rule_defaults[key], "derived_from_rule_pack"
    if key in inferred and inferred[key] is not None:
        return inferred[key], "inferred"
    return None, "unresolved"
