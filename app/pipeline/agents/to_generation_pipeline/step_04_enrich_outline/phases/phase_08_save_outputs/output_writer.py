"""Persist course_spec to shared state and disk."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from ...nodes.base_node import BaseA1Node
from ...shared.models.state import A1State

logger = logging.getLogger(__name__)


class OutputWriter:
    """Writes A1 outputs and terminal status files."""

    def persist_output(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        logger.info("[A1] Persisting to shared state...")
        a1_output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "complete",
            "course_spec": state["course_spec"],
            "inconsistencies": state.get("inconsistencies", []),
        }

        with open(state["shared_state_path"]) as handle:
            shared = json.load(handle)
        shared["agent_outputs"]["A1"] = a1_output
        shared["status"] = "A1_complete"

        temporary_path = state["shared_state_path"] + ".tmp"
        with open(temporary_path, "w") as handle:
            json.dump(shared, handle, indent=2, default=str)
        os.replace(temporary_path, state["shared_state_path"])

        output_dir = Path(state["shared_state_path"]).expanduser().resolve().parent
        spec_path = output_dir / "course_spec.json"
        with open(spec_path, "w") as handle:
            json.dump(a1_output, handle, indent=2, default=str)

        logger.info("[A1] course_spec written -> %s", spec_path)
        return {**state, "status": "complete"}

    def failed_end(self, state: A1State) -> A1State:
        logger.error("[A1] FAILED: %s", state.get("error"))
        self._write_terminal(state, "failed")
        return {**state, "status": "failed"}

    def stopped_end(self, state: A1State) -> A1State:
        logger.warning("[A1] STOPPED: %s", state.get("error"))
        self._write_terminal(state, "stopped")
        return {**state, "status": "stopped"}

    @staticmethod
    def _write_terminal(state: A1State, label: str) -> None:
        output_dir = Path(state["shared_state_path"]).expanduser().resolve().parent
        path = output_dir / f"a1_{label}.json"
        with open(path, "w") as handle:
            json.dump(
                {
                    "status": label.upper(),
                    "reason": state.get("error"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                handle,
                indent=2,
            )


def persist_output(state: A1State) -> A1State:
    return OutputWriter().persist_output(state)


def failed_end(state: A1State) -> A1State:
    return OutputWriter().failed_end(state)


def stopped_end(state: A1State) -> A1State:
    return OutputWriter().stopped_end(state)
