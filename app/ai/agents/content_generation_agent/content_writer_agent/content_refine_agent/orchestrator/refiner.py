from __future__ import annotations

import logging
import time
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.content_generation_agent.models import A2Output, S2ValidationReport
from app.ai.shared_llm_config.tracer import write_span

from ..utils.content_refiner import refine_sections as _refine_sections

logger = logging.getLogger(__name__)


def _get_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def refine_sections(
    kernel: Kernel,
    *,
    a2_output: A2Output,
    s2_report: S2ValidationReport | dict[str, Any],
    rule_pack: dict[str, Any],
    context: dict[str, Any],
    lesson_title: str | None = None,
) -> A2Output:
    """Refine existing generated content based on S2 validation feedback."""
    started_at = time.perf_counter()
    issue_count = len(_get_value(s2_report, "issues", []) or [])
    logger.info(
        "[CONTENT_REFINE] Refining existing content for %s validation issue(s).",
        issue_count,
    )

    result: A2Output | None = None
    error: str | None = None
    try:
        result = _refine_sections(
            kernel,
            a2_output=a2_output,
            s2_report=s2_report,
            rule_pack=rule_pack,
            context=context,
            lesson_title=lesson_title,
        )
        return result
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        write_span(
            name="Content Refine | apply validation feedback",
            agent="CONTENT_REFINE",
            latency_ms=(time.perf_counter() - started_at) * 1000,
            input_data={
                "issues_count": issue_count,
                "course_difficulty": context.get("course_difficulty"),
            },
            output_data={
                "status": getattr(result, "status", None),
                "generated_sections": len(getattr(result, "sections", []) or []),
                "total_words": getattr(getattr(result, "stats", None), "total_words", None),
            }
            if result is not None
            else {},
            error=error,
        )


__all__ = ["refine_sections"]
