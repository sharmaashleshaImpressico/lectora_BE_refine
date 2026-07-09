"""Business logic for Timed Outline generation."""

from __future__ import annotations

from semantic_kernel import Kernel

from app.orchestrators.topic_outline.models import TimedOutlineMetadata
from app.orchestrators.topic_outline.orchestrator import TopicOutlineOrchestrator
from app.schemas.onboarding.timed_outline.timed_outline import (
    GenerateTimedOutlineRequest,
    GenerateTimedOutlineResponse,
)


class TimedOutlineService:
    """Maps API input to the TO orchestrator and returns the API response."""

    def __init__(self, kernel: Kernel) -> None:
        self._orchestrator = TopicOutlineOrchestrator(kernel)

    def generate_timed_outline(
        self,
        request: GenerateTimedOutlineRequest,
    ) -> GenerateTimedOutlineResponse:
        """Run generation, validation, and repair via the feature orchestrator."""
        metadata = self._to_timed_outline_metadata(request)
        result = self._orchestrator.generate_timed_outline(metadata)
        return GenerateTimedOutlineResponse(
            timedOutline=result.outline,
            validationPassed=result.validation_passed,
            repairAttempts=result.repair_attempts,
            finalIssues=result.final_issues,
        )

    @staticmethod
    def _to_timed_outline_metadata(
        request: GenerateTimedOutlineRequest,
    ) -> TimedOutlineMetadata:
        """Convert the frontend payload into orchestrator input."""
        return TimedOutlineMetadata(
            blob_paths=request.blobPaths,
            course_title=request.courseTitle,
            course_description=request.courseDescription,
            audience=request.audience,
            learning_objectives=request.learningObjectives,
            required_topics=request.requiredTopics,
            duration_hours=request.durationHours,
            calculated_word_count=request.calculatedWordCount,
            difficulty=(request.difficultyLevel or request.difficulty or "intermediate").strip().lower(),
            course_topic=request.courseTopic,
            course_type_hint=request.courseTypeHint,
            rule_family=request.ruleFamily,
            experience_level=request.experienceLevel,
            learner_outcomes=request.learnerOutcomes,
            tone=request.tone,
            depth=request.depth,
            emphasis=request.emphasis,
            avoid=request.avoid,
            include_case_studies=request.includeCaseStudies,
            include_examples=request.includeExamples,
            include_knowledge_checks=request.includeKnowledgeChecks,
            preferred_chapters=request.preferredChapters,
            lesson_style=request.lessonStyle,
        )
