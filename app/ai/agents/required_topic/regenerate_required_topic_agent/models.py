"""Input/output models for the RT regeneration agent."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RTRegenerationInput:
    """Input for the RT regeneration agent.

    Regeneration always starts from the user's existing topics and applies
    targeted edits based on the user's prompt — no full regeneration from
    course metadata happens here.
    """

    current_topics: list[str]
    regeneration_prompt: str


@dataclass
class RTRegenerationOutput:
    topics: list[str] = field(default_factory=list)
