"""add_overdue_alert_tracking

Adds ``last_overdue_alert_target_date`` to ``imported_projects``. We store
the value of ``target_launch_date`` that was active at the moment we
emailed the PO that the project had passed its launch date — that gives
us an idempotency key. The next overdue check fires the email only when
``target_launch_date`` differs from this stored value, so:

  * The email never fires twice for the same target.
  * If the PO sets a NEW target via the dashboard or by approving a new
    plan, and that new target later passes too, a fresh email fires
    once (because the stored value still refers to the old target).

Revision ID: e7f1c8a4b3d2
Revises: d9e1f2a3b4c5
Create Date: 2026-05-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f1c8a4b3d2"
down_revision: Union[str, None] = "d9e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "imported_projects",
        sa.Column(
            "last_overdue_alert_target_date",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("imported_projects", "last_overdue_alert_target_date")
