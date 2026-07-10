"""Orchestrates required topics generation workflow."""

from __future__ import annotations

import logging
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.required_topic.models import RTPipelineMetadata
from app.ai.agents.required_topic.rt_generation.main import (
    RTGenerationAgent,
)
from app.ai.agents.required_topic.rt_generation.models import (
    RTGenerationInput,
)
from app.ai.agents.required_topic.rt_refine_agent.main import (
    RTRefinementAgent,
)
from app.ai.agents.required_topic.rt_refine_agent.models import (
    RTRefinementInput,
)
from app.ai.agents.required_topic.rt_validator.main import (
    RTValidatorAgent,
)
from app.ai.agents.required_topic.regenerate_required_topic_agent.main import (
    RTRegenerationAgent,
)
from app.ai.agents.required_topic.regenerate_required_topic_agent.models import (
    RTRegenerationInput,
)
from app.ai.agents.required_topic.rt_validator.models import (
    RTValidationInput,
    RTValidationIssue,
)
from app.orchestrators.required_topics.models import (
    RequiredTopicsGenerationInput,
    RequiredTopicsGenerationResult,
    RequiredTopicsRegenerationInput,
    RequiredTopicsRegenerationResult,
)

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 2


def _issues_as_dicts(
    issues: list[RTValidationIssue],
) -> list[dict[str, Any]]:
    return [
        {
            "type": issue.type,
            "message": issue.message,
            "affected_topics": issue.affected_topics,
            "expected_action": issue.expected_action,
        }
        for issue in issues
    ]


def _format_learner_outcomes(
    *,
    experience_level: str,
    outcomes: list[str],
) -> str:
    lines = [f"Learner experience level: {experience_level.strip()}"]
    if outcomes:
        lines.append("Desired outcomes:")
        lines.extend(f"- {outcome.strip()}" for outcome in outcomes if outcome.strip())
    return "\n".join(lines)


def _to_regeneration_agent_input(
    input_data: RequiredTopicsRegenerationInput,
) -> RTRegenerationInput:
    return RTRegenerationInput(
        current_topics=input_data.current_topics,
        regeneration_prompt=input_data.regeneration_prompt,
    )


def _to_pipeline_metadata(
    input_data: RequiredTopicsGenerationInput,
) -> RTPipelineMetadata:
    return RTPipelineMetadata(
        course_title=input_data.course_title,
        course_description=input_data.course_scope,
        course_type=input_data.course_type,
        course_duration=input_data.course_duration,
        target_audience=input_data.target_audience,
        skill_level=input_data.difficulty_level,
        learner_outcomes=_format_learner_outcomes(
            experience_level=input_data.learner_experience_level,
            outcomes=input_data.learner_outcomes,
        ),
    )


class RequiredTopicsOrchestrator:
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

        self.generation_agent = RTGenerationAgent(
            kernel=self.kernel
        )
        self.validator_agent = RTValidatorAgent(
            kernel=self.kernel
        )
        self.refinement_agent = RTRefinementAgent(
            kernel=self.kernel
        )

    async def execute(
        self,
        input_data: RequiredTopicsGenerationInput,
    ) -> RequiredTopicsGenerationResult:
        metadata = _to_pipeline_metadata(input_data)
        logger.info(
            "[required_topics] Starting | title=%r",
            metadata.course_title,
        )

        # Step 1: Generate topics
        generation = await self.generation_agent.run(
            RTGenerationInput(metadata=metadata)
        )
        current_topics = generation.topics

        if not current_topics:
            logger.warning(
                "[required_topics] Generation returned empty topics"
            )
            return RequiredTopicsGenerationResult(
                topics=[],
                validation_passed=False,
                repair_attempts=0,
            )

        # Step 2: Initial validation
        validation = await self.validator_agent.run(
            RTValidationInput(
                topics=current_topics,
                metadata=metadata,
            )
        )

        if validation.passed:
            return RequiredTopicsGenerationResult(
                topics=current_topics,
                validation_passed=True,
                repair_attempts=0,
            )

        current_issues = validation.issues

        # Step 3: Repair loop
        for attempt in range(
            1,
            _MAX_REPAIR_ATTEMPTS + 1,
        ):
            logger.info(
                "[required_topics] Refinement attempt %s/%s | issues=%s",
                attempt,
                _MAX_REPAIR_ATTEMPTS,
                len(current_issues),
            )

            refinement = await self.refinement_agent.run(
                RTRefinementInput(
                    topics=current_topics,
                    issues=current_issues,
                    metadata=metadata,
                )
            )

            refined_topics = refinement.topics

            if not refined_topics:
                logger.warning(
                    "[required_topics] Refiner returned empty topics"
                )
                break

            validation = await self.validator_agent.run(
                RTValidationInput(
                    topics=refined_topics,
                    metadata=metadata,
                )
            )

            current_topics = refined_topics
            current_issues = validation.issues

            if validation.passed:
                return RequiredTopicsGenerationResult(
                    topics=current_topics,
                    validation_passed=True,
                    repair_attempts=attempt,
                )

        return RequiredTopicsGenerationResult(
            topics=current_topics,
            validation_passed=False,
            repair_attempts=_MAX_REPAIR_ATTEMPTS,
            final_issues=_issues_as_dicts(
                current_issues
            ),
        )

    async def regenerate_required_topics(
        self,
        input_data: RequiredTopicsRegenerationInput,
    ) -> RequiredTopicsRegenerationResult:
        """Revise existing topics from user feedback — no validation or repair."""
        agent_input = _to_regeneration_agent_input(input_data)
        logger.info(
            "[required_topics] Regenerating | topics=%d | prompt_length=%d",
            len(agent_input.current_topics),
            len(agent_input.regeneration_prompt.strip()),
        )
        result = await RTRegenerationAgent(kernel=self.kernel).run(agent_input)
        return RequiredTopicsRegenerationResult(topics=result.topics)
