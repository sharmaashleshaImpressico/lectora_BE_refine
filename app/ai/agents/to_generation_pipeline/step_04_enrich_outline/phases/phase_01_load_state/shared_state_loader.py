"""Step 01 — Load in-memory shared state produced by A0."""

from __future__ import annotations

import logging

from ...nodes.base_node import BaseA1Node
from ..phase_02_parse_document.llm_outline_parser import LlmOutlineSectionParser
from ...shared.models.state import A1State
from app.ai.shared_utils.learning_objectives import resolve_learning_objectives

logger = logging.getLogger(__name__)


class SharedStateLoader(BaseA1Node):
    """Reads A0's in-memory shared state and prepares it for downstream A1 steps."""

    def __init__(self, outline_parser: LlmOutlineSectionParser | None = None) -> None:
        self._outline_parser = outline_parser or LlmOutlineSectionParser()

    def execute(self, state: A1State) -> A1State:
        logger.info("[A1] Loading A0 shared state...")
        try:
            data = dict(state["a0_shared_state"])

            if state.get("prefer_a0_outline"):
                data = self._outline_parser.sync_extracted_inputs(data)
                logger.info("[A1] Generate-TO mode — synced title/LOs from A0 llm_to_outline.")
            else:
                data = self._backfill_learning_objectives(data)

            return {
                **state,
                "run_id": data["run_id"],
                "a0_data": data,
                "status": "running",
                "error": None,
            }
        except Exception as exc:
            return {**state, "status": "failed", "error": f"load_shared_state: {exc}"}

    @staticmethod
    def _backfill_learning_objectives(data: dict) -> dict:
        resolved_los = resolve_learning_objectives(data)
        if resolved_los and not (data.get("extracted_inputs", {}) or {}).get("learning_objectives"):
            extracted_inputs = dict(data.get("extracted_inputs", {}) or {})
            extracted_inputs["learning_objectives"] = resolved_los
            data = {**data, "extracted_inputs": extracted_inputs}
            logger.info(
                "[A1] Backfilled %s learning objective(s) from llm_to_outline for PDF-only source.",
                len(resolved_los),
            )
        return data


def load_shared_state(state: A1State) -> A1State:
    return SharedStateLoader().execute(state)
