"""Input/output models for the outline structure suggestion agent."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OutlineStructureSuggestionInput:
    """Input for suggesting a preferred chapter count and lesson style."""

    course_title: str = ""
    course_description: str = ""
    course_type: str = ""
    target_audience: str = ""
    skill_level: str = ""
    learning_objectives: list[str] = field(default_factory=list)


@dataclass
class OutlineStructureSuggestionOutput:
    preferred_chapters: int
    lesson_style: str
    reasoning: str
