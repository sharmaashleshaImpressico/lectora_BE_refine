"""Orchestrates topic outline (timed outline) generation workflows."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from semantic_kernel import Kernel

from app.pipeline.agents.to_generation_pipeline.step_01_parse_and_generate_outline.phases.synthesizer import (
    A0RequestSynthesizer,
)
from app.pipeline.agents.to_generation_pipeline.step_02_validate_outline.orchestrator.validator import (
    S1Validator,
)
from app.pipeline.agents.to_generation_pipeline.step_03_repair_outline.agent import (
    S1ValidatorRefineAgent,
)
from app.pipeline.agents.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementInput,
    S1RefinementIssue,
)

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 2
_PASSING_STATUSES = {"pass", "pass_with_warnings"}


@dataclass
class TopicOutlineResult:
    """Final output of the topic outline (TO) generation pipeline."""

    outline: dict[str, Any]
    validation_passed: bool
    repair_attempts: int
    blocked: bool
    final_issues: list[dict[str, Any]] = field(default_factory=list)


def _issues_as_dicts(issues: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "field": issue.field,
            "message": issue.message,
            "severity": issue.severity,
            "expected": issue.expected,
            "found": issue.found,
            "rule_source": issue.rule_source,
        }
        for issue in issues
    ]


def _refinement_issues(issues: list[Any]) -> list[S1RefinementIssue]:
    return [
        S1RefinementIssue(
            field=issue.field,
            message=issue.message,
            severity=issue.severity,
            expected=issue.expected,
            found=str(issue.found),
            rule_source=issue.rule_source,
            remediation=issue.remediation,
        )
        for issue in issues
    ]


class TopicOutlineOrchestrator:
    """
    Workflow:

    Generate (A0)
        ↓
    Validate (S1)
        ↓
    Refine (S1_Refine)
        ↓
    Validate (S1)
        ↓
    Pass / Fail
    """

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel

        self.refinement_agent = S1ValidatorRefineAgent(
            kernel=self.kernel
        )

    def execute(
        self,
        *,
        docx_paths: list[str] | None = None,
        pdf_paths: list[str] | None = None,
        to_outline_doc_path: str | None = None,
        course_difficulty: str,
        audience: str = "",
        custom_to_prompt: str | None = None,
        course_type_hint: str | None = None,
        course_description: str | None = None,
        duration_hours: float | None = None,
        calculated_word_count: int | None = None,
        rule_family: str | None = None,
        validation_hints: str | None = None,
    ) -> TopicOutlineResult:
        logger.info(
            "[topic_outline] Starting | difficulty=%r | has_to=%s",
            course_difficulty,
            bool(to_outline_doc_path),
        )

        # Step 1: Generate the outline (A0)
        generation_agent = A0RequestSynthesizer(
            kernel=self.kernel,
            docx_paths=docx_paths,
            pdf_paths=pdf_paths,
            to_outline_doc_path=to_outline_doc_path,
            course_difficulty=course_difficulty,
            custom_to_prompt=custom_to_prompt,
            course_type_hint=course_type_hint,
            audience=audience or None,
            course_description=course_description,
            duration_hours=duration_hours,
            calculated_word_count=calculated_word_count,
            rule_family=rule_family,
            validation_hints=validation_hints,
        )
        a0_result = generation_agent.run()
        current_outline = a0_result.llm_to_outline or {}

        # A0RequestSynthesizer only exposes its full working state via a file
        # on disk (shared_state_path) — this is the one unavoidable disk read,
        # since that agent's internals aren't in scope here. Everything past
        # this point (validate/refine loop) stays in-memory: `shared_state` is
        # loaded once and then mutated directly, never re-read or re-written.
        with open(a0_result.shared_state_path, encoding="utf-8") as handle:
            shared_state = json.load(handle)

        # Step 2: Initial validation (S1)
        validator_agent = S1Validator(
            kernel=self.kernel,
            shared_state=shared_state,
        )
        validation = validator_agent.run()

        if validation.status in _PASSING_STATUSES:
            return TopicOutlineResult(
                outline=current_outline,
                validation_passed=True,
                repair_attempts=0,
                blocked=False,
            )

        current_issues = validation.issues

        # Step 3: Repair loop
        for attempt in range(1, _MAX_REPAIR_ATTEMPTS + 1):
            logger.info(
                "[topic_outline] Refinement attempt %s/%s | issues=%s",
                attempt,
                _MAX_REPAIR_ATTEMPTS,
                len(current_issues),
            )

            refinement = self.refinement_agent.run(
                S1RefinementInput(
                    current_outline=current_outline,
                    issues=_refinement_issues(current_issues),
                )
            )

            if not refinement.applied:
                logger.warning(
                    "[topic_outline] Refiner made no changes — stopping repair loop"
                )
                break

            current_outline = refinement.outline
            # Feed the refined outline back into the in-memory shared_state so
            # the next validation pass checks the updated outline, not the
            # original one — this replaces what used to be a re-read/re-write
            # of shared_state.json on disk between repair attempts.
            shared_state["llm_to_outline_classification"] = current_outline
            validation = validator_agent.run()
            current_issues = validation.issues

            if validation.status in _PASSING_STATUSES:
                return TopicOutlineResult(
                    outline=current_outline,
                    validation_passed=True,
                    repair_attempts=attempt,
                    blocked=False,
                )

        return TopicOutlineResult(
            outline=current_outline,
            validation_passed=False,
            repair_attempts=_MAX_REPAIR_ATTEMPTS,
            blocked=True,
            final_issues=_issues_as_dicts(current_issues),
        )
