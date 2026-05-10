"""Timeline revamp — Sprint 1: target launch date + phase dates + Ready phase.

Adds the data foundation for the PO dashboard timeline rework:
 - imported_projects.target_launch_date          — the enforceable "ship by" date
 - imported_projects.target_launch_source        — "AUTO" | "MANUAL"
 - project_phases.planned_start / planned_end    — persisted per-phase boundaries
 - Seeds a "Ready" phase (sort_order=6) for every project that doesn't have one.

All operations are idempotent — the app's startup auto-migration does the same
work, so this Alembic revision is only for clean offline schema tracking.

Revision ID: a1b2c3d4e5f6
Revises: b7c8d9e0f1a2
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Columns ---------------------------------------------------------
    op.execute("ALTER TABLE imported_projects ADD COLUMN IF NOT EXISTS target_launch_date TIMESTAMPTZ")
    op.execute("ALTER TABLE imported_projects ADD COLUMN IF NOT EXISTS target_launch_source VARCHAR(10)")
    op.execute("ALTER TABLE project_phases    ADD COLUMN IF NOT EXISTS planned_start        TIMESTAMPTZ")
    op.execute("ALTER TABLE project_phases    ADD COLUMN IF NOT EXISTS planned_end          TIMESTAMPTZ")

    # --- Backfill "Ready" phase for every project that doesn't have one --
    # The id is a 25-char string that resembles the cuid output of the Python
    # models (c + 24 hex). Good enough for an admin-inserted row; future rows
    # come from SQLAlchemy default=generate_cuid.
    op.execute(
        """
        INSERT INTO project_phases (
            id, organization_id, project_id, name, slug, color,
            sort_order, is_default, created_at, updated_at
        )
        SELECT
            'c' || substr(md5(random()::text || ip.id), 1, 24),
            ip.organization_id,
            ip.id,
            'Ready',
            'ready',
            '#10b981',
            6,
            FALSE,
            NOW(),
            NOW()
        FROM imported_projects ip
        WHERE NOT EXISTS (
            SELECT 1 FROM project_phases pp
            WHERE pp.project_id = ip.id AND pp.slug = 'ready'
        )
        """
    )


def downgrade() -> None:
    # Drop only the rows this migration added (keep manually-added Ready rows).
    op.execute(
        "DELETE FROM project_phases WHERE slug = 'ready' AND sort_order = 6"
    )
    op.execute("ALTER TABLE project_phases    DROP COLUMN IF EXISTS planned_end")
    op.execute("ALTER TABLE project_phases    DROP COLUMN IF EXISTS planned_start")
    op.execute("ALTER TABLE imported_projects DROP COLUMN IF EXISTS target_launch_source")
    op.execute("ALTER TABLE imported_projects DROP COLUMN IF EXISTS target_launch_date")
