"""LO Pipeline — delegates repair-loop sequencing to the central orchestrator."""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

from app.core.orchestration.central import get_central_orchestrator
from app.core.orchestration.central.types import AgentId
from app.pipeline.agents.__lo1_learning_objective.Lo_generation.models import (
    LOGenerationInput,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_refine_agent.models import (
    LORefinementInput,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_validator.models import (
    LOValidationInput,
    LOValidationIssue,
)
from app.pipeline.agents.__lo1_learning_objective.models import (
    CourseMetadata,
    LOPipelineResult,
)
from app.pipeline.shared_llm_config.tracer import (
    flush_langfuse,
    set_run_context,
    span_context,
)

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 2


def _issues_as_dicts(issues: list[LOValidationIssue]) -> list[dict]:
    return [
        {
            "type": issue.type,
            "message": issue.message,
            "affected_objectives": issue.affected_objectives,
            "expected_action": issue.expected_action,
        }
        for issue in issues
    ]


def _execute(metadata: CourseMetadata) -> LOPipelineResult:
    orchestrator = get_central_orchestrator()
    registry = orchestrator.registry

    logger.info(
        "[lo_pipeline] Starting | title=%r | regen=%s",
        metadata.course_title,
        bool(metadata.regeneration_prompt),
    )

    result = orchestrator.run_repair_pipeline(
        metadata,
        generate=lambda m: registry.invoke(
            AgentId.LO_GENERATION, LOGenerationInput(metadata=m)
        ),
        validate=lambda objectives, m: registry.invoke(
            AgentId.LO_VALIDATOR, LOValidationInput(objectives=objectives, metadata=m)
        ),
        refine=lambda objectives, issues, m: registry.invoke(
            AgentId.LO_REFINEMENT,
            LORefinementInput(objectives=objectives, issues=issues, metadata=m),
        ),
        extract_payload=lambda out: out.objectives,
        validation_passed=lambda val: val.passed,
        extract_issues=lambda val: val.issues,
        issues_as_dicts=_issues_as_dicts,
        max_repair_attempts=_MAX_REPAIR_ATTEMPTS,
        pipeline_name="lo_pipeline",
    )

    return LOPipelineResult(
        objectives=result.payload,
        validation_passed=result.validation_passed,
        repair_attempts=result.repair_attempts,
        final_issues=result.final_issues,
    )


def _build_input_data(metadata: CourseMetadata) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "course_title": metadata.course_title or None,
        "course_type": metadata.course_type or None,
        "target_audience": metadata.target_audience or None,
        "skill_level": metadata.skill_level or None,
        "required_topics_count": len(metadata.required_topics),
        "source_analyses_count": len(metadata.source_analyses),
        "is_regeneration": bool(metadata.regeneration_prompt),
        "current_objectives_count": len(metadata.current_objectives),
    }
    return {k: v for k, v in raw.items() if v not in (None, "")}


def run_lo_pipeline(metadata: CourseMetadata) -> LOPipelineResult:
    """Run the full LO generation → validation → repair pipeline synchronously."""
    run_id = f"lo-pipeline-{_uuid.uuid4().hex[:8]}"
    set_run_context(run_id, metadata.course_title or "lo-pipeline")

    try:
        with span_context(
            name="LO Pipeline | generate → validate → refine",
            agent="LO_PIPELINE",
            input_data=_build_input_data(metadata),
        ):
            return _execute(metadata)
    finally:
        flush_langfuse()
