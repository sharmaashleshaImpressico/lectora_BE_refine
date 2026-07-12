"""Phase 6 hardening: failure modes, concurrency, and consistency errors."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.course_generation.course_generation_job.constants import (
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
    CourseContentConsistencyError,
    CourseContentService,
)
from app.services.onboarding.course_generation.docx_render_service import RenderedDocx
from app.services.onboarding.course_generation.editor_course_transformation_service import (
    EditorTransformationResult,
)
from app.services.onboarding.course_generation.save_to_azure_service import (
    SaveToAzureError,
    SaveToAzureFailedError,
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


def _seed(db: Session) -> tuple[int, int, int]:
    course = CourseBasic(
        title="Concurrency Course",
        course_code="C-1",
        course_type="Insurance CE",
        status_code="DRAFT",
        created_by="t",
    )
    db.add(course)
    db.flush()
    run = CourseRun(
        course_id=course.id, version_number=1, status_code="DRAFT", created_by="t"
    )
    db.add(run)
    db.flush()
    job = CourseGenerationJob(
        course_run_id=run.id, status_code=JOB_STATUS_COMPLETED, requested_by="t"
    )
    db.add(job)
    db.flush()
    db.add(
        CourseContentVersion(
            job_id=job.id,
            course_id=course.id,
            course_run_id=run.id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            canonical_json_blob_path="slug/1/course_content.json",
            docx_blob_path="slug/1/study_guide.docx",
            created_by="pipeline",
            completed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return course.id, run.id, job.id


def test_concurrent_reserve_allocates_distinct_versions(tmp_path):
    db_file = tmp_path / "concurrent.db"
    eng = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
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
            CourseContentVersion.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    setup = SessionLocal()
    try:
        for code, name in (
            (JOB_STATUS_PENDING, "Pending"),
            (JOB_STATUS_COMPLETED, "Completed"),
        ):
            setup.add(
                CourseGenerationJobStatus(
                    code=code, name=name, description=name, is_active=True
                )
            )
        setup.commit()
        course_id, run_id, job_id = _seed(setup)
    finally:
        setup.close()

    results: list[int] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        session = SessionLocal()
        try:
            repo = CourseContentVersionRepository(session)
            barrier.wait(timeout=5)
            row = repo.reserve_next_version(
                job_id=job_id,
                course_id=course_id,
                course_run_id=run_id,
                source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
                created_by="concurrent",
            )
            session.commit()
            results.append(int(row.version_number))
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    eng.dispose()

    assert not errors, errors
    assert sorted(results) == [2, 3]
    # Completion order may differ from version-number order — flag for optimistic concurrency.
    assert set(results) == {2, 3}


def test_docx_failure_before_reserve_leaves_previous_available(db: Session):
    """DOCX is generated before reservation — failure creates no FAILED row."""
    course_id, run_id, job_id = _seed(db)
    service = SaveToAzureService(db)
    service.content = MagicMock()
    service.content.load_canonical_state.return_value = CanonicalCourseState(
        canonical_a2={"course_title": "T", "sections": [{"section_id": "s"}]},
        learning_objectives=[],
        course_title="T",
        source="version",
    )
    service.transformer = MagicMock()
    service.transformer.transform.return_value = EditorTransformationResult(
        canonical_a2={"course_title": "T", "sections": [{"section_id": "s"}]},
        learning_objectives=[],
        course_title="T",
        meta={
            "totalWordCount": 1,
            "sectionCount": 1,
            "chapterCount": 1,
            "estimatedReadTime": "1",
        },
    )
    service.docx = MagicMock()
    service.docx.render_from_a2.side_effect = RuntimeError("docx boom")
    service.version_seed = MagicMock()
    service.version_seed.ensure_pipeline_version_one.return_value = SimpleNamespace(
        id=1, version_number=1
    )
    service.versions = CourseContentVersionRepository(db)
    service.jobs = MagicMock()
    service.jobs.get_by_id.return_value = SimpleNamespace(
        id=job_id, course_run_id=run_id, status_code=JOB_STATUS_COMPLETED
    )
    service.course_runs = MagicMock()
    service.course_runs.get_by_id.return_value = SimpleNamespace(
        id=run_id, course_id=course_id
    )
    service.courses = MagicMock()
    service.courses.get_by_id.return_value = SimpleNamespace(
        id=course_id, title="Concurrency Course"
    )

    with pytest.raises(SaveToAzureError, match="DOCX"):
        service.save(
            job_id=job_id,
            course_snapshot=RenderDocxRequest(
                courseTitle="T",
                sections=[CourseSectionInput(id="s", title="S", level=1, content="x")],
            ),
            created_by="ed",
        )

    repo = CourseContentVersionRepository(db)
    assert repo.max_version_number(job_id) == 1
    assert repo.get_latest_available(job_id).version_number == 1
    assert repo.get_by_job_and_version(job_id, 2) is None


def test_json_upload_failure_marks_failed_and_latest_unchanged():
    from tests.course_generation.test_save_to_azure_service import _build_service, _snapshot

    service, deps = _build_service()
    deps["artifacts"].upload_bytes_no_overwrite.side_effect = RuntimeError(
        "json upload failed"
    )
    with pytest.raises(SaveToAzureFailedError) as exc:
        service.save(job_id=1, course_snapshot=_snapshot(), created_by="u")
    assert exc.value.version_number == 2
    deps["versions"].mark_failed.assert_called_once()
    deps["versions"].mark_available.assert_not_called()


def test_missing_latest_blob_does_not_silently_fallback():
    from app.services.onboarding.course_generation.course_content_service import (
        CourseContentNotFoundError,
    )

    svc = CourseContentService(MagicMock())
    svc.versions = MagicMock()
    svc.artifacts = MagicMock()
    svc.versions.get_latest_available.return_value = SimpleNamespace(
        version_number=3,
        canonical_json_blob_path="slug/1/v3/missing.json",
    )
    svc.artifacts.list_by_job.return_value = [
        SimpleNamespace(
            artifact_type="course_content",
            blob_path="slug/1/course_content.json",
            course_run_id=1,
        )
    ]
    svc._resolve_course_type = MagicMock(return_value="")
    svc._read_json = MagicMock(side_effect=CourseContentNotFoundError("missing"))
    with pytest.raises(CourseContentConsistencyError, match="missing blob"):
        svc.get_course_content("1")
