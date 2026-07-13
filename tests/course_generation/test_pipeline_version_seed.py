"""Phase 5: lazy Version 1 backfill + Save-to-Azure integration."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_STUDY_GUIDE,
    CONTENT_VERSION_SOURCE_EDITOR_SAVE,
    CONTENT_VERSION_SOURCE_PIPELINE,
    CONTENT_VERSION_STATUS_AVAILABLE,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_PENDING,
)
from app.models.course_generation.course_generation_job.course_content_version import (
    CourseContentVersion,
)
from app.models.course_generation.course_generation_job.job import CourseGenerationJob
from app.models.course_generation.course_generation_job.job_artifact import (
    CourseGenerationJobArtifact,
)
from app.models.course_generation.course_generation_job.job_status import (
    CourseGenerationJobStatus,
)
from app.models.onboarding.course_basic.course_basic import CourseBasic
from app.models.onboarding.course_run.course_run import CourseRun
from app.repositories.course_generation.course_content_version_repository import (
    CourseContentVersionRepository,
)
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.course_content_service import (
    CanonicalCourseState,
)
from app.services.onboarding.course_generation.docx_render_service import RenderedDocx
from app.services.onboarding.course_generation.editor_course_transformation_service import (
    EditorTransformationResult,
)
from app.services.onboarding.course_generation.pipeline_version_seed_service import (
    PipelineVersionArtifactsMissingError,
    PipelineVersionSeedService,
)
from app.services.onboarding.course_generation.save_to_azure_service import (
    SaveToAzureError,
    SaveToAzureService,
)


def _enable_sqlite_fks(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", _enable_sqlite_fks)
    with eng.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(
        eng,
        tables=[
            CourseBasic.__table__,
            CourseRun.__table__,
            CourseGenerationJobStatus.__table__,
            CourseGenerationJob.__table__,
            CourseGenerationJobArtifact.__table__,
            CourseContentVersion.__table__,
        ],
    )
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    for code, name in (
        (JOB_STATUS_PENDING, "Pending"),
        (JOB_STATUS_COMPLETED, "Completed"),
    ):
        session.add(
            CourseGenerationJobStatus(
                code=code, name=name, description=name, is_active=True
            )
        )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _seed_completed_job(db: Session, *, with_artifacts: bool = True) -> tuple[int, int, int]:
    course = CourseBasic(
        title="Annuity CE Course",
        course_code="AN-1",
        course_type="Insurance CE",
        status_code="DRAFT",
        created_by="tester",
    )
    db.add(course)
    db.flush()
    course_run = CourseRun(
        course_id=course.id,
        version_number=1,
        status_code="DRAFT",
        created_by="tester",
    )
    db.add(course_run)
    db.flush()
    job = CourseGenerationJob(
        course_run_id=course_run.id,
        status_code=JOB_STATUS_COMPLETED,
        requested_by="tester",
    )
    db.add(job)
    db.flush()
    if with_artifacts:
        db.add(
            CourseGenerationJobArtifact(
                job_id=job.id,
                course_run_id=course_run.id,
                artifact_type=ARTIFACT_TYPE_COURSE_CONTENT,
                stage_name="content_generation",
                file_name="course_content.json",
                blob_path=f"annuity-ce-course/{job.id}/course_content.json",
                content_type="application/json",
            )
        )
        db.add(
            CourseGenerationJobArtifact(
                job_id=job.id,
                course_run_id=course_run.id,
                artifact_type=ARTIFACT_TYPE_STUDY_GUIDE,
                stage_name="content_generation",
                file_name="study_guide.docx",
                blob_path=f"annuity-ce-course/{job.id}/study_guide.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
    db.commit()
    return course.id, course_run.id, job.id


def test_lazy_backfill_creates_pipeline_v1_from_flat_paths(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db)
    seed = PipelineVersionSeedService(db)
    version = seed.ensure_pipeline_version_one(job_id, course_id, run_id)
    db.commit()

    assert version.version_number == 1
    assert version.source_type == CONTENT_VERSION_SOURCE_PIPELINE
    assert version.status_code == CONTENT_VERSION_STATUS_AVAILABLE
    assert version.canonical_json_blob_path == f"annuity-ce-course/{job_id}/course_content.json"
    assert version.docx_blob_path == f"annuity-ce-course/{job_id}/study_guide.docx"


def test_lazy_backfill_idempotent_and_concurrent_safe(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db)
    seed = PipelineVersionSeedService(db)
    first = seed.ensure_pipeline_version_one(job_id, course_id, run_id)
    db.commit()
    second = seed.ensure_pipeline_version_one(job_id, course_id, run_id)
    db.commit()
    assert first.id == second.id
    assert CourseContentVersionRepository(db).max_version_number(job_id) == 1


def test_lazy_backfill_missing_json_blocks(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db, with_artifacts=False)
    db.add(
        CourseGenerationJobArtifact(
            job_id=job_id,
            course_run_id=run_id,
            artifact_type=ARTIFACT_TYPE_STUDY_GUIDE,
            stage_name="content_generation",
            file_name="study_guide.docx",
            blob_path=f"slug/{job_id}/study_guide.docx",
            content_type="application/octet-stream",
        )
    )
    db.commit()
    with pytest.raises(PipelineVersionArtifactsMissingError, match="course_content.json"):
        PipelineVersionSeedService(db).ensure_pipeline_version_one(
            job_id, course_id, run_id
        )


def test_lazy_backfill_missing_docx_blocks(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db, with_artifacts=False)
    db.add(
        CourseGenerationJobArtifact(
            job_id=job_id,
            course_run_id=run_id,
            artifact_type=ARTIFACT_TYPE_COURSE_CONTENT,
            stage_name="content_generation",
            file_name="course_content.json",
            blob_path=f"slug/{job_id}/course_content.json",
            content_type="application/json",
        )
    )
    db.commit()
    with pytest.raises(PipelineVersionArtifactsMissingError, match="study_guide.docx"):
        PipelineVersionSeedService(db).ensure_pipeline_version_one(
            job_id, course_id, run_id
        )


def test_lazy_backfill_does_not_overwrite_existing_available_v1(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db)
    db.add(
        CourseContentVersion(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            canonical_json_blob_path="original/path.json",
            docx_blob_path="original/path.docx",
            created_by="pipeline",
            completed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    version = PipelineVersionSeedService(db).ensure_pipeline_version_one(
        job_id, course_id, run_id
    )
    assert version.canonical_json_blob_path == "original/path.json"


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


def test_save_on_legacy_job_backfills_v1_and_returns_v2(db: Session):
    """Old completed job with flat artifacts and no version rows → first save is v2."""
    course_id, run_id, job_id = _seed_completed_job(db)

    content = MagicMock()
    content.load_canonical_state.return_value = CanonicalCourseState(
        canonical_a2={"course_title": "Annuity CE Course", "sections": [{"section_id": "s"}]},
        learning_objectives=["LO1"],
        course_title="Annuity CE Course",
        source="course_content_artifact",
    )
    transformer = MagicMock()
    transformer.transform.return_value = _transformed()
    docx = MagicMock()
    docx.render_from_a2.return_value = RenderedDocx(content=b"PK", filename="x.docx")
    artifacts = MagicMock()
    artifacts.upload_bytes_no_overwrite.side_effect = lambda path, *_a, **_k: path

    service = SaveToAzureService(
        db,
        content_service=content,
        transformation_service=transformer,
        docx_service=docx,
        artifact_service=artifacts,
    )
    result = service.save(
        job_id=job_id,
        course_snapshot=_snapshot(),
        created_by="editor@example.com",
    )

    assert result.version_number == 2
    repo = CourseContentVersionRepository(db)
    v1 = repo.get_version_one(job_id)
    assert v1 is not None
    assert v1.source_type == CONTENT_VERSION_SOURCE_PIPELINE
    assert v1.canonical_json_blob_path.endswith("/course_content.json")
    assert "/v1/" not in (v1.canonical_json_blob_path or "")
    v2 = repo.get_by_job_and_version(job_id, 2)
    assert v2 is not None
    assert v2.source_type == CONTENT_VERSION_SOURCE_EDITOR_SAVE
    assert f"/v2/" in (v2.canonical_json_blob_path or "")
    # Previous (pipeline) paths unchanged.
    assert v1.canonical_json_blob_path == f"annuity-ce-course/{job_id}/course_content.json"


def test_save_on_pipeline_seeded_job_returns_v2_then_v3(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db)
    seed = PipelineVersionSeedService(db)
    seed.ensure_pipeline_version_one(job_id, course_id, run_id)
    db.commit()

    content = MagicMock()
    content.load_canonical_state.return_value = CanonicalCourseState(
        canonical_a2={"course_title": "Annuity CE Course", "sections": [{"section_id": "s"}]},
        learning_objectives=["LO1"],
        course_title="Annuity CE Course",
        source="version",
    )
    transformer = MagicMock()
    transformer.transform.return_value = _transformed()
    docx = MagicMock()
    docx.render_from_a2.return_value = RenderedDocx(content=b"PK", filename="x.docx")
    artifacts = MagicMock()
    artifacts.upload_bytes_no_overwrite.side_effect = lambda path, *_a, **_k: path

    service = SaveToAzureService(
        db,
        content_service=content,
        transformation_service=transformer,
        docx_service=docx,
        artifact_service=artifacts,
    )
    first = service.save(job_id=job_id, course_snapshot=_snapshot(), created_by="ed")
    assert first.version_number == 2
    second = service.save(job_id=job_id, course_snapshot=_snapshot(), created_by="ed")
    assert second.version_number == 3

    repo = CourseContentVersionRepository(db)
    assert repo.get_version_one(job_id).canonical_json_blob_path.endswith(
        "/course_content.json"
    )
    assert "/v1/" not in repo.get_version_one(job_id).canonical_json_blob_path


def test_save_fails_clearly_when_no_versions_and_missing_pipeline_artifacts(db: Session):
    course_id, run_id, job_id = _seed_completed_job(db, with_artifacts=False)
    content = MagicMock()
    content.load_canonical_state.return_value = CanonicalCourseState(
        canonical_a2={"course_title": "T", "sections": [{"section_id": "s"}]},
        learning_objectives=[],
        course_title="T",
        source="course_content_artifact",
    )
    transformer = MagicMock()
    transformer.transform.return_value = _transformed()
    docx = MagicMock()
    docx.render_from_a2.return_value = RenderedDocx(content=b"PK", filename="x.docx")

    service = SaveToAzureService(
        db,
        content_service=content,
        transformation_service=transformer,
        docx_service=docx,
        artifact_service=MagicMock(),
    )
    with pytest.raises(SaveToAzureError, match="Version 1 artifacts"):
        service.save(job_id=job_id, course_snapshot=_snapshot(), created_by="ed")
    assert CourseContentVersionRepository(db).has_any_version(job_id) is False
