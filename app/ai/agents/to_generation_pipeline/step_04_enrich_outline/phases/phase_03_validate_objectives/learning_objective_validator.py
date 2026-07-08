"""Learning-objective validation for the A1 pipeline."""

from __future__ import annotations

import logging

from ...nodes.base_node import BaseA1Node
from ...shared.models.state import A1State

logger = logging.getLogger(__name__)


class LearningObjectiveValidator(BaseA1Node):
    """Validates that learning objectives are present before enrichment."""

    def execute(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        logger.info("[A1] Validating learning objectives...")
        learning_objectives = state["a0_data"].get("extracted_inputs", {}).get("learning_objectives", [])

        if not learning_objectives:
            sections = state.get("raw_sections", [])
            if sections:
                logger.warning(
                    "[A1] No learning objectives found — continuing without LOs (sections present)."
                )
                return {
                    **state,
                    "status": "complete",
                    "error": "Missing LOs — proceeding without them",
                }

            logger.error("[A1] CRITICAL — no learning objectives and no sections. Stopping pipeline.")
            return {
                **state,
                "status": "stopped",
                "error": "No sections and no LOs — cannot proceed",
            }

        logger.info("[A1] %s learning objectives confirmed.", len(learning_objectives))
        return state


def validate_los(state: A1State) -> A1State:
    return LearningObjectiveValidator().execute(state)
