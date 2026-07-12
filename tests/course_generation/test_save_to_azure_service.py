"""Unit tests for SaveToAzureService (Phase 3 orchestration)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.course_generation.course_generation_job.constants import (
    CONTENT_VERSION_SOURCE_EDITOR_SAVE,
    CONTENT_VERSION_STATUS_AVAILABLE,
    CONTENT_VERSION_STATUS_CREATING,
    CONTENT_VERSION_STATUS_FAILED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_PROCESSING,
)
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.artifact_service import (
    ArtifactAlreadyExistsError,
    build_versioned_artifact_paths,
    resolve_course_slug,
    slugify_course_title,
)
from app.services.onboarding.course_generation.course_content_service import (
    CanonicalCourseState,
    CourseContentNotFoundError,
)
from app.services.onboarding.course_generation.docx_render_service import RenderedDocx
from app.services.onboarding.course_generation.editor_course_transformation_service import (
    EditorCourseTransformationError,
    EditorTransformationResult,
)
from app.services.onboarding.course_generation.save_to_azure_service import (
    JobNotFoundError,
    JobNotSavableError,
    SaveToAzureError,
    SaveToAzureFailedError,
    SaveToAzureService,
)


def _snapshot() -> RenderDocxRequest:
    return RenderDocxRequest(
        courseTitle="Edited Title",
        sections=[
            CourseSectionInput(
                id="sec-1",
                title="Section",
                level=1,
                content="Edited body",
            )
        ],
    )


def _canonical() -> CanonicalCourseState:
    return CanonicalCourseState(
        canonical_a2={
            "status": "completed",
            "run_id": "1",
            "course_title": "DB Course",
            "sections": [
                {
                    "section_id": "sec-1",
                    "heading": "Section",
                    "level": 1,
                    "body_paragraphs": [{"type": "text", "content": "Old"}],
                    "word_count": 1,
                    "images": [],
                    "maps_to_objectives": [0],
                }
            ],
            "course_description": "",
            "course_conclusion": "",
            "stats": {"generated": 1, "total_words": 1},
        },
        learning_objectives=["LO1"],
        course_title="DB Course",
        source="course_content_artifact",
    )


def _transformed() -> EditorTransformationResult:
    return EditorTransformationResult(
        canonical_a2={
            "status": "editor_saved",
            "run_id": "1",
            "course_title": "Edited Title",
            "sections": [
                {
                    "section_id": "sec-1",
                    "heading": "Section",
                    "level": 1,
                    "body_paragraphs": [{"type": "text", "content": "Edited body"}],
                    "word_count": 2,
                    "status": "editor_saved",
                    "is_parent_overview": False,
                    "images": [],
                    "maps_to_objectives": [0],
                }
            ],
            "course_description": "",
            "course_conclusion": "",
            "stats": {"generated": 1, "total_words": 2},
            "study_guide_docx": None,
            "generated_content_json": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        learning_objectives=["LO1"],
        course_title="Edited Title",
        meta={
            "totalWordCount": 2,
            "sectionCount": 1,
            "chapterCount": 1,
            "estimatedReadTime": "1 min read",
        },
    )


def _version(*, version_number: int = 2, status: str = CONTENT_VERSION_STATUS_CREATING):
    return SimpleNamespace(
        id=10,
        job_id=1,
        course_id=5,
        course_run_id=7,
        version_number=version_number,
        status_code=status,
        canonical_json_blob_path=None,
        docx_blob_path=None,
        created_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        created_by="editor",
    )


def _build_service(**overrides) -> tuple[SaveToAzureService, dict]:
    db = MagicMock()
    jobs = MagicMock()
    jobs.get_by_id.return_value = SimpleNamespace(
        id=1,
        course_run_id=7,
        status_code=JOB_STATUS_COMPLETED,
    )
    course_runs = MagicMock()
    course_runs.get_by_id.return_value = SimpleNamespace(id=7, course_id=5)
    courses = MagicMock()
    courses.get_by_id.return_value = SimpleNamespace(id=5, title="Annuity CE Course!")

    content = MagicMock()
    content.load_canonical_state.return_value = _canonical()

    transformer = MagicMock()
    transformer.transform.return_value = _transformed()

    docx = MagicMock()
    docx.render_from_a2.return_value = RenderedDocx(
        content=b"PK\x03\x04-docx",
        filename="Edited-Title.docx",
    )

    artifacts = MagicMock()
    artifacts.upload_bytes_no_overwrite.side_effect = lambda path, *_a, **_k: path

    versions = MagicMock()
    creating = _version(version_number=2)
    available = _version(version_number=2, status=CONTENT_VERSION_STATUS_AVAILABLE)
    available.canonical_json_blob_path = "annuity-ce-course/1/v2/course_content.json"
    available.docx_blob_path = "annuity-ce-course/1/v2/study_guide.docx"
    versions.reserve_next_version.return_value = creating
    versions.mark_available.return_value = available
    versions.has_any_version.return_value = True

    version_seed = MagicMock()
    version_seed.ensure_pipeline_version_one.return_value = SimpleNamespace(
        id=1,
        version_number=1,
        status_code=CONTENT_VERSION_STATUS_AVAILABLE,
    )

    deps = {
        "db": db,
        "jobs": jobs,
        "course_runs": course_runs,
        "courses": courses,
        "content": content,
        "transformer": transformer,
        "docx": docx,
        "artifacts": artifacts,
        "versions": versions,
        "version_seed": version_seed,
    }
    deps.update(overrides)

    service = SaveToAzureService(
        deps["db"],
        content_service=deps["content"],
        transformation_service=deps["transformer"],
        docx_service=deps["docx"],
        artifact_service=deps["artifacts"],
        versions=deps["versions"],
        version_seed=deps["version_seed"],
    )
    service.jobs = deps["jobs"]
    service.course_runs = deps["course_runs"]
    service.courses = deps["courses"]
    return service, deps


# ─── Path helpers ─────────────────────────────────────────────────────────────


def test_slugify_and_resolve_prefer_database_title():
    assert slugify_course_title("Annuity CE Course!") == "annuity-ce-course"
    assert "../evil/path" not in slugify_course_title("../evil/path")
    assert resolve_course_slug(
        database_title="Annuity CE Course!",
        course_slug_hint="../injected/slug",
    ) == "annuity-ce-course"
    assert resolve_course_slug(
        database_title="   ",
        course_slug_hint="Hint Slug",
    ) == "hint-slug"


def test_versioned_paths():
    paths = build_versioned_artifact_paths(
        course_slug="annuity-ce-course",
        job_id=1,
        version_number=3,
    )
    assert paths.directory == "annuity-ce-course/1/v3"
    assert paths.canonical_json_blob_path.endswith("/v3/course_content.json")
    assert paths.docx_blob_path.endswith("/v3/study_guide.docx")


# ─── Successful save ──────────────────────────────────────────────────────────


def test_successful_save_orchestrates_transform_render_reserve_upload_mark():
    service, deps = _build_service()
    result = service.save(
        job_id=1,
        course_snapshot=_snapshot(),
        course_slug="ignored-when-db-title-present",
        created_by="editor@example.com",
    )

    deps["content"].load_canonical_state.assert_called_once_with(1)
    deps["version_seed"].ensure_pipeline_version_one.assert_called_once_with(
        1, 5, 7, created_by="pipeline"
    )
    deps["transformer"].transform.assert_called_once()
    deps["docx"].render_from_a2.assert_called_once()
    deps["versions"].reserve_next_version.assert_called_once_with(
        job_id=1,
        course_id=5,
        course_run_id=7,
        source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
        created_by="editor@example.com",
    )

    upload_paths = [
        c.args[0] for c in deps["artifacts"].upload_bytes_no_overwrite.call_args_list
    ]
    assert upload_paths == [
        "annuity-ce-course/1/v2/course_content.json",
        "annuity-ce-course/1/v2/study_guide.docx",
    ]
    # JSON then DOCX; both use overwrite=False via no_overwrite helper.
    json_call = deps["artifacts"].upload_bytes_no_overwrite.call_args_list[0]
    assert json_call.kwargs["content_type"] == "application/json"
    docx_call = deps["artifacts"].upload_bytes_no_overwrite.call_args_list[1]
    assert "wordprocessingml" in docx_call.kwargs["content_type"]

    deps["versions"].mark_available.assert_called_once_with(
        10,
        canonical_json_blob_path="annuity-ce-course/1/v2/course_content.json",
        docx_blob_path="annuity-ce-course/1/v2/study_guide.docx",
    )
    assert deps["db"].commit.call_count >= 2
    assert result.version_number == 2
    assert result.version_id == 10
    assert result.meta["totalWordCount"] == 2
    deps["versions"].mark_failed.assert_not_called()


def test_storage_json_embeds_learning_objectives():
    service, deps = _build_service()
    service.save(
        job_id=1,
        course_snapshot=_snapshot(),
        created_by="editor",
    )
    json_bytes = deps["artifacts"].upload_bytes_no_overwrite.call_args_list[0].args[1]
    import json as _json

    payload = _json.loads(json_bytes.decode("utf-8"))
    assert payload["learning_objectives"] == ["LO1"]
    assert payload["course_title"] == "Edited Title"
    assert payload["sections"][0]["maps_to_objectives"] == [0]


# ─── Context / loading errors ─────────────────────────────────────────────────


def test_job_not_found():
    service, deps = _build_service()
    deps["jobs"].get_by_id.return_value = None
    with pytest.raises(JobNotFoundError):
        service.save(job_id=99, course_snapshot=_snapshot(), created_by="u")


def test_job_not_completed_not_savable():
    service, deps = _build_service()
    deps["jobs"].get_by_id.return_value = SimpleNamespace(
        id=1, course_run_id=7, status_code=JOB_STATUS_PROCESSING
    )
    with pytest.raises(JobNotSavableError):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")


def test_missing_canonical_state():
    service, deps = _build_service()
    deps["content"].load_canonical_state.side_effect = CourseContentNotFoundError("missing")
    with pytest.raises(CourseContentNotFoundError):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    deps["versions"].reserve_next_version.assert_not_called()


# ─── Failure behavior ─────────────────────────────────────────────────────────


def test_transformation_failure_creates_no_version_or_uploads():
    service, deps = _build_service()
    deps["transformer"].transform.side_effect = EditorCourseTransformationError("bad")
    with pytest.raises(EditorCourseTransformationError, match="bad"):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    deps["versions"].reserve_next_version.assert_not_called()
    deps["artifacts"].upload_bytes_no_overwrite.assert_not_called()


def test_docx_failure_before_reservation_creates_no_version():
    service, deps = _build_service()
    deps["docx"].render_from_a2.side_effect = RuntimeError("docx boom")
    with pytest.raises(SaveToAzureError, match="DOCX"):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    deps["versions"].reserve_next_version.assert_not_called()
    deps["artifacts"].upload_bytes_no_overwrite.assert_not_called()


def test_json_upload_failure_marks_version_failed():
    service, deps = _build_service()

    def fail_json(path, *_a, **_k):
        if path.endswith(".json"):
            raise RuntimeError("json upload failed")
        return path

    deps["artifacts"].upload_bytes_no_overwrite.side_effect = fail_json
    with pytest.raises(SaveToAzureFailedError) as exc_info:
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    assert exc_info.value.version_number == 2
    deps["versions"].mark_failed.assert_called_once()
    assert deps["versions"].mark_failed.call_args.args[0] == 10
    deps["versions"].mark_available.assert_not_called()


def test_docx_upload_failure_after_json_marks_failed():
    service, deps = _build_service()

    def fail_docx(path, *_a, **_k):
        if path.endswith(".docx"):
            raise RuntimeError("docx upload failed")
        return path

    deps["artifacts"].upload_bytes_no_overwrite.side_effect = fail_docx
    with pytest.raises(SaveToAzureFailedError):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    deps["versions"].mark_failed.assert_called_once()
    # JSON upload happened first (orphan policy: leave blob; no cleanup call).
    assert deps["artifacts"].upload_bytes_no_overwrite.call_count == 2


def test_mark_available_failure_marks_failed():
    service, deps = _build_service()
    deps["versions"].mark_available.side_effect = RuntimeError("db write failed")
    with pytest.raises(SaveToAzureFailedError, match="mark version available"):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    deps["versions"].mark_failed.assert_called_once()


def test_overwrite_conflict_marks_failed():
    service, deps = _build_service()
    deps["artifacts"].upload_bytes_no_overwrite.side_effect = ArtifactAlreadyExistsError(
        "exists"
    )
    with pytest.raises(SaveToAzureFailedError):
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    deps["versions"].mark_failed.assert_called_once()


# ─── Layering ─────────────────────────────────────────────────────────────────


def test_service_does_not_import_azure_sdk_directly():
    import app.services.onboarding.course_generation.save_to_azure_service as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "azure.storage" not in source
    assert "BlobServiceClient" not in source
    assert "shared_state" not in source
