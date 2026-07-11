"""Top-level runner for the A1 enrichment LangGraph pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.models import (
    A0Result,
    A1Output,
    A1Status,
    CourseSpec,
    Inconsistency,
)

from ..shared.models.state import A1State
from .graph_builder import A1GraphBuilder


class A1PipelineRunner:
    """Invokes the A1 LangGraph and returns a typed A1Output."""

    def __init__(self, kernel: Kernel, graph_builder: A1GraphBuilder | None = None) -> None:
        self._kernel = kernel
        self._graph_builder = graph_builder or A1GraphBuilder(kernel=kernel)

    def run(
        self,
        a0_result: A0Result,
        docx_path: str,
        feedback: dict[str, Any] | None = None,
        *,
        prefer_a0_outline: bool = False,
    ) -> A1Output:
        app = self._graph_builder.build()
        initial: A1State = {
            "a0_shared_state": a0_result.shared_state,
            "docx_path": docx_path,
            "run_id": "",
            "a0_data": {},
            "raw_sections": [],
            "total_word_count": 0,
            "kc_count": 0,
            "image_map": {},
            "enrichment": {},
            "course_spec": {},
            "inconsistencies": [],
            "retry_count": 0,
            "status": "running",
            "error": None,
            "feedback": feedback,
            "prefer_a0_outline": prefer_a0_outline,
        }
        final: A1State = app.invoke(initial)
        return self._to_output(final)

    @staticmethod
    def _to_output(final: A1State) -> A1Output:
        if final["status"] == "complete":
            course_spec = CourseSpec.model_validate(final["course_spec"])
            inconsistencies = [
                Inconsistency.model_validate(item)
                for item in final.get("inconsistencies", [])
            ]
            return A1Output(
                status=A1Status.complete,
                course_spec=course_spec,
                inconsistencies=inconsistencies,
                retry_count=final.get("retry_count", 0),
                timestamp=datetime.now(timezone.utc),
            )

        return A1Output(
            status=A1Status.failed,
            error=final.get("error"),
            retry_count=final.get("retry_count", 0),
            timestamp=datetime.now(timezone.utc),
        )


def run(
    kernel: Kernel,
    a0_result: A0Result,
    docx_path: str,
    feedback: dict[str, Any] | None = None,
    *,
    prefer_a0_outline: bool = False,
) -> A1Output:
    """Run the A1 LangGraph and return a typed A1Output."""
    return A1PipelineRunner(kernel).run(
        a0_result,
        docx_path,
        feedback,
        prefer_a0_outline=prefer_a0_outline,
    )
