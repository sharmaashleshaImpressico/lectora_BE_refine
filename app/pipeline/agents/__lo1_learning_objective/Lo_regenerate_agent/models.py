"""Input/output models for the LO regeneration agent."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LORegenerationInput:
    """Input for the LO regeneration agent.

    Unlike the generation agent, regeneration always starts from the
    user's existing objectives and applies targeted edits based on the
    user's prompt.  No full regeneration from course metadata happens here.
    """

    current_objectives: list[str]
    regeneration_prompt: str
    course_title: str = ""
    course_type: str = ""
    course_duration: str = ""
    target_audience: str = ""
    skill_level: str = ""


@dataclass
class LORegenerationOutput:
    objectives: list[str] = field(default_factory=list)
