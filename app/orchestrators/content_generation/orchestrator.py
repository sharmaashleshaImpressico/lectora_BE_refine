"""Orchestrates content generation workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.content_generation_agent.content_validation import (
    validate_content,
)
from app.ai.agents.content_generation_agent.content_writer_agent.content_refine_agent import (
    refine_sections,
)
from app.ai.agents.content_generation_agent.content_writer_agent.runner import (
    generate_course_content,
    render_study_guide,
)
from app.ai.agents.content_generation_agent.models import A2Output, S2ValidationReport
from app.ai.agents.content_generation_agent.section_mapper.runner import (
    map_sections,
)
from app.ai.rule_pack_config import resolve_content_rule_pack_from_shared_state

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 2


def _is_blocked(validation: S2ValidationReport) -> bool:
    return validation.blockers > 0


@dataclass
class ContentGenerationInput:
    """Everything the content-generation pipeline needs — no shared_state.json."""

    run_id: str
    course_spec: dict[str, Any]
    outline: dict[str, Any]
    course_title: str
    course_description: str
    learning_objectives: list[str]
    docx_path: str
    content_sample: str = ""
    course_difficulty: str = "intermediate"
    course_audience: str = ""
    special_instructions: str | None = None
    course_config: dict[str, Any] = field(default_factory=dict)
    source_file_specs: list[dict[str, Any]] | None = None
    rule_family: str | None = None
    output_path: str | None = None


@dataclass
class ContentGenerationResult:
    """Final output of the content generation (A2/S2) pipeline."""

    enriched_sections: list[dict[str, Any]]
    a2: A2Output
    validation: S2ValidationReport
    validation_passed: bool
    repair_attempts: int
    blocked: bool
    study_guide_path: str | None


class ContentGenerationOrchestrator:
    """
    Workflow:

    Section Mapper
        ↓
    Generate (A2)
        ↓
    Validate (S2)
        ↓
    Refine (CONTENT_REFINE)
        ↓
    Validate (S2)
        ↓
    Pass / Fail → render study guide on pass
    """

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel

    def execute(self, spec: ContentGenerationInput) -> ContentGenerationResult:
        logger.info(
            "[content_generation] Starting | title=%r | difficulty=%r",
            spec.course_title,
            spec.course_difficulty,
        )

        # Step 1: Section Mapper — maps the TO outline onto course_spec content.
        enriched_sections = map_sections(spec.course_spec, spec.outline)

        # Step 2: Generate content (A2)
        current_a2 = generate_course_content(
            self.kernel,
            run_id=spec.run_id,
            enriched_sections=enriched_sections,
            docx_path=spec.docx_path,
            course_title=spec.course_title,
            course_description=spec.course_description,
            learning_objectives=spec.learning_objectives,
            content_sample=spec.content_sample,
            course_difficulty=spec.course_difficulty,
            course_audience=spec.course_audience,
            special_instructions=spec.special_instructions,
            course_config=spec.course_config,
            source_file_specs=spec.source_file_specs,
        )

        rule_pack = resolve_content_rule_pack_from_shared_state(
            {"course_difficulty": spec.course_difficulty, "rule_family": spec.rule_family},
            purpose="validate",
            difficulty_override=spec.course_difficulty,
        )
        if not rule_pack:
            raise RuntimeError(f"Could not resolve rule pack for difficulty {spec.course_difficulty!r}")

        validation_context = {
            "course_title": spec.course_title,
            "course_audience": spec.course_audience,
            "course_difficulty": spec.course_difficulty,
            "special_instructions": spec.special_instructions,
            "extracted_inputs": {"learning_objectives": spec.learning_objectives},
        }

        # Step 3: Initial validation (S2)
        validation = validate_content(
            self.kernel,
            sections=current_a2.sections,
            a2_output=current_a2,
            rule_pack=rule_pack,
            context=validation_context,
            run_id=spec.run_id,
            phase="full",
        )

        if not _is_blocked(validation):
            return ContentGenerationResult(
                enriched_sections=enriched_sections,
                a2=current_a2,
                validation=validation,
                validation_passed=True,
                repair_attempts=0,
                blocked=False,
                study_guide_path=self._maybe_render(current_a2, spec),
            )

        # Step 4: Repair loop
        for attempt in range(1, _MAX_REPAIR_ATTEMPTS + 1):
            logger.info(
                "[content_generation] Refinement attempt %s/%s | blockers=%s",
                attempt,
                _MAX_REPAIR_ATTEMPTS,
                validation.blockers,
            )

            current_a2 = refine_sections(
                self.kernel,
                a2_output=current_a2,
                s2_report=validation,
                rule_pack=rule_pack,
                context=validation_context,
            )
            validation = validate_content(
                self.kernel,
                sections=current_a2.sections,
                a2_output=current_a2,
                rule_pack=rule_pack,
                context=validation_context,
                run_id=spec.run_id,
                phase="full",
            )

            if not _is_blocked(validation):
                return ContentGenerationResult(
                    enriched_sections=enriched_sections,
                    a2=current_a2,
                    validation=validation,
                    validation_passed=True,
                    repair_attempts=attempt,
                    blocked=False,
                    study_guide_path=self._maybe_render(current_a2, spec),
                )

        return ContentGenerationResult(
            enriched_sections=enriched_sections,
            a2=current_a2,
            validation=validation,
            validation_passed=False,
            repair_attempts=_MAX_REPAIR_ATTEMPTS,
            blocked=True,
            study_guide_path=None,
        )

    def _maybe_render(self, a2_output: A2Output, spec: ContentGenerationInput) -> str | None:
        if not spec.output_path:
            return None
        return render_study_guide(a2_output, spec.learning_objectives, spec.output_path)
