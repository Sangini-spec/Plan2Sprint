"""Make audit_log_entries.actor_id nullable for system-initiated events.

System deliveries (daily digests, scheduled nudges) have no real actor user.
Forcing actor_id NOT NULL was crashing the entire delivery pipeline.

Revision ID: 9c3d4e5f6a1b
Revises: 8a9b1c2d3e4f
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "9c3d4e5f6a1b"
down_revision = "8a9b1c2d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_log_entries",
        "actor_id",
        existing_type=sa.String(length=25),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_log_entries",
        "actor_id",
        existing_type=sa.String(length=25),
        nullable=False,
    )
