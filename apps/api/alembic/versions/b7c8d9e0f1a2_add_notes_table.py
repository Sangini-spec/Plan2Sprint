"""Add notes table for Smart Notes feature.

Private notebook per user: ideas, bugs, feature concepts, decisions, questions.
Attached to a project for context. AI-expandable, shareable to channels.

Revision ID: b7c8d9e0f1a2
Revises: 9c3d4e5f6a1b
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY


revision = "b7c8d9e0f1a2"
down_revision = "9c3d4e5f6a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.String(length=25), primary_key=True),
        sa.Column("organization_id", sa.String(length=25), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("author_email", sa.String(), nullable=False, index=True),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("imported_project_id", sa.String(length=25), sa.ForeignKey("imported_projects.id"), nullable=True, index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False, server_default="idea"),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="blue"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tags", ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notes_author_org", "notes", ["organization_id", "author_email"])


def downgrade() -> None:
    op.drop_index("ix_notes_author_org", table_name="notes")
    op.drop_table("notes")
