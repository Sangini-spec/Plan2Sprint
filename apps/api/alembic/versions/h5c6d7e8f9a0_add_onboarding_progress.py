"""add_onboarding_progress

Adds the ``users.onboarding_progress`` JSONB column for the Plan2Sprint
product tour. Stores per-user step progress, page-hint dismissals, and
replay state.

Shape:
  {
    "role": "product_owner" | "developer" | "stakeholder",
    "current_step": "sprint-planning-rebalance",
    "completed_steps": ["welcome", "connect-tool", ...],
    "skipped_steps": [],
    "page_hints_seen": ["/po/retro", ...],
    "status": "not_started" | "in_progress" | "completed" | "dismissed",
    "started_at": "2026-05-11T14:32:00Z",
    "completed_at": null,
    "banner_dismissed": false,
    "replay_count": 0
  }

NULL = pristine. Frontend treats NULL as status=not_started and shows
the dismissible re-engagement banner to existing users.

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
Create Date: 2026-05-11 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h5c6d7e8f9a0"
down_revision: Union[str, None] = "g4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "onboarding_progress",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_progress")
