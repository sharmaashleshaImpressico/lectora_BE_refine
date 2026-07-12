"""Tests for CourseContentService.load_canonical_state (Phase 3 loader)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_ENRICHED_SECTIONS,
)
from app.services.onboarding.course_generation.course_content_service import (
    CourseContentNotFoundError,
    CourseContentService,
)


def _service() -> tuple[CourseContentService, MagicMock, MagicMock]:
    db = MagicMock()
    svc = CourseContentService(db)
    svc.versions = MagicMock()
    svc.artifacts = MagicMock()
    svc.course_run_specs = MagicMock()
    svc._read_json = MagicMock()
    return svc, svc.versions, svc.artifacts


def test_prefers_latest_available_version():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = SimpleNamespace(
        version_number=2,
        canonical_json_blob_path="slug/1/v2/course_content.json",
    )
    svc._read_json.return_value = {
        "course_title": "From Version",
        "sections": [{"section_id": "s1", "heading": "H"}],
        "learning_objectives": ["VLO"],
    }

    state = svc.load_canonical_state(1)
    assert state.source == "version"
    assert state.course_title == "From Version"
    assert state.learning_objectives == ["VLO"]
    artifacts.list_by_job.assert_not_called()


def test_falls_back_to_flat_course_content_artifact():
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
        "course_title": "From Artifact",
        "sections": [{"section_id": "s1"}],
    }
    svc.course_run_specs.get_by.return_value = None

    state = svc.load_canonical_state(1)
    assert state.source == "course_content_artifact"
    assert state.course_title == "From Artifact"


def test_enriched_only_is_not_enough_for_canonical_save():
    svc, versions, artifacts = _service()
    versions.get_latest_available.return_value = None
    artifacts.list_by_job.return_value = [
        SimpleNamespace(
            artifact_type=ARTIFACT_TYPE_ENRICHED_SECTIONS,
            blob_path="slug/1/enriched_sections.json",
            course_run_id=9,
        )
    ]
    with pytest.raises(CourseContentNotFoundError, match="course_content.json"):
        svc.load_canonical_state(1)
