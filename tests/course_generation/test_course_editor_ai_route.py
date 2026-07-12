"""API tests for POST /ai/content-transformations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_db, get_kernel
from app.api.v1.endpoints.ai import content_transformations as ai_routes
from app.ai.agents.content_transformation_agent import ContentTransformationError
from app.core.auth.dependencies import require_valid_token
from app.schemas.ai.content_ai import (
    ContentAiOperation,
    CourseEditorAiRequest,
    CourseEditorAiResponse,
)


def _body(**overrides) -> dict:
    payload = {
        "sectionId": "sec-1",
        "operation": "summarize",
        "content": "Unsaved frontend section content about annuities.",
        "userPrompt": None,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def ai_client():
    app = FastAPI()
    app.include_router(ai_routes.router)

    mock_service = MagicMock()
    mock_service.transform.return_value = CourseEditorAiResponse(
        section_id="sec-1",
        operation=ContentAiOperation.summarize,
        content="Condensed annuity content.",
    )

    app.dependency_overrides[require_valid_token] = lambda: {"name": "Ada Lovelace"}
    app.dependency_overrides[get_kernel] = lambda: MagicMock()

    with patch.object(
        ai_routes,
        "CourseEditorAiService",
        return_value=mock_service,
    ) as service_cls:
        client = TestClient(app)
        yield client, mock_service, service_cls

    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "operation,user_prompt",
    [
        ("summarize", None),
        ("expand", None),
        ("simplify", "keep legal terms"),
        ("rewrite", "Make this more concise"),
        ("improve_tone", "More formal professional tone"),
    ],
)
def test_transform_content_success_all_operations(ai_client, operation, user_prompt):
    client, mock_service, service_cls = ai_client
    mock_service.transform.return_value = CourseEditorAiResponse(
        section_id="sec-1",
        operation=ContentAiOperation(operation),
        content=f"transformed-{operation}",
    )

    response = client.post(
        "/ai/content-transformations",
        json=_body(operation=operation, userPrompt=user_prompt),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["sectionId"] == "sec-1"
    assert data["operation"] == operation
    assert data["content"] == f"transformed-{operation}"

    service_cls.assert_called_once()
    assert "db" not in service_cls.call_args.kwargs
    assert len(service_cls.call_args.args) == 1  # kernel only

    mock_service.transform.assert_called_once()
    request = mock_service.transform.call_args.args[0]
    assert isinstance(request, CourseEditorAiRequest)
    assert request.content == "Unsaved frontend section content about annuities."
    assert request.operation.value == operation
    assert "job_id" not in mock_service.transform.call_args.kwargs


@pytest.mark.parametrize("operation", ["rewrite", "improve_tone"])
def test_transform_requires_user_prompt_for_guided_ops(ai_client, operation):
    client, mock_service, _ = ai_client

    response = client.post(
        "/ai/content-transformations",
        json=_body(operation=operation, userPrompt=None),
    )

    assert response.status_code == 422
    mock_service.transform.assert_not_called()


@pytest.mark.parametrize("operation", ["rewrite", "improve_tone"])
def test_transform_rejects_blank_user_prompt_for_guided_ops(ai_client, operation):
    client, mock_service, _ = ai_client

    response = client.post(
        "/ai/content-transformations",
        json=_body(operation=operation, userPrompt="   "),
    )

    assert response.status_code == 422
    mock_service.transform.assert_not_called()


def test_transform_provider_failure_maps_to_502(ai_client):
    client, mock_service, _ = ai_client
    mock_service.transform.side_effect = ContentTransformationError("LLM failed")

    response = client.post("/ai/content-transformations", json=_body())

    assert response.status_code == 502


def test_transform_preserve_structure_round_trip(ai_client):
    client, mock_service, _ = ai_client
    paragraphs = [
        {
            "id": "b1",
            "type": "text",
            "content": "Annuities provide **income**.",
        },
        {
            "id": "b2",
            "type": "important_callout",
            "label": "Important",
            "content": "Charges may apply.",
        },
        {
            "id": "b3",
            "type": "callout",
            "label": "Warning",
            "content": "Avoid misrepresentation.",
        },
        {
            "id": "b4",
            "type": "callout",
            "label": "Best Practice",
            "content": "Document suitability.",
        },
        {"id": "b5", "type": "bullet_list", "items": ["Fixed", "Variable"]},
        {"id": "b6", "type": "numbered_list", "items": ["Assess", "Compare"]},
        {
            "id": "b7",
            "type": "table",
            "caption": "Compare products",
            "headers": ["Feature", "Fixed"],
            "rows": [["Risk", "Low"]],
        },
    ]
    transformed = [
        {**paragraphs[0], "content": "Annuities can provide **income**."},
        {**paragraphs[1], "content": "Fees may apply."},
        {**paragraphs[2], "content": "Do not misrepresent products."},
        {**paragraphs[3], "content": "Always document suitability."},
        {**paragraphs[4], "items": ["Fixed annuity", "Variable annuity"]},
        {**paragraphs[5], "items": ["Assess needs", "Compare options"]},
        {
            **paragraphs[6],
            "caption": "Product comparison",
            "headers": ["Feature", "Fixed"],
            "rows": [["Risk", "Low"]],
        },
    ]
    mock_service.transform.return_value = CourseEditorAiResponse(
        section_id="sec-1",
        operation=ContentAiOperation.summarize,
        content="compat",
        paragraphs=transformed,
    )

    response = client.post(
        "/ai/content-transformations",
        json=_body(
            preserveStructure=True,
            paragraphs=paragraphs,
            content="flat preview",
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["paragraphs"] is not None
    assert len(data["paragraphs"]) == 7
    assert data["paragraphs"][1]["label"] == "Important"
    assert data["paragraphs"][2]["label"] == "Warning"
    assert data["paragraphs"][3]["label"] == "Best Practice"
    assert data["paragraphs"][0]["content"].find("**income**") >= 0
    assert data["content"] == "compat"

    request = mock_service.transform.call_args.args[0]
    assert request.preserve_structure is True
    assert request.paragraphs[6]["type"] == "table"


def test_preserve_structure_requires_paragraphs_with_ids(ai_client):
    client, mock_service, _ = ai_client

    response = client.post(
        "/ai/content-transformations",
        json=_body(preserveStructure=True, paragraphs=[]),
    )
    assert response.status_code == 422
    mock_service.transform.assert_not_called()


def test_route_does_not_resolve_database_dependency(ai_client):
    client, _, _ = ai_client
    # get_db is intentionally not overridden; if the route depended on it,
    # FastAPI would fail resolving the dependency.
    assert get_db not in client.app.dependency_overrides

    response = client.post("/ai/content-transformations", json=_body())
    assert response.status_code == 200


def test_schema_validation_rewrite_requires_prompt():
    with pytest.raises(ValidationError):
        CourseEditorAiRequest(
            sectionId="sec-1",
            operation="rewrite",
            content="body",
            userPrompt="",
        )
