"""Phase 5: pipeline runner seeds Version 1 after successful artifact persistence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.onboarding.course_generation.pipeline_runner import (
    CourseGenerationPipelineRunner,
)


def _runner() -> tuple[CourseGenerationPipelineRunner, dict]:
    db = MagicMock()
    runner = CourseGenerationPipelineRunner(db)
    runner.jobs = MagicMock()
    runner.loader = MagicMock()
    runner.artifacts = MagicMock()
    runner.validation_runs = MagicMock()
    runner.progress = MagicMock()
    runner.course_runs = MagicMock()
    runner.version_seed = MagicMock()
    return runner, {
        "db": db,
        "jobs": runner.jobs,
        "artifacts": runner.artifacts,
        "course_runs": runner.course_runs,
        "version_seed": runner.version_seed,
    }


def _spec() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="7",
        course_title="Course",
        course_difficulty="intermediate",
        course_audience="agents",
        course_spec={},
        learning_objectives=["LO"],
        source_file_specs=[],
    )


def test_seed_pipeline_version_one_registers_available_pipeline():
    runner, deps = _runner()
    deps["course_runs"].get_by_id.return_value = SimpleNamespace(id=7, course_id=5)
    deps["jobs"].repository.get_by_id.return_value = SimpleNamespace(
        id=1, requested_by="alice@example.com"
    )
    deps["version_seed"].register_from_paths.return_value = SimpleNamespace(id=99)

    runner._seed_pipeline_version_one(
        job_id="1",
        course_run_id="7",
        canonical_json_blob_path="slug/1/course_content.json",
        docx_blob_path="slug/1/study_guide.docx",
    )

    deps["version_seed"].register_from_paths.assert_called_once_with(
        job_id=1,
        course_id=5,
        course_run_id=7,
        canonical_json_blob_path="slug/1/course_content.json",
        docx_blob_path="slug/1/study_guide.docx",
        created_by="alice@example.com",
    )
    deps["db"].commit.assert_called()


def test_execute_traced_seeds_v1_only_when_both_artifacts_and_validation_pass():
    runner, deps = _runner()
    deps["jobs"].repository.get_by_id.return_value = SimpleNamespace(
        id=1, requested_by="pipeline-user", status_code="PROCESSING"
    )
    deps["course_runs"].get_by_id.return_value = SimpleNamespace(id=7, course_id=5)

    content_artifact = SimpleNamespace(id=10, blob_path="slug/1/course_content.json")
    study_guide_artifact = SimpleNamespace(id=11, blob_path="slug/1/study_guide.docx")
    report_artifact = SimpleNamespace(id=12, blob_path="slug/1/validation_report.json")

    def persist_bytes(**kwargs):
        if kwargs.get("file_name") == "course_content.json":
            return content_artifact
        if kwargs.get("file_name") == "validation_report.json":
            return report_artifact
        return SimpleNamespace(id=1, blob_path="other")

    deps["artifacts"].persist_bytes.side_effect = persist_bytes
    deps["artifacts"].persist_file.return_value = study_guide_artifact
    deps["version_seed"].register_from_paths.return_value = SimpleNamespace(id=1)

    runner.loader.load.return_value = _spec()

    validation = SimpleNamespace(
        model_dump_json=lambda: "{}",
        blockers=0,
        warnings=0,
        infos=0,
        phase="full",
        message="",
    )
    a2 = SimpleNamespace(model_dump_json=lambda: "{}")
    result = SimpleNamespace(
        enriched_sections=[],
        a2=a2,
        study_guide_path="/tmp/study_guide.docx",
        validation=validation,
        validation_passed=True,
        repair_attempts=0,
    )

    with (
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.create_kernel",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.ContentGenerationOrchestrator"
        ) as orch_cls,
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.traced_workflow"
        ) as traced,
    ):
        traced.return_value.__enter__ = MagicMock(return_value=None)
        traced.return_value.__exit__ = MagicMock(return_value=False)
        orch_cls.return_value.execute.return_value = result

        runner._execute_traced(job_id="1", course_run_id="7")

    deps["version_seed"].register_from_paths.assert_called_once()
    deps["jobs"].mark_completed.assert_called_once()


def test_execute_traced_skips_seed_when_validation_fails():
    runner, deps = _runner()
    deps["artifacts"].persist_bytes.return_value = SimpleNamespace(
        id=1, blob_path="slug/1/course_content.json"
    )
    deps["artifacts"].persist_file.return_value = SimpleNamespace(
        id=2, blob_path="slug/1/study_guide.docx"
    )
    runner.loader.load.return_value = _spec()
    validation = SimpleNamespace(
        model_dump_json=lambda: "{}",
        blockers=1,
        warnings=0,
        infos=0,
        phase="full",
        message="blocked",
    )
    result = SimpleNamespace(
        enriched_sections=[],
        a2=SimpleNamespace(model_dump_json=lambda: "{}"),
        study_guide_path="/tmp/study_guide.docx",
        validation=validation,
        validation_passed=False,
        repair_attempts=1,
    )

    with (
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.create_kernel",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.ContentGenerationOrchestrator"
        ) as orch_cls,
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.traced_workflow"
        ) as traced,
    ):
        traced.return_value.__enter__ = MagicMock(return_value=None)
        traced.return_value.__exit__ = MagicMock(return_value=False)
        orch_cls.return_value.execute.return_value = result
        runner._execute_traced(job_id="1", course_run_id="7")

    deps["version_seed"].register_from_paths.assert_not_called()
    deps["jobs"].mark_failed.assert_called_once()
    deps["jobs"].mark_completed.assert_not_called()


def test_execute_traced_skips_seed_when_study_guide_missing():
    runner, deps = _runner()
    deps["artifacts"].persist_bytes.side_effect = lambda **kwargs: SimpleNamespace(
        id=1,
        blob_path=f"slug/1/{kwargs.get('file_name', 'x')}",
    )
    runner.loader.load.return_value = _spec()
    validation = SimpleNamespace(
        model_dump_json=lambda: "{}",
        blockers=0,
        warnings=0,
        infos=0,
        phase="full",
        message="",
    )
    result = SimpleNamespace(
        enriched_sections=[],
        a2=SimpleNamespace(model_dump_json=lambda: "{}"),
        study_guide_path=None,
        validation=validation,
        validation_passed=True,
        repair_attempts=0,
    )

    with (
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.create_kernel",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.ContentGenerationOrchestrator"
        ) as orch_cls,
        patch(
            "app.services.onboarding.course_generation.pipeline_runner.traced_workflow"
        ) as traced,
    ):
        traced.return_value.__enter__ = MagicMock(return_value=None)
        traced.return_value.__exit__ = MagicMock(return_value=False)
        orch_cls.return_value.execute.return_value = result
        runner._execute_traced(job_id="1", course_run_id="7")

    deps["version_seed"].register_from_paths.assert_not_called()
    deps["jobs"].mark_completed.assert_called_once()
