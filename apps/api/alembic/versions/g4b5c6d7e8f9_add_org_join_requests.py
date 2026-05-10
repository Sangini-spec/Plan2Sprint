"""add_org_join_requests

Adds the ``org_join_requests`` table — owner-approval gate for the
Settings → org-rename canonical-match flow. Phase 1 of Hotfix 85
auto-migrated sole-user orgs into a matched canonical org. Hotfix 86
gates that migration behind founder approval so a stranger can't
acquire access to an existing tenant just by guessing its name.

Lifecycle:
  pending   — created by PATCH /organizations/current when a
              canonical match is found and caller is sole user
  approved  — founder of target_org_id clicked Approve; migration ran
  rejected  — founder declined
  cancelled — requester withdrew before founder acted

Indexes:
  - (target_org_id, status='pending')  — fast lookup of pending
    requests by founder for the Invitations page
  - (requester_user_id, status='pending') — single open request per
    requester (uniqueness enforced at the application layer; SQL
    keeps a partial index for fast lookup)

Revision ID: g4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-05-10 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_join_requests",
        sa.Column("id", sa.String(length=25), primary_key=True),
        sa.Column("requester_user_id", sa.String(length=25), nullable=False),
        sa.Column("requester_email", sa.String(), nullable=False),
        sa.Column("requester_full_name", sa.String(), nullable=True),
        sa.Column("source_org_id", sa.String(length=25), nullable=False),
        sa.Column("target_org_id", sa.String(length=25), nullable=False),
        sa.Column("target_org_name", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id", sa.String(length=25), nullable=True
        ),
        sa.Column("resolution_note", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["requester_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_join_requests_target_pending",
        "org_join_requests",
        ["target_org_id", "status"],
    )
    op.create_index(
        "ix_join_requests_requester_pending",
        "org_join_requests",
        ["requester_user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_join_requests_requester_pending", table_name="org_join_requests"
    )
    op.drop_index(
        "ix_join_requests_target_pending", table_name="org_join_requests"
    )
    op.drop_table("org_join_requests")
