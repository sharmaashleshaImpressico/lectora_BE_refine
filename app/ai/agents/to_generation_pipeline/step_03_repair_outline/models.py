"""Input/output models for S1 TO refinement."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class S1RefinementIssue:
    field: str
    message: str
    severity: str = "warning"
    expected: str = ""
    found: str = ""
    rule_source: str = ""
    remediation: str | None = None


@dataclass
class S1RefinementInput:
    current_outline: dict[str, Any]
    issues: list[S1RefinementIssue]
    course_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class S1RefinementOutput:
    outline: dict[str, Any] = field(default_factory=dict)
    applied: bool = False
