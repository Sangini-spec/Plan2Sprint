"""add_project_insights_and_suggested_priority

Revision ID: d4a7f3c81e02
Revises: efbc1b0a69b3
Create Date: 2026-03-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a7f3c81e02'
down_revision: Union[str, None] = '3beeed7119fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sprint plan project-level insights
    op.add_column(
        "sprint_plans",
        sa.Column("estimated_weeks_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sprint_plans",
        sa.Column("project_completion_summary", sa.String(), nullable=True),
    )
    op.add_column(
        "sprint_plans",
        sa.Column("capacity_recommendations", sa.JSON(), nullable=True),
    )

    # Assignment-level suggested priority
    op.add_column(
        "plan_assignments",
        sa.Column("suggested_priority", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plan_assignments", "suggested_priority")
    op.drop_column("sprint_plans", "capacity_recommendations")
    op.drop_column("sprint_plans", "project_completion_summary")
    op.drop_column("sprint_plans", "estimated_weeks_total")
