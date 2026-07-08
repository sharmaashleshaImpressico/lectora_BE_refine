"""Conditional routing rules for the A1 LangGraph workflow."""

from __future__ import annotations

from ..shared.models.state import A1State


class A1GraphRouter:
    """Decides the next graph node based on the current pipeline state."""

    @staticmethod
    def after_load(state: A1State) -> str:
        return "failed_end" if state["status"] == "failed" else "parse_document"

    @staticmethod
    def after_parse(state: A1State) -> str:
        if state["status"] == "failed":
            return "failed_end"
        if state.get("error") and state.get("retry_count", 0) <= 1:
            return "parse_document"
        return "validate_los"

    @staticmethod
    def after_validate(state: A1State) -> str:
        # Image mapper disabled — proceed directly to section enrichment.
        return "stopped_end" if state["status"] == "stopped" else "enrich_with_llm"

    @staticmethod
    def after_build(state: A1State) -> str:
        return "failed_end" if state["status"] == "failed" else "detect_inconsistencies"
