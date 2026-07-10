"""add course_status and courses tables

Revision ID: e5f6a7b8c9d0
Revises:
Create Date: 2026-07-06 00:00:00.000000

Creates the first Course Generator course-level tables:
  - course_status  — lookup table seeded with lifecycle status codes
  - courses        — course records referencing course_status
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = None
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


_COURSE_STATUS_SEED_ROWS = [
    {
        "code": "DRAFT",
        "name": "Draft",
        "description": "Course setup is in progress. User has not started generation yet.",
        "is_active": True,
    },
    {
        "code": "ACTIVE",
        "name": "Active",
        "description": "Course is active and ready for use.",
        "is_active": True,
    },
    {
        "code": "ARCHIVED",
        "name": "Archived",
        "description": "Course is archived and no longer active.",
        "is_active": True,
    }
]


def upgrade() -> None:
    op.create_table(
        "course_status",
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

    course_status_table = sa.table(
        "course_status",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(course_status_table, _COURSE_STATUS_SEED_ROWS)

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("course_code", sa.String(length=100), nullable=True),
        sa.Column("course_type", sa.String(length=100), nullable=False),
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
            ["status_code"],
            ["course_status.code"],
            name="fk_courses_status_code_course_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_courses_status_code",
        "courses",
        ["status_code"],
        unique=False,
    )
    op.create_index(
        "ix_courses_created_at",
        "courses",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_courses_created_at", table_name="courses")
    op.drop_index("ix_courses_status_code", table_name="courses")
    op.drop_table("courses")
    op.drop_table("course_status")
