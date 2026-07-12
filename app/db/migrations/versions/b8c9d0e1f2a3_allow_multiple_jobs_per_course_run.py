"""allow multiple jobs per course run

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-10 00:00:00.000000

Drops the unique constraint on course_generation_jobs.course_run_id so a
course run can be re-generated (a new job created) more than once, instead
of being permanently limited to exactly one job for its lifetime.

Uses batch_alter_table so the same migration works on SQLite (no ALTER
CONSTRAINT support) and on Azure SQL / other dialects.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("course_generation_jobs") as batch_op:
        batch_op.drop_constraint(
            "uq_course_generation_jobs_course_run_id",
            type_="unique",
        )


def downgrade() -> None:
    with op.batch_alter_table("course_generation_jobs") as batch_op:
        batch_op.create_unique_constraint(
            "uq_course_generation_jobs_course_run_id",
            ["course_run_id"],
        )
