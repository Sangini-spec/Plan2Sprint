"""Hotfix 19 — add AI phase classification cache columns to work_items.

When the rules engine can't match a feature title/source_status to any
phase, we fall back to an LLM that reads the feature's description and
acceptance criteria and picks the most appropriate phase semantically.
The result is cached on the work item so we don't pay for the same
classification on every dashboard read.

Three new columns:
  * ``ai_classified_phase_id`` — FK to project_phases, nullable. Points
    at the phase the LLM picked. Cleared (CASCADE SET NULL) if the
    referenced phase is deleted, in which case the feature falls back
    to the rules → status-fallback chain again.
  * ``ai_classified_at`` — when the classification ran, for diagnostics.
  * ``ai_classified_input_hash`` — sha256 of (title + description +
    acceptance_criteria + project's phase slug list). On read, we
    re-hash and compare; if the hash differs (e.g. PO edited the
    description in ADO), we re-run the classifier. If hash matches,
    cache hit, no LLM call.

Revision ID: c8b3a5e7f0d1
Revises: a7c4e1d2b9f3
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa


revision = "c8b3a5e7f0d1"
down_revision = "a7c4e1d2b9f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column(
            "ai_classified_phase_id",
            sa.String(length=25),
            nullable=True,
        ),
    )
    op.add_column(
        "work_items",
        sa.Column(
            "ai_classified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "work_items",
        sa.Column(
            "ai_classified_input_hash",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_work_items_ai_phase",
        "work_items",
        "project_phases",
        ["ai_classified_phase_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_work_items_ai_phase", "work_items", type_="foreignkey")
    op.drop_column("work_items", "ai_classified_input_hash")
    op.drop_column("work_items", "ai_classified_at")
    op.drop_column("work_items", "ai_classified_phase_id")
