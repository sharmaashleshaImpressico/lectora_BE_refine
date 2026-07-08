"""Enriched / repaired outline validation — deterministic checks on A1 course_spec."""

from .deterministic_check import (
    check_a1_credit_hours,
    check_a1_credit_hours_against_rule_pack,
    check_a1_kc_count,
    check_a1_learning_objectives_range,
    check_a1_lo_coverage,
    check_a1_sections,
    check_rule_pack_sanity,
)

__all__ = [
    "check_rule_pack_sanity",
    "check_a1_sections",
    "check_a1_kc_count",
    "check_a1_lo_coverage",
    "check_a1_learning_objectives_range",
    "check_a1_credit_hours_against_rule_pack",
    "check_a1_credit_hours",
]
