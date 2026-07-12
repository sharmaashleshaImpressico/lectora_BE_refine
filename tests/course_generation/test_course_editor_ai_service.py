"""Unit tests for CourseEditorAiService."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.orchestrators.content_transformation.models import (
    ContentTransformationInput,
    ContentTransformationResult,
)
from app.schemas.ai.content_ai import ContentAiOperation, CourseEditorAiRequest
from app.services.ai.course_editor_ai_service import CourseEditorAiService


def _service() -> tuple[CourseEditorAiService, MagicMock]:
    kernel = MagicMock()
    orchestrator = MagicMock()
    svc = CourseEditorAiService(kernel, orchestrator=orchestrator)
    return svc, orchestrator


def test_transform_forwards_frontend_content_without_job_id():
    svc, orchestrator = _service()
    orchestrator.transform.return_value = ContentTransformationResult(
        section_id="sec-1",
        operation=ContentAiOperation.expand,
        content="Expanded body",
    )

    request = CourseEditorAiRequest(
        sectionId="sec-1",
        operation="expand",
        content="Exact unsaved frontend HTML <p>x</p>",
        userPrompt="add one example",
    )
    response = svc.transform(request)

    orchestrator.transform.assert_called_once()
    orch_input: ContentTransformationInput = orchestrator.transform.call_args.args[0]
    assert not hasattr(orch_input, "job_id")
    assert orch_input.section_id == "sec-1"
    assert orch_input.operation == ContentAiOperation.expand
    assert orch_input.content == "Exact unsaved frontend HTML <p>x</p>"
    assert orch_input.user_prompt == "add one example"
    assert orch_input.preserve_structure is False
    assert response.content == "Expanded body"
    assert response.paragraphs is None


def test_transform_forwards_paragraphs_when_preserve_structure():
    svc, orchestrator = _service()
    paragraphs = [
        {"id": "p1", "type": "text", "content": "Hello"},
        {
            "id": "p2",
            "type": "important_callout",
            "label": "Important",
            "content": "Note",
        },
    ]
    orchestrator.transform.return_value = ContentTransformationResult(
        section_id="sec-1",
        operation=ContentAiOperation.summarize,
        content="Hello\n\nNote",
        paragraphs=[
            {"id": "p1", "type": "text", "content": "Hi"},
            {
                "id": "p2",
                "type": "important_callout",
                "label": "Important",
                "content": "Note short",
            },
        ],
    )

    response = svc.transform(
        CourseEditorAiRequest(
            sectionId="sec-1",
            operation="summarize",
            content="Hello\n\nNote",
            paragraphs=paragraphs,
            preserveStructure=True,
        )
    )

    orch_input: ContentTransformationInput = orchestrator.transform.call_args.args[0]
    assert orch_input.preserve_structure is True
    assert orch_input.paragraphs == paragraphs
    assert response.paragraphs is not None
    assert response.paragraphs[1]["label"] == "Important"
    assert response.content == "Hello\n\nNote"


def test_service_has_no_job_repository_or_db():
    svc, _ = _service()
    assert not hasattr(svc, "_db")
    assert not hasattr(svc, "_jobs")
