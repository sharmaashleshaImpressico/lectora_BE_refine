"""Deterministic checks for enriched / repaired course outline (A1 course_spec)."""

from .course_rule_pack_checks import RulePackChecks, check_rule_pack_sanity
from .course_spec_checks import (
    A1Checks,
    check_a1_assessment_rules,
    check_a1_credit_hours,
    check_a1_credit_hours_against_rule_pack,
    check_a1_kc_count,
    check_a1_learning_objectives_range,
    check_a1_lo_coverage,
    check_a1_sections,
)

__all__ = [
    "A1Checks",
    "RulePackChecks",
    "check_rule_pack_sanity",
    "check_a1_sections",
    "check_a1_kc_count",
    "check_a1_lo_coverage",
    "check_a1_learning_objectives_range",
    "check_a1_credit_hours_against_rule_pack",
    "check_a1_credit_hours",
    "check_a1_assessment_rules",
]
