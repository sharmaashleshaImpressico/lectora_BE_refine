"""Run all deterministic S2/content validation checks."""

from __future__ import annotations

import logging
from typing import Any

from .checks import (
    check_a2_completeness,
    check_callouts_per_section,
    check_course_word_count_bands,
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
    check_word_count_against_doc_bounds,
)

logger = logging.getLogger(__name__)


def run_deterministic_validation(
    *,
    phase: str,
    scoped_a2_output: dict[str, Any],
    sections: list[dict],
    a2_output: dict[str, Any],
    shared_state: dict[str, Any],
    rule_pack: dict[str, Any],
) -> list[dict]:
    """Execute structure, compliance, and length checks without LLM calls."""
    raw_issues: list[dict] = []

    logger.info("[S2][deterministic] Checking A2 completeness...")
    raw_issues.extend(check_a2_completeness(scoped_a2_output))

    logger.info("[S2][deterministic] Checking section content...")
    raw_issues.extend(check_section_non_empty(sections))

    logger.info("[S2][deterministic] Checking compliance_elements...")
    raw_issues.extend(check_forbidden_phrases(sections, rule_pack))
    raw_issues.extend(check_required_behaviors(sections, rule_pack))
    raw_issues.extend(check_voice_pronouns(sections, rule_pack))
    raw_issues.extend(check_regulatory_mode(rule_pack))

    logger.info("[S2][deterministic] Checking content_rules...")
    raw_issues.extend(check_callouts_per_section(sections, rule_pack))
    raw_issues.extend(check_examples_per_section(sections, rule_pack))
    raw_issues.extend(check_no_duplicate_headings(sections, rule_pack))

    if phase == "full":
        raw_issues.extend(check_intro_section(sections, rule_pack))
        raw_issues.extend(check_los_in_first_section(sections, rule_pack))
        raw_issues.extend(check_summary_section(sections, rule_pack))
        raw_issues.extend(check_course_word_count_bands(a2_output, rule_pack))

        logger.info("[S2][deterministic] Checking document generation bounds...")
        raw_issues.extend(check_word_count_against_doc_bounds(a2_output, shared_state, rule_pack))

        logger.info("[S2][deterministic] Checking LO coverage...")
        raw_issues.extend(check_lo_coverage(sections, shared_state, rule_pack))

    return raw_issues
