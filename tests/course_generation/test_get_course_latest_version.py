"""Phase 5: GET /jobs/{id}/course prefers latest AVAILABLE version."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_ENRICHED_SECTIONS,
)
from app.services.onboarding.course_generation.course_content_service import (
    CourseContentConsistencyError,
    CourseContentNotFoundError,
    CourseContentService,
    _map_a2_output,
)


def _service() -> tuple[CourseContentService, MagicMock, MagicMock]:
    db = MagicMock()
    svc = CourseContentService(db)
    svc.versions = MagicMock()
    svc.artifacts = MagicMock()
    svc.course_run_specs = MagicMock()
    svc._resolve_course_type = MagicMock(return_value="Insurance CE")
    svc._read_json = MagicMock()
    return svc, svc.versions, svc.artifacts


def test_get_course_no_versions_uses_flat_artifact():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = None
    artifacts.list_by_job.return_value = [
        SimpleNamespace(
            artifact_type=ARTIFACT_TYPE_COURSE_CONTENT,
            blob_path="slug/1/course_content.json",
            course_run_id=9,
        )
    ]
    svc._read_json.return_value = {
        "course_title": "Flat Title",
        "sections": [
            {
                "section_id": "s1",
                "heading": "Lesson",
                "level": 1,
                "outline_lesson": "Lesson",
                "body_paragraphs": [{"type": "text", "content": "Body"}],
                "word_count": 1,
                "images": [],
            }
        ],
    }

    result = svc.get_course_content("1")
    assert result["courseTitle"] == "Flat Title"
    assert result["jobId"] == "1"
    assert "sections" in result
    assert "meta" in result


def test_get_course_prefers_version_2_over_version_1_and_flat():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = SimpleNamespace(
        version_number=2,
        canonical_json_blob_path="slug/1/v2/course_content.json",
    )
    artifacts.list_by_job.return_value = [
        SimpleNamespace(
            artifact_type=ARTIFACT_TYPE_COURSE_CONTENT,
            blob_path="slug/1/course_content.json",
            course_run_id=9,
        )
    ]
    svc._read_json.return_value = {
        "course_title": "Saved Title",
        "learning_objectives": ["Explain annuities"],
        "sections": [
            {
                "section_id": "s1",
                "heading": "Chapter",
                "level": 1,
                "outline_lesson": "Chapter",
                "body_paragraphs": [{"type": "text", "content": "Hi"}],
                "word_count": 1,
                "images": [],
            }
        ],
    }

    result = svc.get_course_content("1")
    assert result["courseTitle"] == "Saved Title"
    lo = next(s for s in result["sections"] if s["sectionType"] == "learning-objectives")
    assert lo["learningObjectives"] == ["Explain annuities"]
    svc._read_json.assert_called_once_with("slug/1/v2/course_content.json")


def test_get_course_ignores_failed_and_creating_higher_versions():
    """get_latest_available already filters; assert we only call that helper."""
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = SimpleNamespace(
        version_number=2,
        canonical_json_blob_path="slug/1/v2/course_content.json",
    )
    artifacts.list_by_job.return_value = []
    svc._read_json.return_value = {
        "course_title": "V2",
        "sections": [
            {
                "section_id": "s1",
                "heading": "H",
                "level": 1,
                "outline_lesson": "H",
                "body_paragraphs": [],
                "word_count": 0,
                "images": [],
            }
        ],
    }
    result = svc.get_course_content("1")
    assert result["courseTitle"] == "V2"
    versions.get_latest_available.assert_called_once_with("1")


def test_get_course_missing_latest_blob_raises_consistency_error():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = SimpleNamespace(
        version_number=2,
        canonical_json_blob_path="slug/1/v2/missing.json",
    )
    artifacts.list_by_job.return_value = [
        SimpleNamespace(
            artifact_type=ARTIFACT_TYPE_COURSE_CONTENT,
            blob_path="slug/1/course_content.json",
            course_run_id=9,
        )
    ]
    svc._read_json.side_effect = CourseContentNotFoundError("missing")
    with pytest.raises(CourseContentConsistencyError, match="missing blob"):
        svc.get_course_content("1")


def test_get_course_invalid_latest_json_raises_consistency_error():
    import json

    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = SimpleNamespace(
        version_number=3,
        canonical_json_blob_path="slug/1/v3/course_content.json",
    )
    artifacts.list_by_job.return_value = []
    svc._read_json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
    with pytest.raises(CourseContentConsistencyError, match="invalid JSON"):
        svc.get_course_content("1")


def test_get_course_falls_back_to_enriched_when_no_versions_or_flat():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = None
    artifacts.list_by_job.return_value = [
        SimpleNamespace(
            artifact_type=ARTIFACT_TYPE_ENRICHED_SECTIONS,
            blob_path="slug/1/enriched_sections.json",
            course_run_id=9,
        )
    ]
    svc._read_json.return_value = [{"title": "Lesson", "content": "Body", "subtopics": []}]
    result = svc.get_course_content("1")
    assert result["sections"][0]["title"] == "Lesson"


def test_map_a2_output_tolerates_extra_keys_and_missing_los():
    result = _map_a2_output(
        "1",
        {
            "course_title": "Older Flat",
            "extra_wrapper": {"ignored": True},
            "sections": [
                {
                    "section_id": "s1",
                    "heading": "H",
                    "level": 1,
                    "outline_lesson": "H",
                    "body_paragraphs": [{"type": "text", "content": "x"}],
                    "word_count": 1,
                    "images": [],
                }
            ],
        },
        course_type="",
    )
    assert result["courseTitle"] == "Older Flat"
    assert all(s["sectionType"] != "learning-objectives" for s in result["sections"])


def test_load_canonical_uses_consistency_error_for_corrupt_version():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = SimpleNamespace(
        version_number=2,
        canonical_json_blob_path="slug/1/v2/course_content.json",
    )
    svc._read_json.side_effect = CourseContentNotFoundError("gone")
    with pytest.raises(CourseContentConsistencyError):
        svc.load_canonical_state(1)
    artifacts.list_by_job.assert_not_called()
