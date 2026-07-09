"""Wizard/onboarding fields for dynamic TO system prompt construction."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceAnalysisPromptContext:
    source_name: str
    extract_hint: str = ""
    main_topics: tuple[str, ...] = ()
    recommended_course_use: str = ""
    recommended_depth: str = ""
    supports_learning_objectives: tuple[str, ...] = ()
    ignore_or_reduce: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToWizardPromptContext:
    """Structured onboarding preferences from POST /generate-to."""

    experience_level: str | None = None
    learner_outcomes: str | None = None
    audience_notes: str | None = None
    tone: str | None = None
    depth: str | None = None
    emphasis: str | None = None
    avoid: str | None = None
    include_case_studies: bool | None = None
    include_examples: bool | None = None
    include_knowledge_checks: bool | None = None
    lesson_style: str | None = None
    course_type_hint: str | None = None
    required_topics: tuple[str, ...] = ()
    source_analyses: tuple[SourceAnalysisPromptContext, ...] = ()

    def has_content(self) -> bool:
        return bool(
            self.experience_level
            or self.learner_outcomes
            or self.audience_notes
            or self.tone
            or self.depth
            or self.emphasis
            or self.avoid
            or self.include_case_studies is not None
            or self.include_examples is not None
            or self.include_knowledge_checks is not None
            or self.lesson_style
            or self.course_type_hint
            or self.required_topics
            or self.source_analyses
        )
