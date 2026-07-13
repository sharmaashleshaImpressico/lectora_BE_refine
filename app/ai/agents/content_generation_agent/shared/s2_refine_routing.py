"""Routing decisions for whether S2 validation results require content refinement."""

from __future__ import annotations

from typing import Any


def _count(report: Any, attr: str) -> int:
    return int(getattr(report, attr, 0) or 0)


def s2_has_blockers(report: Any) -> bool:
    return _count(report, "blockers") > 0


def s2_requires_content_refine(report: Any) -> bool:
    """True when the report has blockers or criticals that warrant a refine pass."""
    return _count(report, "blockers") > 0 or _count(report, "criticals") > 0


def s2_content_refine_routing_reason(report: Any) -> str:
    blockers = _count(report, "blockers")
    criticals = _count(report, "criticals")
    if blockers:
        return f"{blockers} blocker(s) — content refine required."
    if criticals:
        return f"{criticals} critical(s) — content refine required."
    return "No blockers or criticals — content refine not required."


__all__ = [
    "s2_has_blockers",
    "s2_requires_content_refine",
    "s2_content_refine_routing_reason",
]
