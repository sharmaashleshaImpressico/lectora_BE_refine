"""Base class for A1 LangGraph node handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..shared.models.state import A1State


class BaseA1Node(ABC):
    """Common interface for pipeline steps that read and return A1State."""

    @abstractmethod
    def execute(self, state: A1State) -> A1State:
        """Run the node logic and return the updated state."""

    def __call__(self, state: A1State) -> A1State:
        return self.execute(state)
