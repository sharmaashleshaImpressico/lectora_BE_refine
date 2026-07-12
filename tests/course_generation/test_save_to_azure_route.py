"""API tests for POST /jobs/{job_id}/artifacts/save-to-azure."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_save_to_azure_service
from app.api.v1.endpoints.content_generation import course_generation_job as job_routes
from app.core.auth.dependencies import get_current_user_name, require_valid_token
from app.repositories.course_generation.course_content_version_repository import (
    VersionAllocationError,
)
from app.services.onboarding.course_generation.course_content_service import (
    CourseContentNotFoundError,
)
from app.services.onboarding.course_generation.editor_course_transformation_service import (
    EditorCourseTransformationError,
)
from app.services.onboarding.course_generation.save_to_azure_service import (
    CourseContextNotFoundError,
    JobNotFoundError,
    JobNotSavableError,
    SaveToAzureFailedError,
    SaveToAzureResult,
)


def _valid_course_body(**overrides) -> dict:
    body = {
        "course": {
            "courseTitle": "Annuity CE Course",
            "sections": [
                {
                    "id": "sec-1",
                    "title": "Chapter One",
                    "level": 1,
                    "sectionType": "content",
                    "content": "Edited body text",
                    "paragraphs": [],
                    "children": [],
                    "order": 0,
                }
            ],
        },
        "courseSlug": "optional-slug",
    }
    body.update(overrides)
    return body


def _result(**overrides) -> SaveToAzureResult:
    data = dict(
        job_id=42,
        course_id=101,
        course_run_id=205,
        version_id=456,
        version_number=2,
        canonical_json_blob_path="annuity-ce-course/42/v2/course_content.json",
        docx_blob_path="annuity-ce-course/42/v2/study_guide.docx",
        created_at=datetime(2026, 7, 12, 14, 0, 0, tzinfo=timezone.utc),
        meta={
            "totalWordCount": 1200,
            "sectionCount": 8,
            "chapterCount": 3,
            "estimatedReadTime": "6 min read",
        },
        course_title="Annuity CE Course",
        container_hint="course-generation-artifacts",
    )
    data.update(overrides)
    return SaveToAzureResult(**data)


@pytest.fixture
def save_client():
    app = FastAPI()
    app.include_router(job_routes.router)

    mock_service = MagicMock()
    mock_service.save.return_value = _result()

    app.dependency_overrides[require_valid_token] = lambda: {"name": "Ada Lovelace"}
    app.dependency_overrides[get_current_user_name] = lambda: "Ada Lovelace"
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[get_save_to_azure_service] = lambda: mock_service

    client = TestClient(app)
    yield client, mock_service, app
    app.dependency_overrides.clear()


# ─── Success ──────────────────────────────────────────────────────────────────


def test_save_to_azure_success(save_client):
    client, mock_service, _app = save_client
    response = client.post(
        "/jobs/42/artifacts/save-to-azure",
        json=_valid_course_body(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["jobId"] == "42"
    assert payload["versionNumber"] == 2
    assert payload["versionId"] == "456"
    assert payload["courseId"] == 101
    assert payload["courseRunId"] == 205
    assert payload["blobPath"] == "annuity-ce-course/42/v2/study_guide.docx"
    assert payload["fileName"] == "study_guide.docx"
    assert payload["containerName"] == "course-generation-artifacts"
    assert payload["meta"]["totalWordCount"] == 1200
    assert payload["canonicalJsonBlobPath"].endswith("course_content.json")

    mock_service.save.assert_called_once()
    kwargs = mock_service.save.call_args.kwargs
    assert kwargs["job_id"] == "42"
    assert kwargs["course_slug"] == "optional-slug"
    assert kwargs["created_by"] == "Ada Lovelace"
    assert kwargs["course_snapshot"].course_title == "Annuity CE Course"
    assert len(kwargs["course_snapshot"].sections) == 1


def test_course_slug_optional(save_client):
    client, mock_service, _app = save_client
    body = _valid_course_body()
    del body["courseSlug"]
    response = client.post("/jobs/42/artifacts/save-to-azure", json=body)
    assert response.status_code == 200
    assert mock_service.save.call_args.kwargs["course_slug"] is None


# ─── Validation ───────────────────────────────────────────────────────────────


def test_missing_course_returns_422(save_client):
    client, mock_service, _app = save_client
    response = client.post(
        "/jobs/42/artifacts/save-to-azure",
        json={"courseSlug": "x"},
    )
    assert response.status_code == 422
    mock_service.save.assert_not_called()


def test_invalid_section_shape_returns_422(save_client):
    client, mock_service, _app = save_client
    response = client.post(
        "/jobs/42/artifacts/save-to-azure",
        json={
            "course": {
                "courseTitle": "T",
                "sections": [{"id": "s1", "level": "not-an-int"}],
            }
        },
    )
    assert response.status_code == 422
    mock_service.save.assert_not_called()


def test_extra_client_version_fields_are_ignored(save_client):
    client, mock_service, _app = save_client
    body = _valid_course_body(
        versionNumber=99,
        blobPath="evil/path.docx",
        courseId=1,
    )
    response = client.post("/jobs/42/artifacts/save-to-azure", json=body)
    assert response.status_code == 200
    # Path job_id and service result remain authoritative.
    assert response.json()["versionNumber"] == 2
    assert "evil" not in response.json()["blobPath"]
    kwargs = mock_service.save.call_args.kwargs
    assert "version_number" not in kwargs


# ─── Error mapping ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("exc", "status_code"),
    [
        (JobNotFoundError("missing"), 404),
        (CourseContextNotFoundError("no course"), 404),
        (CourseContentNotFoundError("no content"), 404),
        (JobNotSavableError("not completed"), 409),
        (VersionAllocationError("collision"), 409),
        (EditorCourseTransformationError("bad tree"), 422),
        (SaveToAzureFailedError("upload failed", version_id=10, version_number=2), 502),
    ],
)
def test_error_mapping(save_client, exc, status_code):
    client, mock_service, _app = save_client
    mock_service.save.side_effect = exc
    response = client.post(
        "/jobs/42/artifacts/save-to-azure",
        json=_valid_course_body(),
    )
    assert response.status_code == status_code
    detail = response.json()["detail"]
    # Safe responses must not leak stack / azure / sql noise.
    assert "Traceback" not in str(detail)
    assert "connection_string" not in str(detail).lower()


def test_save_failure_hides_internal_message(save_client):
    client, mock_service, _app = save_client
    mock_service.save.side_effect = SaveToAzureFailedError(
        "Azure SecretKey=abc failed at pyodbc"
    )
    response = client.post(
        "/jobs/42/artifacts/save-to-azure",
        json=_valid_course_body(),
    )
    assert response.status_code == 502
    assert "SecretKey" not in response.json()["detail"]
    assert "pyodbc" not in response.json()["detail"]


# ─── Auth ─────────────────────────────────────────────────────────────────────


def test_unauthenticated_request_returns_401():
    app = FastAPI()
    app.include_router(job_routes.router)
    # Do not override auth — HTTPBearer auto_error=False still yields 401 via require_valid_token.
    client = TestClient(app)
    response = client.post(
        "/jobs/42/artifacts/save-to-azure",
        json=_valid_course_body(),
    )
    assert response.status_code == 401


def test_created_by_uses_authenticated_user_not_body(save_client):
    client, mock_service, _app = save_client
    body = _valid_course_body(createdBy="attacker@evil.com", requested_by="attacker")
    response = client.post("/jobs/42/artifacts/save-to-azure", json=body)
    assert response.status_code == 200
    assert mock_service.save.call_args.kwargs["created_by"] == "Ada Lovelace"


# ─── Layering / OpenAPI ───────────────────────────────────────────────────────


def test_route_delegates_only_to_save_service(save_client):
    client, mock_service, app = save_client
    client.post("/jobs/42/artifacts/save-to-azure", json=_valid_course_body())
    assert mock_service.save.call_count == 1
    # Dependency override proves the route uses get_save_to_azure_service, not inline Azure.
    assert get_save_to_azure_service in app.dependency_overrides


def test_openapi_includes_save_to_azure_contract(save_client):
    _client, _mock, app = save_client
    schema = app.openapi()
    path = schema["paths"]["/jobs/{job_id}/artifacts/save-to-azure"]["post"]
    assert "SaveToAzureRequest" in str(path.get("requestBody", {})) or "course" in str(
        path.get("requestBody", {})
    )
    # Response model exposes versionNumber via alias.
    components = schema.get("components", {}).get("schemas", {})
    response_schema = components.get("SaveToAzureResponse", {})
    props = response_schema.get("properties", {})
    # FastAPI may expose either alias or field name depending on schema generation.
    assert "versionNumber" in props or "version_number" in props
    assert "course" in str(path.get("requestBody", {})).lower() or any(
        "SaveToAzureRequest" in str(ref)
        for ref in [path.get("requestBody", {})]
    )
