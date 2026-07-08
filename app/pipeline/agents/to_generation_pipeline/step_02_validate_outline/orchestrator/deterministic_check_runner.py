"""Run deterministic S1 checks for TO outline validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from ..constants.validation import is_out_of_scope_to_validation_issue
from ..to_validation_check.ai_check import run_ai_outline_checks
from ..to_validation_check.deterministic_check import (
    check_a0_classification,
    check_a0_images,
    check_a0_metadata,
    check_to_required_fields,
)
from .rule_source_resolver import RuleSourceContext

S1ValidationPhase = Literal["full", "to_only", "a1_only"]
logger = logging.getLogger(__name__)


@dataclass
class CheckRunResult:
    raw_issues: list[dict]
    priority_rule: str


class DeterministicCheckRunner:
    """Executes TO rule-pack validation checks and optional AI semantic checks."""

    @classmethod
    def run(
        cls,
        *,
        phase: S1ValidationPhase,
        shared_state: dict,
        course_spec: dict,
        a1_output: dict,
        a1_ready: bool,
        rule_context: RuleSourceContext,
    ) -> CheckRunResult:
        _ = (phase, course_spec, a1_output, a1_ready)
        raw_issues: list[dict] = []
        priority_rule = "TO timed-outline rule pack validation."

        if rule_context.use_to_rule_pack:
            logger.info("[S1] Checking TO outline (to_rule_pack)...")
            raw_issues.extend(check_to_required_fields(shared_state))
            raw_issues.extend(check_a0_metadata(shared_state))
            raw_issues.extend(check_a0_classification(shared_state))
            raw_issues.extend(check_a0_images(shared_state))

            logger.info("[S1] Running AI semantic outline validation...")
            ai_issues, priority_rule = run_ai_outline_checks(
                shared_state=shared_state,
                course_spec=course_spec,
                to_rule_pack=rule_context.to_rule_pack,
            )
            raw_issues.extend(ai_issues)

        filtered_issues = [
            issue for issue in raw_issues if not is_out_of_scope_to_validation_issue(issue)
        ]
        return CheckRunResult(raw_issues=filtered_issues, priority_rule=priority_rule)
