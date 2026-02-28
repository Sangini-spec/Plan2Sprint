"""add_sprint_plan_ai_fields

Revision ID: 3beeed7119fe
Revises: c5d8e2f17a03
Create Date: 2026-02-25 21:41:37.841099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3beeed7119fe'
down_revision: Union[str, None] = 'c5d8e2f17a03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to sprint_plans
    op.add_column(
        "sprint_plans",
        sa.Column("project_id", sa.String(25), sa.ForeignKey("imported_projects.id"), nullable=True),
    )
    op.add_column(
        "sprint_plans",
        sa.Column("overall_rationale", sa.String(), nullable=True),
    )
    op.add_column(
        "sprint_plans",
        sa.Column("goal_attainment_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "sprint_plans",
        sa.Column("tool", sa.String(10), nullable=True),
    )
    op.add_column(
        "sprint_plans",
        sa.Column("human_edits", sa.JSON(), nullable=True),
    )

    # Create user_project_preferences table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_project_preferences (
            id VARCHAR(25) PRIMARY KEY,
            user_id VARCHAR NOT NULL UNIQUE,
            organization_id VARCHAR(25) NOT NULL,
            selected_project_id VARCHAR(25) REFERENCES imported_projects(id),
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            CONSTRAINT uq_user_project_pref UNIQUE (user_id)
        )
    """)


def downgrade() -> None:
    op.drop_column("sprint_plans", "human_edits")
    op.drop_column("sprint_plans", "tool")
    op.drop_column("sprint_plans", "goal_attainment_confidence")
    op.drop_column("sprint_plans", "overall_rationale")
    op.drop_column("sprint_plans", "project_id")
    op.drop_table("user_project_preferences")
