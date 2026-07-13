"""Rule-pack resolution for content generation/validation.

The real course-type rule packs live in ``packs/``; resolution by course
type / rule family lives in ``course_packs.py``.
"""

from .content_generation_filter import (
    apply_rule_pack_overrides,
    filter_rule_pack_for_validation,
    resolve_content_rule_pack_from_shared_state,
)
from .course_overview import resolve_course_overview_for_output
from .course_packs import (
    COURSE_RULE_PACKS,
    DEFAULT_COURSE_RULE_FAMILY,
    normalize_rule_family_key,
    resolve_course_rule_pack,
)
from .prompt_bundle import (
    bundle_rule_pack_for_prompt,
    bundle_rule_pack_for_validation_prompt,
)

__all__ = [
    "COURSE_RULE_PACKS",
    "DEFAULT_COURSE_RULE_FAMILY",
    "apply_rule_pack_overrides",
    "filter_rule_pack_for_validation",
    "normalize_rule_family_key",
    "resolve_content_rule_pack_from_shared_state",
    "resolve_course_overview_for_output",
    "resolve_course_rule_pack",
    "bundle_rule_pack_for_prompt",
    "bundle_rule_pack_for_validation_prompt",
]
