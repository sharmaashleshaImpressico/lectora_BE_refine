"""Orchestrates learning objective generation workflows."""

from __future__ import annotations

import logging
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.learning_objective_agent.Lo_generation.main import (
    LOGenerationAgent,
)
from app.ai.agents.learning_objective_agent.Lo_generation.models import (
    LOGenerationInput,
)
from app.ai.agents.learning_objective_agent.Lo_refine_agent.main import (
    LORefinementAgent,
)
from app.ai.agents.learning_objective_agent.Lo_refine_agent.models import (
    LORefinementInput,
)
from app.ai.agents.learning_objective_agent.Lo_regenerate_agent.main import (
    LORegenerationAgent,
)
from app.ai.agents.learning_objective_agent.Lo_regenerate_agent.models import (
    LORegenerationInput,
)
from app.ai.agents.learning_objective_agent.Lo_validator.main import (
    LOValidatorAgent,
)
from app.ai.agents.learning_objective_agent.Lo_validator.models import (
    LOValidationInput,
    LOValidationIssue,
)
from app.ai.agents.learning_objective_agent.models import CourseMetadata
from app.orchestrators.learning_objective.models import (
    LearningObjectiveGenerationInput,
    LearningObjectiveGenerationResult,
    LearningObjectiveRegenerationInput,
    LearningObjectiveRegenerationResult,
)

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 2


def _issues_as_dicts(
    issues: list[LOValidationIssue],
) -> list[dict[str, Any]]:
    return [
        {
            "type": issue.type,
            "message": issue.message,
            "affected_objectives": issue.affected_objectives,
            "expected_action": issue.expected_action,
        }
        for issue in issues
    ]


def _to_course_metadata(input_data: LearningObjectiveGenerationInput) -> CourseMetadata:
    return CourseMetadata(
        course_title=input_data.course_title,
        course_description=input_data.course_description,
        course_type=input_data.course_type,
        course_duration=input_data.course_duration,
        skill_level=input_data.skill_level,
        target_audience=input_data.target_audience,
        required_topics=input_data.required_topics,
        source_analyses=[
            {"source_name": path} for path in input_data.source_materials
        ],
    )


def _to_regeneration_agent_input(
    input_data: LearningObjectiveRegenerationInput,
) -> LORegenerationInput:
    return LORegenerationInput(
        current_objectives=input_data.current_objectives,
        regeneration_prompt=input_data.regeneration_prompt,
        course_title=input_data.course_title,
        course_type=input_data.course_type,
        course_duration=input_data.course_duration,
        skill_level=input_data.skill_level,
        target_audience=input_data.target_audience,
    )


class LearningObjectiveOrchestrator:
    """
    Workflow:

    Generate
        ↓
    Validate
        ↓
    Refine
        ↓
    Validate
        ↓
    Pass / Fail
    """

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel

        self.generation_agent = LOGenerationAgent(
            kernel=self.kernel
        )
        self.validator_agent = LOValidatorAgent(
            kernel=self.kernel
        )
        self.refinement_agent = LORefinementAgent(
            kernel=self.kernel
        )

    def generate_learning_objectives(
        self,
        input_data: LearningObjectiveGenerationInput,
    ) -> LearningObjectiveGenerationResult:
        metadata = _to_course_metadata(input_data)
        logger.info(
            "[learning_objective] Starting | title=%r",
            metadata.course_title,
        )

        # Step 1: Generate objectives
        generation = self.generation_agent.run(
            LOGenerationInput(metadata=metadata)
        )
        current_objectives = generation.objectives

        if not current_objectives:
            logger.warning(
                "[learning_objective] Generation returned empty objectives"
            )
            return LearningObjectiveGenerationResult(
                objectives=[],
                validation_passed=False,
                repair_attempts=0,
            )

        # Step 2: Initial validation
        validation = self.validator_agent.run(
            LOValidationInput(
                objectives=current_objectives,
                metadata=metadata,
            )
        )

        if validation.passed:
            return LearningObjectiveGenerationResult(
                objectives=current_objectives,
                validation_passed=True,
                repair_attempts=0,
            )

        current_issues = validation.issues

        # Step 3: Repair loop
        for attempt in range(1, _MAX_REPAIR_ATTEMPTS + 1):
            logger.info(
                "[learning_objective] Refinement attempt %s/%s | issues=%s",
                attempt,
                _MAX_REPAIR_ATTEMPTS,
                len(current_issues),
            )

            refinement = self.refinement_agent.run(
                LORefinementInput(
                    objectives=current_objectives,
                    issues=current_issues,
                    metadata=metadata,
                )
            )

            refined_objectives = refinement.objectives

            if not refined_objectives:
                logger.warning(
                    "[learning_objective] Refiner returned empty objectives"
                )
                break

            validation = self.validator_agent.run(
                LOValidationInput(
                    objectives=refined_objectives,
                    metadata=metadata,
                )
            )

            current_objectives = refined_objectives
            current_issues = validation.issues

            if validation.passed:
                return LearningObjectiveGenerationResult(
                    objectives=current_objectives,
                    validation_passed=True,
                    repair_attempts=attempt,
                )

        return LearningObjectiveGenerationResult(
            objectives=current_objectives,
            validation_passed=False,
            repair_attempts=_MAX_REPAIR_ATTEMPTS,
            final_issues=_issues_as_dicts(current_issues),
        )

    def regenerate_learning_objectives(
        self,
        input_data: LearningObjectiveRegenerationInput,
    ) -> LearningObjectiveRegenerationResult:
        """Revise existing objectives from user feedback — no validation or repair."""
        agent_input = _to_regeneration_agent_input(input_data)
        logger.info(
            "[learning_objective] Regenerating | objectives=%d | prompt_length=%d",
            len(agent_input.current_objectives),
            len(agent_input.regeneration_prompt.strip()),
        )
        result = LORegenerationAgent(kernel=self.kernel).run(agent_input)
        return LearningObjectiveRegenerationResult(objectives=result.objectives)
