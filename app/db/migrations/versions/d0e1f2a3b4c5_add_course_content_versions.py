"""add course_content_versions table

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-12 00:00:00.000000

Adds `course_content_versions` — immutable study-guide / course-content
revisions scoped to a course-generation job (v1 = pipeline, v2+ = editor saves).

Distinct from `course_runs.version_number` (generation attempts).

Indexes are ascending composites for SQLite + Azure SQL portability; queries
resolve newest / latest-available with `ORDER BY version_number DESC`.
Descending indexes are not used because Alembic/SQLite do not portably
express DESC column directions on all target dialects in this project.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_server_default() -> sa.TextClause:
    """Dialect-aware current-timestamp default for DateTime(timezone=True) columns."""
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        return sa.text("SYSDATETIMEOFFSET()")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "course_content_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status_code",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'CREATING'"),
        ),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("canonical_json_blob_path", sa.String(length=1024), nullable=True),
        sa.Column("docx_blob_path", sa.String(length=1024), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["course_generation_jobs.id"],
            name="fk_course_content_versions_job_id_course_generation_jobs",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_course_content_versions_course_id_courses",
        ),
        sa.ForeignKeyConstraint(
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_content_versions_course_run_id_course_runs",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "version_number",
            name="uq_course_content_versions_job_id_version_number",
        ),
    )
    op.create_index(
        "ix_course_content_versions_job_id_version_number",
        "course_content_versions",
        ["job_id", "version_number"],
        unique=False,
    )
    op.create_index(
        "ix_course_content_versions_job_id_status_version",
        "course_content_versions",
        ["job_id", "status_code", "version_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_content_versions_job_id_status_version",
        table_name="course_content_versions",
    )
    op.drop_index(
        "ix_course_content_versions_job_id_version_number",
        table_name="course_content_versions",
    )
    op.drop_table("course_content_versions")
