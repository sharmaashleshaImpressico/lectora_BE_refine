"""Placeholder rule-pack resolution for content generation.

These are generic defaults, not the real business rules — see
``rule_packs.py`` for the notice and swap point.
"""

from .content_generation_filter import resolve_content_rule_pack_from_shared_state
from .course_overview import resolve_course_overview_for_output
from .prompt_bundle import (
    bundle_rule_pack_for_prompt,
    bundle_rule_pack_for_validation_prompt,
)
from .rule_packs import DEFAULT_FAMILY, RULE_PACKS

__all__ = [
    "DEFAULT_FAMILY",
    "RULE_PACKS",
    "resolve_content_rule_pack_from_shared_state",
    "resolve_course_overview_for_output",
    "bundle_rule_pack_for_prompt",
    "bundle_rule_pack_for_validation_prompt",
]
