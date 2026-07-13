"""Input/output models for the TO regeneration agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TORegenerationInput:
    """Input for revising an existing Training Outline in place."""

    current_to: dict[str, Any]
    revision_prompt: str


@dataclass
class TORegenerationOutput:
    to: dict[str, Any] = field(default_factory=dict)
