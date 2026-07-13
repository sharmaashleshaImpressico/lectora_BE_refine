"""add course generation job and output tracking tables

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-06 00:00:00.000000

Creates Course Generator job/output tracking tables:
  - course_generation_job_status      — lookup table seeded with job status codes
  - course_generation_jobs            — backend execution records per course run
  - course_generation_job_artifacts   — artifact references produced by a job
  - course_generation_validation_runs — course-level validation history
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_server_default() -> sa.TextClause:
    """Dialect-aware current-timestamp default for DateTime(timezone=True) columns."""
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        return sa.text("SYSDATETIMEOFFSET()")
    return sa.text("CURRENT_TIMESTAMP")


def _bool_true_server_default() -> sa.TextClause:
    """Dialect-aware boolean-true server default."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return sa.text("true")
    return sa.text("1")


_COURSE_GENERATION_JOB_STATUS_SEED_ROWS = [
    {
        "code": "PENDING",
        "name": "Pending",
        "description": "Course generation job has been created but not started.",
        "is_active": True,
    },
    {
        "code": "PROCESSING",
        "name": "Processing",
        "description": "Course generation job is currently running.",
        "is_active": True,
    },
    {
        "code": "COMPLETED",
        "name": "Completed",
        "description": "Course generation job completed successfully.",
        "is_active": True,
    },
    {
        "code": "FAILED",
        "name": "Failed",
        "description": "Course generation job failed due to a technical or pipeline error.",
        "is_active": True,
    },
    {
        "code": "CANCELLED",
        "name": "Cancelled",
        "description": "Course generation job was cancelled by the user or system.",
        "is_active": True,
    },
]


def upgrade() -> None:
    op.create_table(
        "course_generation_job_status",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=_bool_true_server_default(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.PrimaryKeyConstraint("code"),
    )

    course_generation_job_status_table = sa.table(
        "course_generation_job_status",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        course_generation_job_status_table,
        _COURSE_GENERATION_JOB_STATUS_SEED_ROWS,
    )

    op.create_table(
        "course_generation_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "status_code",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("shared_state_blob_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_generation_jobs_course_run_id_course_runs",
        ),
        sa.ForeignKeyConstraint(
            ["status_code"],
            ["course_generation_job_status.code"],
            name="fk_course_generation_jobs_status_code_course_generation_job_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_run_id",
            name="uq_course_generation_jobs_course_run_id",
        ),
    )
    op.create_index(
        "ix_course_generation_jobs_status_code",
        "course_generation_jobs",
        ["status_code"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_jobs_created_at",
        "course_generation_jobs",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "course_generation_job_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("stage_name", sa.String(length=50), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("blob_path", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["course_generation_jobs.id"],
            name="fk_course_generation_job_artifacts_job_id_course_generation_jobs",
        ),
        sa.ForeignKeyConstraint(
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_generation_job_artifacts_course_run_id_course_runs",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_generation_job_artifacts_job_id",
        "course_generation_job_artifacts",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_job_artifacts_course_run_id",
        "course_generation_job_artifacts",
        ["course_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_job_artifacts_artifact_type",
        "course_generation_job_artifacts",
        ["artifact_type"],
        unique=False,
    )

    op.create_table(
        "course_generation_validation_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column("validation_type", sa.String(length=100), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=True),
        sa.Column("info_count", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("report_artifact_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["course_generation_jobs.id"],
            name="fk_course_generation_validation_runs_job_id_course_generation_jobs",
        ),
        sa.ForeignKeyConstraint(
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_generation_validation_runs_course_run_id_course_runs",
        ),
        sa.ForeignKeyConstraint(
            ["report_artifact_id"],
            ["course_generation_job_artifacts.id"],
            name=(
                "fk_course_generation_validation_runs_report_artifact_id_"
                "course_generation_job_artifacts"
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_generation_validation_runs_job_id",
        "course_generation_validation_runs",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_validation_runs_course_run_id",
        "course_generation_validation_runs",
        ["course_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_validation_runs_validation_type",
        "course_generation_validation_runs",
        ["validation_type"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_validation_runs_status",
        "course_generation_validation_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_course_generation_validation_runs_created_at",
        "course_generation_validation_runs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_generation_validation_runs_created_at",
        table_name="course_generation_validation_runs",
    )
    op.drop_index(
        "ix_course_generation_validation_runs_status",
        table_name="course_generation_validation_runs",
    )
    op.drop_index(
        "ix_course_generation_validation_runs_validation_type",
        table_name="course_generation_validation_runs",
    )
    op.drop_index(
        "ix_course_generation_validation_runs_course_run_id",
        table_name="course_generation_validation_runs",
    )
    op.drop_index(
        "ix_course_generation_validation_runs_job_id",
        table_name="course_generation_validation_runs",
    )
    op.drop_table("course_generation_validation_runs")

    op.drop_index(
        "ix_course_generation_job_artifacts_artifact_type",
        table_name="course_generation_job_artifacts",
    )
    op.drop_index(
        "ix_course_generation_job_artifacts_course_run_id",
        table_name="course_generation_job_artifacts",
    )
    op.drop_index(
        "ix_course_generation_job_artifacts_job_id",
        table_name="course_generation_job_artifacts",
    )
    op.drop_table("course_generation_job_artifacts")

    op.drop_index(
        "ix_course_generation_jobs_created_at",
        table_name="course_generation_jobs",
    )
    op.drop_index(
        "ix_course_generation_jobs_status_code",
        table_name="course_generation_jobs",
    )
    op.drop_table("course_generation_jobs")

    op.drop_table("course_generation_job_status")
