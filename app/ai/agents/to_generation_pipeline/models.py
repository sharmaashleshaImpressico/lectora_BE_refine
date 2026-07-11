"""Native pydantic models for the Timed-Outline (TO) generation pipeline.

This module replaces the missing ``lectora_backend.pipeline.models`` package.
Field shapes were reverse-engineered from every call site that constructs or
reads these models across ``step_01_parse_and_generate_outline`` (A0),
``step_02_validate_outline`` (S1), ``step_03_repair_outline`` (S1 refine), and
``step_04_enrich_outline`` (A1). Kept dependency-free (pydantic only, which is
already a project dependency) and permissive (``extra="allow"``) where the
original payloads are known to carry additional passthrough keys.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# A0 — request synthesis models
# ─────────────────────────────────────────────────────────────────────────────


class ProvenanceEntry(BaseModel):
    """Tracks where a resolved request_spec field value came from."""

    value: Any = None
    source: str = "unresolved"


class CourseMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = ""
    course_id: str | None = None
    audience: str | None = None
    course_type: str | None = None
    category: str | None = None
    topic: str | None = None


class RuleClassification(BaseModel):
    model_config = ConfigDict(extra="allow")

    family: str = ""
    family_key: str = ""
    rule_pack_id: str | None = None
    rule_pack_version: str | None = None
    llm_confidence: float | None = None
    llm_reasoning: str | None = None


class RequestSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    timestamp: datetime
    course_metadata: CourseMetadata
    rule_classification: RuleClassification


class ExtractedInputs(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = ""
    course_id: str | None = None
    learning_objectives: list[str] = Field(default_factory=list)
    content_sample: str = ""
    total_doc_word_count: int = 0
    to_outline_total_word_count: int = 0
    heading_tree: list[dict[str, Any]] = Field(default_factory=list)
    heading_map: list[list[Any]] = Field(default_factory=list)
    toc_entries: list[Any] = Field(default_factory=list)
    toc_section_contents: list[Any] = Field(default_factory=list)
    total_paragraphs: int = 0
    paragraphs_by_source: dict[str, int] = Field(default_factory=dict)


class LLMClassification(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule_family: str | None = None
    confidence: float | None = None
    audience: str | None = None
    topic: str | None = None
    course_type: str | None = None
    category: str | None = None
    reasoning: str | None = None


class AgentOutputSlots(BaseModel):
    """Per-agent output slots persisted onto shared_state (A1, ... future agents)."""

    model_config = ConfigDict(extra="allow")

    A1: dict[str, Any] | None = None


class SharedState(BaseModel):
    """In-memory / on-disk pipeline state handed between A0 -> S1 -> S1-refine -> A1."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str = "a0_completed"
    request_spec: RequestSpec | None = None
    provenance_log: dict[str, ProvenanceEntry] = Field(default_factory=dict)
    source_document: str = ""
    extracted_inputs: ExtractedInputs | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)
    llm_classification: LLMClassification | None = None
    llm_to_outline_classification: dict[str, Any] = Field(default_factory=dict)
    agent_outputs: AgentOutputSlots = Field(default_factory=AgentOutputSlots)


class A0Result(BaseModel):
    """Final return value of ``A0RequestSynthesizer.run()``."""

    model_config = ConfigDict(extra="allow")

    request_spec: RequestSpec
    provenance_log: dict[str, ProvenanceEntry] = Field(default_factory=dict)
    shared_state: dict[str, Any] = Field(default_factory=dict)
    llm_to_outline: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# S1 — outline validation models
# ─────────────────────────────────────────────────────────────────────────────


class IssueSeverity(str, Enum):
    blocker = "blocker"
    warning = "warning"
    info = "info"


class ValidationIssue(BaseModel):
    """A single S1 validation finding (deterministic or AI-sourced)."""

    model_config = ConfigDict(extra="allow")

    field: str = "s1_validator"
    expected: Any = "Requirement satisfied"
    found: Any = "Not satisfied"
    severity: IssueSeverity = IssueSeverity.warning
    message: str = ""
    rule_source: str = ""
    remediation: str | None = None


class S1Status(str, Enum):
    blocked = "blocked"
    pass_with_warnings = "pass_with_warnings"
    pass_ = "pass"


class S1ValidationReport(BaseModel):
    """Aggregated result of an S1 validation run."""

    model_config = ConfigDict(extra="allow")

    status: S1Status
    run_id: str = "unknown"
    issues: list[ValidationIssue] = Field(default_factory=list)
    blockers: int = 0
    warnings: int = 0
    infos: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# A1 — outline enrichment / course-spec models
# ─────────────────────────────────────────────────────────────────────────────


class Inconsistency(BaseModel):
    """A single structural inconsistency flagged in the assembled course_spec."""

    model_config = ConfigDict(extra="allow")

    field: str = ""
    expected: Any = None
    found: Any = None
    severity: str = "info"
    message: str = ""
    rule_source: str = ""


class CourseSpec(BaseModel):
    """Final assembled course specification produced by A1 (see course_spec_builder)."""

    model_config = ConfigDict(extra="allow")

    run_id: str = ""
    course_id: str | None = None
    course_title: str | None = None
    extracted_inputs: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)


class A1Status(str, Enum):
    complete = "complete"
    failed = "failed"
    running = "running"
    stopped = "stopped"


class A1Output(BaseModel):
    """Typed return value of ``A1PipelineRunner.run()``."""

    model_config = ConfigDict(extra="allow")

    status: A1Status
    course_spec: CourseSpec | None = None
    inconsistencies: list[Inconsistency] = Field(default_factory=list)
    retry_count: int = 0
    timestamp: datetime | None = None
    error: str | None = None


__all__ = [
    "A0Result",
    "A1Output",
    "A1Status",
    "AgentOutputSlots",
    "CourseMetadata",
    "CourseSpec",
    "ExtractedInputs",
    "Inconsistency",
    "IssueSeverity",
    "LLMClassification",
    "ProvenanceEntry",
    "RequestSpec",
    "RuleClassification",
    "S1Status",
    "S1ValidationReport",
    "SharedState",
    "ValidationIssue",
]
