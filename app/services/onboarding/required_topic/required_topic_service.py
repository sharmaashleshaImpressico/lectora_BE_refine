"""Business logic for Required Topics generation and regeneration."""

from __future__ import annotations

from semantic_kernel import Kernel

from app.orchestrators.required_topics.models import (
    RequiredTopicsGenerationInput,
    RequiredTopicsRegenerationInput,
)
from app.orchestrators.required_topics.orchestrator import RequiredTopicsOrchestrator
from app.schemas.onboarding.required_topic.required_topic import (
    GenerateRequiredTopicsRequest,
    GenerateRequiredTopicsResponse,
    RegenerateRequiredTopicsRequest,
    RegenerateRequiredTopicsResponse,
)


class RequiredTopicService:
    """Maps API input to the RT orchestrator and returns the API response."""

    def __init__(self, kernel: Kernel) -> None:
        self._orchestrator = RequiredTopicsOrchestrator(kernel)

    async def generate_required_topics(
        self,
        request: GenerateRequiredTopicsRequest,
    ) -> GenerateRequiredTopicsResponse:
        """Run generation, validation, and repair via the feature orchestrator."""
        input_data = self._to_generation_input(request)
        result = await self._orchestrator.execute(input_data)
        return GenerateRequiredTopicsResponse(
            requiredTopics=result.topics,
            validationPassed=result.validation_passed,
            repairAttempts=result.repair_attempts,
            finalIssues=result.final_issues,
        )

    async def regenerate_required_topics(
        self,
        request: RegenerateRequiredTopicsRequest,
    ) -> RegenerateRequiredTopicsResponse:
        """Revise existing topics from user feedback via the orchestrator."""
        input_data = self._to_regeneration_input(request)
        result = await self._orchestrator.regenerate_required_topics(input_data)
        return RegenerateRequiredTopicsResponse(
            requiredTopics=result.topics,
        )

    @staticmethod
    def _to_generation_input(
        request: GenerateRequiredTopicsRequest,
    ) -> RequiredTopicsGenerationInput:
        """Convert the frontend payload into orchestrator input."""
        return RequiredTopicsGenerationInput(
            course_title=request.courseTitle,
            course_scope=request.courseDescription,
            course_type=request.courseType,
            course_duration=request.courseDuration,
            difficulty_level=request.skillLevel,
            target_audience=request.targetAudience,
            learner_experience_level=request.skillLevel,
            learner_outcomes=[request.learnerOutcomes],
        )

    @staticmethod
    def _to_regeneration_input(
        request: RegenerateRequiredTopicsRequest,
    ) -> RequiredTopicsRegenerationInput:
        """Convert the regenerate request into orchestrator input."""
        return RequiredTopicsRegenerationInput(
            current_topics=request.currentTopics,
            regeneration_prompt=request.regenerationPrompt,
        )
