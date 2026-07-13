"""Thin orchestrator for single-agent Course Editor content transformation."""

from __future__ import annotations

import logging
import uuid

from semantic_kernel import Kernel

from app.ai.agents.content_transformation_agent import (
    ContentTransformationAgent,
    ContentTransformationAgentInput,
)
from app.orchestrators.content_transformation.models import (
    ContentTransformationInput,
    ContentTransformationResult,
)
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)


class ContentTransformationOrchestrator:
    """Dispatch one ContentTransformationAgent run under a traced workflow.

    Not part of the course-generation DAG.
    """

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel
        self._agent = ContentTransformationAgent(kernel)

    def transform(
        self,
        input_data: ContentTransformationInput,
    ) -> ContentTransformationResult:
        run_id = f"content-transform-{uuid.uuid4().hex[:8]}"
        with traced_workflow(
            "content_transformation",
            run_id=run_id,
            doc_name=f"section-{input_data.section_id}",
            metadata={
                "operation": input_data.operation.value,
                "section_id": input_data.section_id,
                "preserve_structure": input_data.preserve_structure,
            },
            input_data={
                "operation": input_data.operation.value,
                "section_id": input_data.section_id,
                "content_chars": len(input_data.content or ""),
                "paragraph_count": len(input_data.paragraphs or []),
                "preserve_structure": input_data.preserve_structure,
                "has_user_prompt": bool((input_data.user_prompt or "").strip()),
            },
        ):
            logger.info(
                "[content_transformation] Starting | section_id=%s operation=%s "
                "preserve_structure=%s paragraphs=%d",
                input_data.section_id,
                input_data.operation.value,
                input_data.preserve_structure,
                len(input_data.paragraphs or []),
            )
            agent_result = self._agent.run(
                ContentTransformationAgentInput(
                    operation=input_data.operation,
                    content=input_data.content,
                    user_prompt=input_data.user_prompt,
                    paragraphs=list(input_data.paragraphs or []),
                    preserve_structure=input_data.preserve_structure,
                )
            )
            return ContentTransformationResult(
                section_id=input_data.section_id,
                operation=input_data.operation,
                content=agent_result.content,
                paragraphs=agent_result.paragraphs,
            )


__all__ = ["ContentTransformationOrchestrator"]
