"""Recreate courses.id as INT IDENTITY.

The legacy table used VARCHAR(64) ids with no default. The ORM expects
Azure SQL to assign integer primary keys via IDENTITY(1,1).

Revision ID: 20260707_001
Revises:
Create Date: 2026-07-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260707_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "courses" not in inspector.get_table_names():
        op.create_table(
            "courses",
            sa.Column("id", sa.Integer(), sa.Identity(start=1, increment=1), primary_key=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("course_code", sa.String(length=32), nullable=False),
            sa.Column("course_type", sa.String(length=100), nullable=False),
            sa.Column("status_code", sa.String(length=50), nullable=False, server_default="DRAFT"),
            sa.Column("created_by", sa.String(length=255), nullable=False, server_default="system"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["status_code"], ["course_status.code"], name="fk_courses_status_code_course_status"),
        )
        return

    legacy_rows = bind.execute(
        sa.text(
            "SELECT title, course_code, course_type, status_code, created_by, created_at, updated_at "
            "FROM courses"
        )
    ).mappings().all()

    op.drop_constraint("fk_courses_status_code_course_status", "courses", type_="foreignkey")
    op.drop_constraint("pk_courses", "courses", type_="primary")
    op.drop_table("courses")

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), sa.Identity(start=1, increment=1), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("course_code", sa.String(length=32), nullable=False),
        sa.Column("course_type", sa.String(length=100), nullable=False),
        sa.Column("status_code", sa.String(length=50), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["status_code"], ["course_status.code"], name="fk_courses_status_code_course_status"),
    )

    for row in legacy_rows:
        bind.execute(
            sa.text(
                "INSERT INTO courses "
                "(title, course_code, course_type, status_code, created_by, created_at, updated_at) "
                "VALUES (:title, :course_code, :course_type, :status_code, :created_by, :created_at, :updated_at)"
            ),
            {
                "title": row["title"],
                "course_code": row["course_code"] or "CRS-LEGACY",
                "course_type": row["course_type"],
                "status_code": row["status_code"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    legacy_rows = bind.execute(
        sa.text(
            "SELECT id, title, course_code, course_type, status_code, created_by, created_at, updated_at "
            "FROM courses"
        )
    ).mappings().all()

    op.drop_constraint("fk_courses_status_code_course_status", "courses", type_="foreignkey")
    op.drop_constraint("pk_courses", "courses", type_="primary")
    op.drop_table("courses")

    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("course_code", sa.String(length=100), nullable=True),
        sa.Column("course_type", sa.String(length=100), nullable=False),
        sa.Column("status_code", sa.String(length=50), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_courses"),
        sa.ForeignKeyConstraint(["status_code"], ["course_status.code"], name="fk_courses_status_code_course_status"),
    )

    for row in legacy_rows:
        bind.execute(
            sa.text(
                "INSERT INTO courses "
                "(id, title, course_code, course_type, status_code, created_by, created_at, updated_at) "
                "VALUES (:id, :title, :course_code, :course_type, :status_code, :created_by, :created_at, :updated_at)"
            ),
            {
                "id": f"CRS-{int(row['id']):08X}",
                "title": row["title"],
                "course_code": row["course_code"],
                "course_type": row["course_type"],
                "status_code": row["status_code"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
