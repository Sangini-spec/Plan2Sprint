"""add_project_phases_and_assignment_rules

Revision ID: e6b2a4f93d17
Revises: d4a7f3c81e02
Create Date: 2026-03-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6b2a4f93d17"
down_revision: Union[str, None] = "d4a7f3c81e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- project_phases --
    op.create_table(
        "project_phases",
        sa.Column("id", sa.String(25), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(25),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(25),
            sa.ForeignKey("imported_projects.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#6366f1"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "is_default", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("project_id", "slug", name="uq_project_phases_proj_slug"),
    )

    # -- phase_assignment_rules --
    op.create_table(
        "phase_assignment_rules",
        sa.Column("id", sa.String(25), primary_key=True),
        sa.Column(
            "phase_id",
            sa.String(25),
            sa.ForeignKey("project_phases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # -- Add phase_id FK to work_items --
    op.add_column(
        "work_items",
        sa.Column(
            "phase_id",
            sa.String(25),
            sa.ForeignKey("project_phases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("work_items", "phase_id")
    op.drop_table("phase_assignment_rules")
    op.drop_table("project_phases")
