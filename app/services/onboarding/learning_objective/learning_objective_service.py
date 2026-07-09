"""Business logic for Learning Objective generation."""

from __future__ import annotations

from semantic_kernel import Kernel

from app.ai.agents.learning_objective_agent.models import CourseMetadata
from app.orchestrators.learning_objective.orchestrator import (
    LearningObjectiveOrchestrator,
)
from app.schemas.onboarding.learning_objective.learning_objective import (
    GenerateLearningObjectivesRequest,
    GenerateLearningObjectivesResponse,
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
        metadata = self._to_course_metadata(request)
        result = self._orchestrator.execute(metadata)
        return GenerateLearningObjectivesResponse(
            learningObjectives=result.objectives,
            validationPassed=result.validation_passed,
            repairAttempts=result.repair_attempts,
            finalIssues=result.final_issues,
        )

    @staticmethod
    def _to_course_metadata(
        request: GenerateLearningObjectivesRequest,
    ) -> CourseMetadata:
        """Convert the frontend payload into orchestrator input."""
        return CourseMetadata(
            course_title=request.courseTitle,
            course_description=request.courseDescription,
            course_type=request.courseType,
            course_duration=request.courseDuration,
            skill_level=request.skillLevel,
            target_audience=request.targetAudience,
            required_topics=request.requiredTopics,
            source_analyses=[
                {"source_name": path} for path in request.sourceMaterials
            ],  # paths only; full source analysis is out of scope for this API
        )
