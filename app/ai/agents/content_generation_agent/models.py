"""Native content-generation models (A2 generation, S2 validation).

Replaces the equivalent models that used to live in the missing
``lectora_backend.pipeline.models`` package.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class A2Stats(BaseModel):
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    total_words: int = 0


class A2Output(BaseModel):
    status: str
    run_id: str
    course_title: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    stats: A2Stats = Field(default_factory=A2Stats)
    course_description: str = ""
    course_conclusion: str = ""
    study_guide_docx: str | None = None
    generated_content_json: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class S2Status(str, Enum):
    pass_ = "pass"
    pass_with_warnings = "pass_with_warnings"
    blocked = "blocked"
    blocker = "blocker"


class ValidationIssue(BaseModel):
    field: str = "s2_validator"
    expected: str = ""
    found: Any = None
    severity: str = "warning"
    message: str = ""
    rule_source: str = "s2_validator"
    failure_reason: str | None = None
    remediation: str | None = None


class S2ValidationReport(BaseModel):
    status: S2Status
    run_id: str
    issues: list[ValidationIssue] = Field(default_factory=list)
    blockers: int = 0
    criticals: int = 0
    warnings: int = 0
    infos: int = 0
    report_path: str | None = None
    message: str | None = None
    lesson_title: str | None = None
    phase: str | None = None


__all__ = [
    "A2Stats",
    "A2Output",
    "S2Status",
    "ValidationIssue",
    "S2ValidationReport",
]
