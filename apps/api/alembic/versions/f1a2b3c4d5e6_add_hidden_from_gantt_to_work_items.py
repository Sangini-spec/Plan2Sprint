"""Sprint E — add work_items.hidden_from_gantt for PO-controlled Gantt visibility.

The Project Plan Gantt becomes unreadable on long-running projects with
dozens of legacy / completed features. PO needs to remove rows from view
without deleting the underlying work item (it's still needed for sprint
history + analytics). This flag is consulted only by the project-plan
dashboard endpoint; it has no effect on sprint planning, capacity, etc.

Server-default false so existing rows backfill cleanly.

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column(
            "hidden_from_gantt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("work_items", "hidden_from_gantt")
