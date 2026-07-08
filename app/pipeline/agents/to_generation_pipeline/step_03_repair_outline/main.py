"""S1 Validator Refine — repair A0 TO outline from S1 blocker and warning feedback."""

from __future__ import annotations

from typing import Any

from lectora_backend.pipeline.agent.to_generation_pipeline.step_03_repair_outline.agent import S1ValidatorRefineAgent
from lectora_backend.pipeline.agent.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementInput,
    S1RefinementIssue,
    S1RefinementOutput,
)
from lectora_backend.pipeline.agent.to_generation_pipeline.step_03_repair_outline.utils.outline_persister import (
    OutlinePersister,
)
from lectora_backend.pipeline.models import S1ValidationReport, ValidationIssue

_default_agent = S1ValidatorRefineAgent()
_default_persister = OutlinePersister()


def _issue_is_refinable(issue: ValidationIssue) -> bool:
    return _default_agent.is_refinable(issue)


def _issues_from_report(report: S1ValidationReport) -> list[S1RefinementIssue]:
    return _default_agent.issues_from_report(report)


def _build_user_message(input_data: S1RefinementInput) -> str:
    return _default_agent.build_user_message(input_data)


def persist_refined_to_outline(shared_state_path: str, refined_outline: dict[str, Any]) -> None:
    """Write repaired outline back to shared_state and llm_to_outline.json."""
    _default_persister.persist(shared_state_path, refined_outline)


__all__ = [
    "S1RefinementInput",
    "S1RefinementIssue",
    "S1RefinementOutput",
    "S1ValidatorRefineAgent",
    "_build_user_message",
    "_issue_is_refinable",
    "_issues_from_report",
    "persist_refined_to_outline",
]
