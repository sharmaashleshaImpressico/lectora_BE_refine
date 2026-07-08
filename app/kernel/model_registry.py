"""
Model Registry — centralised source of truth for per-agent LLM deployments.

Agents call `get_deployment(agent_id)` at *call time* so any override written
via the settings API is picked up by the next generation run without a restart.

Overrides are persisted to ``model_overrides.json`` next to this file.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_OVERRIDES_FILE = Path(__file__).parent / "model_overrides.json"
_lock = threading.Lock()

DEFAULTS: dict[str, str] = {
    "A0": "o3",
    "A0_TO": "gpt-5.4-mini",
    "A1": "gpt-5.4-mini",
    "A2": "gpt-5.4-mini",
}

AVAILABLE_MODELS: list[dict] = [

    {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini", "provider": "Azure OpenAI", "tier": "efficient"},
]

AGENT_META: dict[str, dict] = {
    "A0": {
        "name": "Request Synthesizer — Classify",
        "role": "Classifies rule family from course title, objectives, and content sample",
        "pipeline_step": 1,
        "supports_temperature": False,
    },
    "A0_TO": {
        "name": "Request Synthesizer — TO Generation",
        "role": "Generates Timed Outline from DOCX + PDF extracted text",
        "pipeline_step": 1,
        "supports_temperature": False,
    },
    "A1": {
        "name": "Outline Interpreter",
        "role": "Parses document structure, enriches sections, builds course spec",
        "pipeline_step": 2,
        "supports_temperature": True,
    },
    "A2": {
        "name": "Content Generator",
        "role": "Generates course content per lesson, descriptions, and conclusions",
        "pipeline_step": 3,
        "supports_temperature": True,
    },
}


def _read_overrides() -> dict[str, str]:
    with _lock:
        return _read_overrides_unlocked()


def _read_overrides_unlocked() -> dict[str, str]:
    if not _OVERRIDES_FILE.exists():
        return {}
    try:
        return json.loads(_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_overrides(overrides: dict[str, str]) -> None:
    with _lock:
        _write_overrides_unlocked(overrides)


def _write_overrides_unlocked(overrides: dict[str, str]) -> None:
    _OVERRIDES_FILE.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_deployment(agent_id: str) -> str:
    overrides = _read_overrides()
    return overrides.get(agent_id) or DEFAULTS.get(agent_id, "gpt-5.4-mini")


def get_to_file_deployment() -> str:
    explicit = os.environ.get("A0_TO_FILE_DEPLOYMENT", "").strip()
    if explicit:
        return explicit
    return get_deployment("A0_TO")


def get_all_configs() -> list[dict]:
    overrides = _read_overrides()
    return [
        {
            "agent_id": agent_id,
            "name": meta["name"],
            "role": meta["role"],
            "pipeline_step": meta["pipeline_step"],
            "default_deployment": DEFAULTS[agent_id],
            "current_deployment": overrides.get(agent_id) or DEFAULTS[agent_id],
            "is_overridden": agent_id in overrides,
            "supports_temperature": meta["supports_temperature"],
        }
        for agent_id, meta in AGENT_META.items()
    ]


def set_deployment(agent_id: str, deployment: str) -> None:
    with _lock:
        overrides = _read_overrides_unlocked()
        overrides[agent_id] = deployment
        _write_overrides_unlocked(overrides)


def reset_deployment(agent_id: str) -> None:
    with _lock:
        overrides = _read_overrides_unlocked()
        overrides.pop(agent_id, None)
        _write_overrides_unlocked(overrides)


def reset_all_deployments() -> None:
    _write_overrides({})
