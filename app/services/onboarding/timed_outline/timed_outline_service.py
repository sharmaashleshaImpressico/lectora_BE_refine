"""Business logic for Timed Outline generation."""

from __future__ import annotations

import threading

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.regenerate_outline.main import (
    TORegenerationAgent,
)
from app.ai.agents.to_generation_pipeline.regenerate_outline.models import (
    TORegenerationInput,
)
from app.ai.agents.to_generation_pipeline.suggest_outline_structure.main import (
    OutlineStructureSuggestionAgent,
)
from app.ai.agents.to_generation_pipeline.suggest_outline_structure.models import (
    OutlineStructureSuggestionInput,
)
from app.orchestrators.topic_outline.models import TimedOutlineGenerationInput
from app.orchestrators.topic_outline.orchestrator import TopicOutlineOrchestrator
from app.schemas.onboarding.timed_outline.timed_outline import (
    GenerateTimedOutlineRequest,
    GenerateTimedOutlineResponse,
    RegenerateTimedOutlineRequest,
    RegenerateTimedOutlineResponse,
    SuggestOutlineStructureRequest,
    SuggestOutlineStructureResponse,
)


# Shared across requests (not per-instance): the generate-to endpoint is
# synchronous and runs in the request thread, so a cancel request needs a
# handle it can reach without a job ID.
_cancel_event = threading.Event()


class TimedOutlineService:
    """Maps API input to the TO orchestrator and returns the API response."""

    def __init__(self, kernel: Kernel) -> None:
        self._orchestrator = TopicOutlineOrchestrator(kernel)
        self._regeneration_agent = TORegenerationAgent(kernel)
        self._structure_suggestion_agent = OutlineStructureSuggestionAgent(kernel)

    def generate_timed_outline(
        self,
        request: GenerateTimedOutlineRequest,
    ) -> GenerateTimedOutlineResponse:
        """Run generation, validation, and repair via the feature orchestrator."""
        _cancel_event.clear()
        input_data = self._to_generation_input(request)
        result = self._orchestrator.generate_timed_outline(input_data, cancel_event=_cancel_event)
        return GenerateTimedOutlineResponse(
            timedOutline=result.outline,
            validationPassed=result.validation_passed,
            repairAttempts=result.repair_attempts,
            finalIssues=result.final_issues,
        )

    @staticmethod
    def cancel_generate_to() -> None:
        """Signal the in-flight generate-to request (if any) to stop."""
        _cancel_event.set()

    def regenerate_timed_outline(
        self,
        request: RegenerateTimedOutlineRequest,
    ) -> RegenerateTimedOutlineResponse:
        """Revise an existing timed outline in place using a free-text prompt."""
        result = self._regeneration_agent.run(
            TORegenerationInput(
                current_to=request.currentTo,
                revision_prompt=request.regenerationPrompt or "",
            )
        )
        return RegenerateTimedOutlineResponse(to=result.to)

    def suggest_outline_structure(
        self,
        request: SuggestOutlineStructureRequest,
    ) -> SuggestOutlineStructureResponse:
        """Suggest a preferred chapter count and lesson style for a course."""
        result = self._structure_suggestion_agent.run(
            OutlineStructureSuggestionInput(
                course_title=request.courseTitle or "",
                course_description=request.courseDescription or "",
                course_type=request.courseType or "",
                target_audience=request.targetAudience or "",
                skill_level=request.skillLevel or "",
                learning_objectives=request.learningObjectives or [],
            )
        )
        return SuggestOutlineStructureResponse(
            preferredChapters=result.preferred_chapters,
            lessonStyle=result.lesson_style,
            reasoning=result.reasoning,
        )

    @staticmethod
    def _to_generation_input(
        request: GenerateTimedOutlineRequest,
    ) -> TimedOutlineGenerationInput:
        """Convert the frontend payload into orchestrator input."""
        return TimedOutlineGenerationInput(
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
