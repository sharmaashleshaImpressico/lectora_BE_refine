"""Orchestrates required topics generation workflow."""

from __future__ import annotations

import logging
from typing import Any

from semantic_kernel import Kernel

from app.pipeline.agents.required_topic.models import (
    RTPipelineMetadata,
    RTPipelineResult,
)
from app.pipeline.agents.required_topic.rt_generation.main import (
    RTGenerationAgent,
)
from app.pipeline.agents.required_topic.rt_generation.models import (
    RTGenerationInput,
)
from app.pipeline.agents.required_topic.rt_refine_agent.main import (
    RTRefinementAgent,
)
from app.pipeline.agents.required_topic.rt_refine_agent.models import (
    RTRefinementInput,
)
from app.pipeline.agents.required_topic.rt_validator.main import (
    RTValidatorAgent,
)
from app.pipeline.agents.required_topic.rt_validator.models import (
    RTValidationInput,
    RTValidationIssue,
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
        metadata: RTPipelineMetadata,
    ) -> RTPipelineResult:
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
            return RTPipelineResult(
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
            return RTPipelineResult(
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
                return RTPipelineResult(
                    topics=current_topics,
                    validation_passed=True,
                    repair_attempts=attempt,
                )

        return RTPipelineResult(
            topics=current_topics,
            validation_passed=False,
            repair_attempts=_MAX_REPAIR_ATTEMPTS,
            final_issues=_issues_as_dicts(
                current_issues
            ),
        )
