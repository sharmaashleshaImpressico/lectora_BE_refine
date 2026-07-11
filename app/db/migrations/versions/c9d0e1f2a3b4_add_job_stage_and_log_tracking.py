"""add job stage and log tracking tables

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-11 00:00:00.000000

Adds `course_generation_job_stages` and `course_generation_job_logs`, which
back the frontend's live pipeline-progress UI: a REST snapshot
(`GET /jobs/{job_id}`) and an SSE stream (`GET /jobs/{job_id}/events`) both
read from these tables instead of guessing progress from the job's single
overall `status_code`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_server_default() -> sa.TextClause:
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        return sa.text("SYSDATETIMEOFFSET()")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "course_generation_job_stages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("stage_code", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("outcome", sa.String(length=30), nullable=True),
        sa.Column(
            "retry_attempt", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blockers_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["course_generation_jobs.id"],
            name="fk_course_generation_job_stages_job_id_course_generation_jobs",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "stage_code", name="uq_course_generation_job_stages_job_stage"
        ),
    )
    op.create_index(
        "ix_course_generation_job_stages_job_id",
        "course_generation_job_stages",
        ["job_id"],
        unique=False,
    )

    op.create_table(
        "course_generation_job_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column(
            "level", sa.String(length=10), nullable=False, server_default=sa.text("'info'")
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stage_code", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["course_generation_jobs.id"],
            name="fk_course_generation_job_logs_job_id_course_generation_jobs",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_generation_job_logs_job_id",
        "course_generation_job_logs",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_generation_job_logs_job_id", table_name="course_generation_job_logs"
    )
    op.drop_table("course_generation_job_logs")

    op.drop_index(
        "ix_course_generation_job_stages_job_id", table_name="course_generation_job_stages"
    )
    op.drop_table("course_generation_job_stages")
