"""Detect structural inconsistencies in course_spec."""

from __future__ import annotations

import logging

from ...nodes.base_node import BaseA1Node
from ...shared.models.state import A1State

logger = logging.getLogger(__name__)


class InconsistencyDetector(BaseA1Node):
    """Checks course_spec for structural inconsistencies."""

    def execute(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        logger.info("[A1] Checking for inconsistencies...")
        issues = self._detect_issues(state)

        if issues:
            for issue in issues:
                logger.info(
                    "  [%s] %s: %s",
                    issue["severity"].upper(),
                    issue["field"],
                    issue["message"],
                )
        else:
            logger.info("[A1] No inconsistencies detected.")

        return {**state, "inconsistencies": issues}

    def _detect_issues(self, state: A1State) -> list[dict]:
        issues: list[dict] = []
        course_spec = state["course_spec"]
        learning_objectives = state["a0_data"].get("extracted_inputs", {}).get("learning_objectives", [])

        mapped_indices = set()
        for section in course_spec.get("sections", []):
            mapped_indices.update(section.get("maps_to_objectives", []))

        unmapped = [index for index in range(len(learning_objectives)) if index not in mapped_indices]
        if unmapped:
            issues.append({
                "field": "learning_objectives_coverage",
                "expected": f"all {len(learning_objectives)} LOs mapped",
                "found": f"LO indices {unmapped} unmapped",
                "severity": "info",
                "message": (
                    f"LO(s) {[index + 1 for index in unmapped]} have no explicit section mapping. "
                    "May need A2 to address coverage gaps."
                ),
            })

        return issues


def detect_inconsistencies(state: A1State) -> A1State:
    return InconsistencyDetector().execute(state)
