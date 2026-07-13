"""Business logic for Learning Objective generation and regeneration."""

from __future__ import annotations

from semantic_kernel import Kernel

from app.orchestrators.learning_objective.models import (
    LearningObjectiveGenerationInput,
    LearningObjectiveRegenerationInput,
)
from app.orchestrators.learning_objective.orchestrator import (
    LearningObjectiveOrchestrator,
)
from app.schemas.onboarding.learning_objective.learning_objective import (
    GenerateLearningObjectivesRequest,
    GenerateLearningObjectivesResponse,
    RegenerateLearningObjectivesRequest,
    RegenerateLearningObjectivesResponse,
)


class LearningObjectiveService:
    """Maps API input to the LO orchestrator and returns the API response."""

    def __init__(self, kernel: Kernel) -> None:
        self._orchestrator = LearningObjectiveOrchestrator(kernel)

    def generate_learning_objectives(
        self,
        request: GenerateLearningObjectivesRequest,
    ) -> GenerateLearningObjectivesResponse:
        """Run generation, validation, and repair via the feature orchestrator."""
        input_data = self._to_generation_input(request)
        result = self._orchestrator.generate_learning_objectives(input_data)
        return GenerateLearningObjectivesResponse(
            learningObjectives=result.objectives,
            validationPassed=result.validation_passed,
            repairAttempts=result.repair_attempts,
            finalIssues=result.final_issues,
        )

    def regenerate_learning_objectives(
        self,
        request: RegenerateLearningObjectivesRequest,
    ) -> RegenerateLearningObjectivesResponse:
        """Revise existing objectives from user feedback via the orchestrator."""
        input_data = self._to_regeneration_input(request)
        result = self._orchestrator.regenerate_learning_objectives(input_data)
        return RegenerateLearningObjectivesResponse(
            learningObjectives=result.objectives,
        )

    @staticmethod
    def _to_generation_input(
        request: GenerateLearningObjectivesRequest,
    ) -> LearningObjectiveGenerationInput:
        """Convert the frontend payload into orchestrator input."""
        return LearningObjectiveGenerationInput(
            source_materials=request.sourceMaterials,
            course_title=request.courseTitle,
            course_description=request.courseDescription,
            course_type=request.courseType,
            course_duration=request.courseDuration,
            skill_level=request.skillLevel,
            target_audience=request.targetAudience,
            required_topics=request.requiredTopics,
        )

    @staticmethod
    def _to_regeneration_input(
        request: RegenerateLearningObjectivesRequest,
    ) -> LearningObjectiveRegenerationInput:
        """Convert the regenerate request into orchestrator input."""
        return LearningObjectiveRegenerationInput(
            current_objectives=request.currentObjectives,
            regeneration_prompt=request.regenerationPrompt,
            course_title=request.courseTitle or "",
            course_type=request.courseType or "",
            course_duration=request.courseDuration or "",
            skill_level=request.skillLevel or "",
            target_audience=request.targetAudience or "",
        )
