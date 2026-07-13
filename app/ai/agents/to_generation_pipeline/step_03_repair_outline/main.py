"""S1 Validator Refine — repair A0 TO outline from S1 blocker and warning feedback."""

from __future__ import annotations

from app.ai.agents.to_generation_pipeline.step_03_repair_outline.agent import S1ValidatorRefineAgent
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementInput,
    S1RefinementIssue,
    S1RefinementOutput,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.issues import (
    RefinementIssueFilter,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.message_builder import (
    RefinementMessageBuilder,
)
from app.ai.agents.to_generation_pipeline.models import S1ValidationReport, ValidationIssue

_issue_filter = RefinementIssueFilter()
_message_builder = RefinementMessageBuilder()


def _issue_is_refinable(issue: ValidationIssue) -> bool:
    return _issue_filter.is_refinable(issue)


def _issues_from_report(report: S1ValidationReport) -> list[S1RefinementIssue]:
    return _issue_filter.from_report(report)


def _build_user_message(input_data: S1RefinementInput) -> str:
    return _message_builder.build(input_data)


__all__ = [
    "S1RefinementInput",
    "S1RefinementIssue",
    "S1RefinementOutput",
    "S1ValidatorRefineAgent",
    "_build_user_message",
    "_issue_is_refinable",
    "_issues_from_report",
]
