"""Tests for CourseContentVersion model and repository (Phase 1 versioning)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.course_generation.course_generation_job.constants import (
    CONTENT_VERSION_ERROR_MESSAGE_MAX_LENGTH,
    CONTENT_VERSION_SOURCE_EDITOR_SAVE,
    CONTENT_VERSION_SOURCE_PIPELINE,
    CONTENT_VERSION_STATUS_AVAILABLE,
    CONTENT_VERSION_STATUS_CREATING,
    CONTENT_VERSION_STATUS_FAILED,
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
    InvalidVersionStatusTransitionError,
    VersionAllocationError,
    VersionNotFoundError,
)


def _enable_sqlite_fks(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", _enable_sqlite_fks)
    # Ensure PRAGMA applies on the first connection used by create_all.
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
    session.add(
        CourseGenerationJobStatus(
            code=JOB_STATUS_PENDING,
            name="Pending",
            description="Pending",
            is_active=True,
        )
    )
    session.add(
        CourseGenerationJobStatus(
            code=JOB_STATUS_COMPLETED,
            name="Completed",
            description="Completed",
            is_active=True,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def repo(db: Session) -> CourseContentVersionRepository:
    return CourseContentVersionRepository(db)


def _seed_course_graph(db: Session, *, title: str = "Test Course") -> tuple[int, int, int]:
    """Create course → run → job and return (course_id, course_run_id, job_id)."""
    course = CourseBasic(
        title=title,
        course_code="TST-001",
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
    db.commit()
    return course.id, course_run.id, job.id


# ─── Model / schema ───────────────────────────────────────────────────────────


def test_table_and_constraints_registered(engine):
    inspector = inspect(engine)
    assert "course_content_versions" in inspector.get_table_names()

    unique = {
        tuple(sorted(u["column_names"]))
        for u in inspector.get_unique_constraints("course_content_versions")
    }
    # SQLite may also surface the unique as an index; accept either.
    indexes = {
        tuple(idx["column_names"])
        for idx in inspector.get_indexes("course_content_versions")
    }
    assert ("job_id", "version_number") in unique or ("job_id", "version_number") in {
        tuple(c) for c in unique
    } or any(cols == ("job_id", "version_number") for cols in indexes)

    index_names = {idx["name"] for idx in inspector.get_indexes("course_content_versions")}
    assert "ix_course_content_versions_job_id_version_number" in index_names
    assert "ix_course_content_versions_job_id_status_version" in index_names


def test_create_valid_version_row(db: Session):
    course_id, run_id, job_id = _seed_course_graph(db)
    before = datetime.now(timezone.utc)
    row = CourseContentVersion(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        version_number=1,
        status_code=CONTENT_VERSION_STATUS_CREATING,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="pipeline",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    assert row.id is not None
    assert row.created_at is not None
    # SQLite may return naive UTC; compare as aware when possible.
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    assert created >= before.replace(microsecond=0)
    assert row.completed_at is None
    assert row.canonical_json_blob_path is None
    assert row.docx_blob_path is None


def test_unique_job_version_enforced(db: Session):
    course_id, run_id, job_id = _seed_course_graph(db)
    db.add(
        CourseContentVersion(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            created_by="a",
        )
    )
    db.commit()

    db.add(
        CourseContentVersion(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_CREATING,
            source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
            created_by="b",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_foreign_keys_require_valid_parents(db: Session):
    with pytest.raises(IntegrityError):
        db.add(
            CourseContentVersion(
                job_id=99999,
                course_id=99999,
                course_run_id=99999,
                version_number=1,
                status_code=CONTENT_VERSION_STATUS_CREATING,
                source_type=CONTENT_VERSION_SOURCE_PIPELINE,
                created_by="tester",
            )
        )
        db.flush()
    db.rollback()


# ─── Repository queries ───────────────────────────────────────────────────────


def test_latest_available_none_when_empty(repo: CourseContentVersionRepository, db: Session):
    _, _, job_id = _seed_course_graph(db)
    assert repo.get_latest_available(job_id) is None
    assert repo.list_available_versions(job_id) == []


def test_latest_available_returns_highest_available(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)
    for n, status in (
        (1, CONTENT_VERSION_STATUS_AVAILABLE),
        (2, CONTENT_VERSION_STATUS_AVAILABLE),
        (3, CONTENT_VERSION_STATUS_FAILED),
    ):
        db.add(
            CourseContentVersion(
                job_id=job_id,
                course_id=course_id,
                course_run_id=run_id,
                version_number=n,
                status_code=status,
                source_type=CONTENT_VERSION_SOURCE_PIPELINE
                if n == 1
                else CONTENT_VERSION_SOURCE_EDITOR_SAVE,
                created_by="tester",
            )
        )
    db.commit()

    latest = repo.get_latest_available(job_id)
    assert latest is not None
    assert latest.version_number == 2
    assert latest.status_code == CONTENT_VERSION_STATUS_AVAILABLE

    listed = repo.list_available_versions(job_id)
    assert [v.version_number for v in listed] == [2, 1]


def test_get_by_job_and_version_and_job_isolation(
    repo: CourseContentVersionRepository, db: Session
):
    course_a, run_a, job_a = _seed_course_graph(db, title="Course A")
    course_b, run_b, job_b = _seed_course_graph(db, title="Course B")

    db.add(
        CourseContentVersion(
            job_id=job_a,
            course_id=course_a,
            course_run_id=run_a,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            created_by="a",
        )
    )
    db.add(
        CourseContentVersion(
            job_id=job_b,
            course_id=course_b,
            course_run_id=run_b,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            created_by="b",
        )
    )
    db.commit()

    found = repo.get_by_job_and_version(job_a, 1)
    assert found is not None
    assert found.job_id == job_a
    assert repo.get_by_job_and_version(job_a, 99) is None
    assert all(v.job_id == job_a for v in repo.list_available_versions(job_a))


# ─── Reservation ──────────────────────────────────────────────────────────────


def test_reserve_first_and_second_version(repo: CourseContentVersionRepository, db: Session):
    course_id, run_id, job_id = _seed_course_graph(db)

    v1 = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="pipeline-user",
    )
    db.commit()
    assert v1.version_number == 1
    assert v1.status_code == CONTENT_VERSION_STATUS_CREATING
    assert v1.job_id == job_id
    assert v1.course_id == course_id
    assert v1.course_run_id == run_id
    assert v1.source_type == CONTENT_VERSION_SOURCE_PIPELINE
    assert v1.created_by == "pipeline-user"

    v2 = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
        created_by="editor-user",
    )
    db.commit()
    assert v2.version_number == 2
    assert v2.source_type == CONTENT_VERSION_SOURCE_EDITOR_SAVE


def test_failed_versions_are_not_reused(repo: CourseContentVersionRepository, db: Session):
    course_id, run_id, job_id = _seed_course_graph(db)
    for n in (1, 2, 3):
        db.add(
            CourseContentVersion(
                job_id=job_id,
                course_id=course_id,
                course_run_id=run_id,
                version_number=n,
                status_code=(
                    CONTENT_VERSION_STATUS_FAILED
                    if n == 3
                    else CONTENT_VERSION_STATUS_AVAILABLE
                ),
                source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
                created_by="tester",
            )
        )
    db.commit()

    nxt = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
        created_by="tester",
    )
    assert nxt.version_number == 4


def test_versions_scoped_independently_per_job(
    repo: CourseContentVersionRepository, db: Session
):
    c1, r1, j1 = _seed_course_graph(db, title="One")
    c2, r2, j2 = _seed_course_graph(db, title="Two")

    a = repo.reserve_next_version(
        job_id=j1,
        course_id=c1,
        course_run_id=r1,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="u",
    )
    b = repo.reserve_next_version(
        job_id=j2,
        course_id=c2,
        course_run_id=r2,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="u",
    )
    db.commit()
    assert a.version_number == 1
    assert b.version_number == 1
    assert a.job_id != b.job_id


# ─── Status transitions ───────────────────────────────────────────────────────


def test_mark_available_and_failed(repo: CourseContentVersionRepository, db: Session):
    course_id, run_id, job_id = _seed_course_graph(db)
    creating = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="u",
    )
    db.commit()

    available = repo.mark_available(
        creating.id,
        canonical_json_blob_path="slug/1/v1/course_content.json",
        docx_blob_path="slug/1/v1/study_guide.docx",
    )
    db.commit()
    assert available.status_code == CONTENT_VERSION_STATUS_AVAILABLE
    assert available.canonical_json_blob_path.endswith("course_content.json")
    assert available.docx_blob_path.endswith("study_guide.docx")
    assert available.completed_at is not None
    assert available.error_message is None
    assert repo.get_latest_available(job_id).id == available.id

    failed_row = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
        created_by="u",
    )
    db.commit()
    failed = repo.mark_failed(failed_row.id, error_message="upload blew up")
    db.commit()
    assert failed.status_code == CONTENT_VERSION_STATUS_FAILED
    assert failed.error_message == "upload blew up"
    assert failed.completed_at is not None
    assert repo.get_latest_available(job_id).version_number == 1


def test_error_message_truncated(repo: CourseContentVersionRepository, db: Session):
    course_id, run_id, job_id = _seed_course_graph(db)
    row = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="u",
    )
    db.commit()
    huge = "x" * (CONTENT_VERSION_ERROR_MESSAGE_MAX_LENGTH + 500)
    failed = repo.mark_failed(row.id, error_message=huge)
    assert len(failed.error_message) == CONTENT_VERSION_ERROR_MESSAGE_MAX_LENGTH
    assert failed.error_message.endswith("...")


def test_mark_unknown_id_raises(repo: CourseContentVersionRepository):
    with pytest.raises(VersionNotFoundError):
        repo.mark_available(
            999999,
            canonical_json_blob_path="a.json",
            docx_blob_path="a.docx",
        )
    with pytest.raises(VersionNotFoundError):
        repo.mark_failed(999999, error_message="nope")


def test_cannot_transition_available_back_to_creating_via_mark(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)
    row = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="u",
    )
    db.commit()
    repo.mark_available(
        row.id,
        canonical_json_blob_path="a.json",
        docx_blob_path="a.docx",
    )
    db.commit()

    with pytest.raises(InvalidVersionStatusTransitionError):
        repo.mark_available(
            row.id,
            canonical_json_blob_path="b.json",
            docx_blob_path="b.docx",
        )
    with pytest.raises(InvalidVersionStatusTransitionError):
        repo.mark_failed(row.id, error_message="should not work")


# ─── Concurrency / collision handling ─────────────────────────────────────────


def test_two_allocations_distinct_version_numbers(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)
    first = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_PIPELINE,
        created_by="u1",
    )
    second = repo.reserve_next_version(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
        created_by="u2",
    )
    db.commit()
    assert {first.version_number, second.version_number} == {1, 2}


def test_uniqueness_conflict_retries_successfully(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)
    # Seed v1 so the first computed next is 2.
    db.add(
        CourseContentVersion(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            created_by="seed",
        )
    )
    db.commit()

    call_count = {"n": 0}
    real_flush = db.flush

    def flaky_flush(*args, **kwargs):
        call_count["n"] += 1
        # First flush inside reserve (attempt 1) collides; later flushes succeed.
        if call_count["n"] == 1:
            raise IntegrityError(
                "INSERT",
                {},
                Exception(
                    "UNIQUE constraint failed: "
                    "course_content_versions.job_id, "
                    "course_content_versions.version_number"
                ),
            )
        return real_flush(*args, **kwargs)

    with patch.object(db, "flush", side_effect=flaky_flush):
        reserved = repo.reserve_next_version(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
            created_by="editor",
        )

    assert reserved.version_number >= 2
    assert call_count["n"] >= 2


def test_unrelated_integrity_error_is_not_retried_as_collision(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)

    def boom(*_args, **_kwargs):
        raise IntegrityError(
            "INSERT",
            {},
            Exception("FOREIGN KEY constraint failed"),
        )

    with patch.object(db, "flush", side_effect=boom):
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            repo.reserve_next_version(
                job_id=job_id,
                course_id=course_id,
                course_run_id=run_id,
                source_type=CONTENT_VERSION_SOURCE_PIPELINE,
                created_by="u",
            )


def test_allocation_exhaustion_raises(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)

    def always_collide(*_args, **_kwargs):
        raise IntegrityError(
            "INSERT",
            {},
            Exception(
                "UNIQUE constraint failed: "
                "course_content_versions.job_id, "
                "course_content_versions.version_number"
            ),
        )

    with patch.object(db, "flush", side_effect=always_collide):
        with pytest.raises(VersionAllocationError):
            repo.reserve_next_version(
                job_id=job_id,
                course_id=course_id,
                course_run_id=run_id,
                source_type=CONTENT_VERSION_SOURCE_PIPELINE,
                created_by="u",
            )


def test_collision_detector_helpers():
    unique_exc = IntegrityError(
        "stmt",
        {},
        Exception("uq_course_content_versions_job_id_version_number"),
    )
    fk_exc = IntegrityError("stmt", {}, Exception("FOREIGN KEY constraint failed"))
    assert CourseContentVersionRepository._is_version_number_collision(unique_exc) is True
    assert CourseContentVersionRepository._is_version_number_collision(fk_exc) is False


# ─── Pipeline Version 1 seed (Phase 5) ─────────────────────────────────────────


def test_register_pipeline_version_one_creates_available_pipeline(
    repo: CourseContentVersionRepository, db: Session
):
    from app.repositories.course_generation.course_content_version_repository import (
        PipelineVersionConflictError,
    )

    course_id, run_id, job_id = _seed_course_graph(db)
    row = repo.register_pipeline_version_one(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        canonical_json_blob_path="slug/1/course_content.json",
        docx_blob_path="slug/1/study_guide.docx",
        created_by="pipeline",
    )
    db.commit()

    assert row.version_number == 1
    assert row.status_code == CONTENT_VERSION_STATUS_AVAILABLE
    assert row.source_type == CONTENT_VERSION_SOURCE_PIPELINE
    assert row.canonical_json_blob_path.endswith("course_content.json")
    assert row.docx_blob_path.endswith("study_guide.docx")
    assert row.completed_at is not None
    assert repo.get_version_one(job_id).id == row.id
    assert repo.has_any_version(job_id) is True

    # Idempotent retry — same paths, no second row.
    again = repo.register_pipeline_version_one(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        canonical_json_blob_path="slug/1/course_content.json",
        docx_blob_path="slug/1/study_guide.docx",
        created_by="pipeline",
    )
    db.commit()
    assert again.id == row.id
    assert repo.max_version_number(job_id) == 1

    # Editor-created Version 1 must not be replaced.
    db.query(CourseContentVersion).filter_by(id=row.id).update(
        {"source_type": CONTENT_VERSION_SOURCE_EDITOR_SAVE}
    )
    db.commit()
    with pytest.raises(PipelineVersionConflictError, match="editor save"):
        repo.register_pipeline_version_one(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            canonical_json_blob_path="x",
            docx_blob_path="y",
            created_by="pipeline",
        )


def test_register_pipeline_version_one_repairs_failed_pipeline_seed(
    repo: CourseContentVersionRepository, db: Session
):
    course_id, run_id, job_id = _seed_course_graph(db)
    db.add(
        CourseContentVersion(
            job_id=job_id,
            course_id=course_id,
            course_run_id=run_id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_FAILED,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            created_by="pipeline",
            error_message="partial",
        )
    )
    db.commit()

    repaired = repo.register_pipeline_version_one(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        canonical_json_blob_path="slug/1/course_content.json",
        docx_blob_path="slug/1/study_guide.docx",
        created_by="pipeline",
    )
    db.commit()
    assert repaired.status_code == CONTENT_VERSION_STATUS_AVAILABLE
    assert repaired.error_message is None
    assert repaired.canonical_json_blob_path.endswith("course_content.json")
    assert repo.max_version_number(job_id) == 1


def test_register_pipeline_version_one_rejects_inconsistent_course_links(
    repo: CourseContentVersionRepository, db: Session
):
    from app.repositories.course_generation.course_content_version_repository import (
        PipelineVersionConflictError,
    )

    course_id, run_id, job_id = _seed_course_graph(db)
    other_course, other_run, _ = _seed_course_graph(db, title="Other")
    repo.register_pipeline_version_one(
        job_id=job_id,
        course_id=course_id,
        course_run_id=run_id,
        canonical_json_blob_path="a.json",
        docx_blob_path="a.docx",
        created_by="pipeline",
    )
    db.commit()
    with pytest.raises(PipelineVersionConflictError, match="linked to"):
        repo.register_pipeline_version_one(
            job_id=job_id,
            course_id=other_course,
            course_run_id=other_run,
            canonical_json_blob_path="b.json",
            docx_blob_path="b.docx",
            created_by="pipeline",
        )
