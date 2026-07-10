"""add course run tracking tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-06 00:00:00.000000

Creates Course Generator run-level tracking tables:
  - course_run_status         — lookup table seeded with run lifecycle status codes
  - course_runs               — one user-level generation attempt/version per course
  - course_run_specs          — onboarding/specification metadata per run
  - course_run_rule_overrides — per-run rule overrides
  - course_run_inputs         — uploaded/supporting files per run
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
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


_COURSE_RUN_STATUS_SEED_ROWS = [
    {
        "code": "DRAFT",
        "name": "Draft",
        "description": "User is still filling or editing the course creation input flow.",
        "is_active": True,
    },
    {
        "code": "GENERATING",
        "name": "Generating",
        "description": "Course generation job is currently running for this course run.",
        "is_active": True,
    },
    {
        "code": "GENERATED",
        "name": "Generated",
        "description": "Course run generated successfully.",
        "is_active": True,
    },
    {
        "code": "FAILED",
        "name": "Failed",
        "description": (
            "Course run failed due to a technical, pipeline, or final validation failure."
        ),
        "is_active": True,
    },
    {
        "code": "CANCELLED",
        "name": "Cancelled",
        "description": "Course run was cancelled by the user or system.",
        "is_active": True,
    },
]


def upgrade() -> None:
    op.create_table(
        "course_run_status",
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

    course_run_status_table = sa.table(
        "course_run_status",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(course_run_status_table, _COURSE_RUN_STATUS_SEED_ROWS)

    op.create_table(
        "course_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("created_from_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "status_code",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
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
            ["course_id"],
            ["courses.id"],
            name="fk_course_runs_course_id_courses",
        ),
        sa.ForeignKeyConstraint(
            ["status_code"],
            ["course_run_status.code"],
            name="fk_course_runs_status_code_course_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_from_run_id"],
            ["course_runs.id"],
            name="fk_course_runs_created_from_run_id_course_runs",
        ),
        sa.UniqueConstraint(
            "course_id",
            "version_number",
            name="uq_course_runs_course_id_version_number",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_runs_course_id",
        "course_runs",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_runs_status_code",
        "course_runs",
        ["status_code"],
        unique=False,
    )
    op.create_index(
        "ix_course_runs_created_at",
        "course_runs",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "course_run_specs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column("course_scope", sa.Text(), nullable=True),
        sa.Column("duration_hours", sa.Float(), nullable=True),
        sa.Column("difficulty_level", sa.String(length=100), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("learner_experience_level", sa.String(length=100), nullable=True),
        sa.Column("learner_outcomes", sa.Text(), nullable=True),
        sa.Column("required_topics_json", sa.Text(), nullable=True),
        sa.Column("learning_objectives_json", sa.Text(), nullable=True),
        sa.Column("tone", sa.String(length=255), nullable=True),
        sa.Column("depth", sa.String(length=100), nullable=True),
        sa.Column("emphasis", sa.Text(), nullable=True),
        sa.Column("avoid_instructions", sa.Text(), nullable=True),
        sa.Column("include_case_studies", sa.Boolean(), nullable=True),
        sa.Column("include_examples", sa.Boolean(), nullable=True),
        sa.Column("course_structure_mode", sa.String(length=100), nullable=True),
        sa.Column("uploaded_outline_blob_path", sa.String(length=512), nullable=True),
        sa.Column("rule_pack_id", sa.String(length=255), nullable=True),
        sa.Column("rule_pack_version", sa.String(length=100), nullable=True),
        sa.Column("effective_rule_pack_blob_path", sa.String(length=512), nullable=True),
        sa.Column("outline_notes", sa.Text(), nullable=True),
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
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_run_specs_course_run_id_course_runs",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_run_id",
            name="uq_course_run_specs_course_run_id",
        ),
    )

    op.create_table(
        "course_run_rule_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column("original_value_json", sa.Text(), nullable=True),
        sa.Column("override_value_json", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.ForeignKeyConstraint(
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_run_rule_overrides_course_run_id_course_runs",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_run_rule_overrides_course_run_id",
        "course_run_rule_overrides",
        ["course_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_run_rule_overrides_rule_name",
        "course_run_rule_overrides",
        ["rule_name"],
        unique=False,
    )

    op.create_table(
        "course_run_inputs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_run_id", sa.Integer(), nullable=False),
        sa.Column("input_type", sa.String(length=100), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("blob_path", sa.String(length=1024), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("source_intent", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_timestamp_server_default(),
        ),
        sa.ForeignKeyConstraint(
            ["course_run_id"],
            ["course_runs.id"],
            name="fk_course_run_inputs_course_run_id_course_runs",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_run_inputs_course_run_id",
        "course_run_inputs",
        ["course_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_run_inputs_input_type",
        "course_run_inputs",
        ["input_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_course_run_inputs_input_type", table_name="course_run_inputs")
    op.drop_index("ix_course_run_inputs_course_run_id", table_name="course_run_inputs")
    op.drop_table("course_run_inputs")

    op.drop_index(
        "ix_course_run_rule_overrides_rule_name",
        table_name="course_run_rule_overrides",
    )
    op.drop_index(
        "ix_course_run_rule_overrides_course_run_id",
        table_name="course_run_rule_overrides",
    )
    op.drop_table("course_run_rule_overrides")

    op.drop_table("course_run_specs")

    op.drop_index("ix_course_runs_created_at", table_name="course_runs")
    op.drop_index("ix_course_runs_status_code", table_name="course_runs")
    op.drop_index("ix_course_runs_course_id", table_name="course_runs")
    op.drop_table("course_runs")

    op.drop_table("course_run_status")
