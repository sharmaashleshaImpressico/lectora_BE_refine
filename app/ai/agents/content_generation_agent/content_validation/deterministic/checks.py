"""
Content validation checks — aggregator module.

All checks are split across focused sub-modules:
  • content_checks.py     — A2 completeness, compliance, voice/tone, structure, LO coverage
  • word_count_checks.py  — TO target deviation, course bands, doc-bounds

Deterministic checks are orchestrated by deterministic/runner.py.
AI-based checks live in ai_validation/runner.py.
"""

from .content_checks import (
    check_a2_completeness,
    check_callouts_per_section,
    check_examples_per_section,
    check_forbidden_phrases,
    check_intro_section,
    check_lo_coverage,
    check_los_in_first_section,
    check_no_duplicate_headings,
    check_regulatory_mode,
    check_required_behaviors,
    check_section_non_empty,
    check_summary_section,
    check_voice_pronouns,
)
from .word_count_checks import (
    check_course_word_count_bands,
    check_word_count_against_doc_bounds,
    check_word_count_target,
)

__all__ = [
    # Content checks
    "check_a2_completeness",
    "check_callouts_per_section",
    "check_examples_per_section",
    "check_forbidden_phrases",
    "check_intro_section",
    "check_lo_coverage",
    "check_los_in_first_section",
    "check_no_duplicate_headings",
    "check_regulatory_mode",
    "check_required_behaviors",
    "check_section_non_empty",
    "check_summary_section",
    "check_voice_pronouns",
    # Word-count / pacing checks
    "check_course_word_count_bands",
    "check_word_count_against_doc_bounds",
    "check_word_count_target",
]
