"""Fold course_spec into the in-memory A1 state."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...nodes.base_node import BaseA1Node
from ...shared.models.state import A1State

logger = logging.getLogger(__name__)


class OutputWriter:
    """Finalizes A1's in-memory state; no disk I/O."""

    def persist_output(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        logger.info("[A1] Finalizing in-memory shared state...")
        a1_output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "complete",
            "course_spec": state["course_spec"],
            "inconsistencies": state.get("inconsistencies", []),
        }

        shared = dict(state["a0_shared_state"])
        shared["agent_outputs"] = {**shared.get("agent_outputs", {}), "A1": a1_output}
        shared["status"] = "A1_complete"

        return {**state, "a0_shared_state": shared, "status": "complete"}

    def failed_end(self, state: A1State) -> A1State:
        logger.error("[A1] FAILED: %s", state.get("error"))
        return {**state, "status": "failed"}

    def stopped_end(self, state: A1State) -> A1State:
        logger.warning("[A1] STOPPED: %s", state.get("error"))
        return {**state, "status": "stopped"}


def persist_output(state: A1State) -> A1State:
    return OutputWriter().persist_output(state)


def failed_end(state: A1State) -> A1State:
    return OutputWriter().failed_end(state)


def stopped_end(state: A1State) -> A1State:
    return OutputWriter().stopped_end(state)
