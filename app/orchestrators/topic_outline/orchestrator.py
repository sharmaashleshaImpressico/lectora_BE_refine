"""Orchestrates topic outline (timed outline) generation workflows."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.phases.synthesizer import (
    A0RequestSynthesizer,
)
from app.ai.agents.to_generation_pipeline.step_02_validate_outline.orchestrator.validator import (
    S1Validator,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.agent import (
    S1ValidatorRefineAgent,
)
from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.shared.models.to_wizard_prompt_context import (
    ToWizardPromptContext,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementInput,
    S1RefinementIssue,
)
from app.orchestrators.topic_outline.models import (
    TimedOutlineGenerationInput,
    TimedOutlineGenerationResult,
)
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 2
_PASSING_STATUSES = {"pass", "pass_with_warnings"}


def _doc_name(title: str | None, fallback: str) -> str:
    s = re.sub(r"[^\w.\-]+", "_", (title or "").strip(), flags=re.UNICODE).strip("._")
    return s or fallback


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


def _split_blob_paths(blob_paths: list[str]) -> tuple[list[str], list[str]]:
    docx_paths: list[str] = []
    pdf_paths: list[str] = []
    for path in blob_paths:
        if path.lower().endswith(".pdf"):
            pdf_paths.append(path)
        else:
            docx_paths.append(path)
    return docx_paths, pdf_paths


def _build_wizard_prompt_context(metadata: TimedOutlineGenerationInput) -> ToWizardPromptContext:
    return ToWizardPromptContext(
        experience_level=metadata.experience_level,
        learner_outcomes=metadata.learner_outcomes,
        audience_notes=metadata.audience,
        tone=metadata.tone,
        depth=metadata.depth,
        emphasis=metadata.emphasis,
        avoid=metadata.avoid,
        include_case_studies=metadata.include_case_studies,
        include_examples=metadata.include_examples,
        include_knowledge_checks=metadata.include_knowledge_checks,
        lesson_style=metadata.lesson_style,
        course_type_hint=metadata.course_type_hint,
        required_topics=tuple(metadata.required_topics),
    )


def _build_validation_hints(metadata: TimedOutlineGenerationInput) -> str | None:
    topic = (metadata.course_topic or "").strip()
    return f"Course topic: {topic}" if topic else None


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

    def generate_timed_outline(
        self,
        metadata: TimedOutlineGenerationInput,
        cancel_event: threading.Event | None = None,
    ) -> TimedOutlineGenerationResult:
        """Entry point for POST /generate-to."""
        docx_paths, pdf_paths = _split_blob_paths(metadata.blob_paths)
        return self.execute(
            docx_paths=docx_paths or None,
            pdf_paths=pdf_paths or None,
            course_difficulty=metadata.difficulty,
            audience=metadata.audience,
            course_description=metadata.course_description,
            duration_hours=metadata.duration_hours,
            calculated_word_count=metadata.calculated_word_count,
            rule_family=metadata.rule_family,
            course_type_hint=metadata.course_type_hint,
            wizard_course_title=metadata.course_title,
            wizard_learning_objectives=metadata.learning_objectives,
            preferred_chapters=metadata.preferred_chapters,
            wizard_prompt_context=_build_wizard_prompt_context(metadata),
            validation_hints=_build_validation_hints(metadata),
            difficulty_level=metadata.difficulty,
            cancel_event=cancel_event,
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
        difficulty_level: str | None = None,
        wizard_course_title: str | None = None,
        wizard_learning_objectives: list[str] | None = None,
        preferred_chapters: int | None = None,
        wizard_prompt_context: ToWizardPromptContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> TimedOutlineGenerationResult:
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
            difficulty_level=difficulty_level or course_difficulty,
            wizard_course_title=wizard_course_title,
            wizard_learning_objectives=wizard_learning_objectives,
            preferred_chapters=preferred_chapters,
            wizard_prompt_context=wizard_prompt_context,
            cancel_event=cancel_event,
        )
        doc_name = generation_agent._resolve_trace_doc_name()
        if wizard_course_title:
            doc_name = _doc_name(wizard_course_title, doc_name)

        with traced_workflow(
            "topic_outline",
            run_id=generation_agent.run_id,
            doc_name=doc_name,
            metadata={"course_title": wizard_course_title},
            input_data={
                "course_title": wizard_course_title,
                "difficulty": course_difficulty,
            },
        ):
            return self._execute_pipeline(generation_agent)

    def _execute_pipeline(
        self,
        generation_agent: A0RequestSynthesizer,
    ) -> TimedOutlineGenerationResult:
        a0_result = generation_agent.run()
        current_outline = a0_result.llm_to_outline or {}

        # A0Result already carries the finalized shared_state in memory.
        # Everything past this point (validate/refine loop) mutates it
        # directly, never re-reading or re-writing shared_state.json.
        shared_state = a0_result.shared_state

        # Step 2: Initial validation (S1)
        validator_agent = S1Validator(
            kernel=self.kernel,
            shared_state=shared_state,
        )
        with traced_workflow("S1"):
            validation = validator_agent.run()

        if validation.status in _PASSING_STATUSES:
            return TimedOutlineGenerationResult(
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

            with traced_workflow("S1_TO_REFINE"):
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
            with traced_workflow("S1"):
                validation = validator_agent.run()
            current_issues = validation.issues

            if validation.status in _PASSING_STATUSES:
                return TimedOutlineGenerationResult(
                    outline=current_outline,
                    validation_passed=True,
                    repair_attempts=attempt,
                    blocked=False,
                )

        return TimedOutlineGenerationResult(
            outline=current_outline,
            validation_passed=False,
            repair_attempts=_MAX_REPAIR_ATTEMPTS,
            blocked=True,
            final_issues=_issues_as_dicts(current_issues),
        )
