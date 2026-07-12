"""Unit tests for ContentTransformationOrchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.orchestrators.content_transformation.models import ContentTransformationInput
from app.orchestrators.content_transformation.orchestrator import (
    ContentTransformationOrchestrator,
)
from app.schemas.ai.content_ai import ContentAiOperation


def test_orchestrator_wraps_traced_workflow_and_calls_agent_once():
    kernel = MagicMock()
    orchestrator = ContentTransformationOrchestrator(kernel)
    agent = MagicMock()
    agent.run.return_value = MagicMock(content="transformed", paragraphs=None)
    orchestrator._agent = agent

    with patch(
        "app.orchestrators.content_transformation.orchestrator.traced_workflow"
    ) as traced:
        traced.return_value.__enter__ = MagicMock(return_value=MagicMock())
        traced.return_value.__exit__ = MagicMock(return_value=False)

        result = orchestrator.transform(
            ContentTransformationInput(
                section_id="sec-9",
                operation=ContentAiOperation.simplify,
                content="Complex legal prose.",
                user_prompt=None,
                paragraphs=[{"id": "p1", "type": "text", "content": "Complex legal prose."}],
                preserve_structure=True,
            )
        )

    traced.assert_called_once()
    kwargs = traced.call_args.kwargs
    assert traced.call_args.args[0] == "content_transformation"
    assert "job_id" not in kwargs
    assert kwargs["metadata"]["operation"] == "simplify"
    assert kwargs["metadata"]["section_id"] == "sec-9"
    assert kwargs["metadata"]["preserve_structure"] is True
    assert "job_id" not in kwargs["metadata"]
    assert "job_id" not in kwargs["input_data"]

    agent.run.assert_called_once()
    agent_input = agent.run.call_args.args[0]
    assert agent_input.operation == ContentAiOperation.simplify
    assert agent_input.preserve_structure is True
    assert agent_input.paragraphs[0]["id"] == "p1"
    assert not hasattr(agent_input, "job_id")
    assert result.content == "transformed"
    assert result.section_id == "sec-9"


def test_orchestrator_does_not_invoke_content_generation_dag():
    """Ensure imports stay on the focused transform path (no pipeline runner)."""
    import app.orchestrators.content_transformation.orchestrator as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "ContentGenerationOrchestrator" not in source
    assert "CourseGenerationPipelineRunner" not in source
    assert "pipeline_runner" not in source
    assert "job_id" not in source
