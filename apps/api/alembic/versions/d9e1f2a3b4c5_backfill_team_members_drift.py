"""Backfill team_members schema drift

The columns ``team_members.role``, ``team_members.imported_project_id``,
``team_members.github_username``, and ``team_members.github_access_token``
all exist on the production database (applied out-of-band via direct
ALTER TABLE statements over time) but were never captured in any
Alembic revision. Restoring from migrations alone produces a schema
that's incompatible with the running app — RBAC silently degrades
because ``role`` doesn't exist, project-scoped filters break because
``imported_project_id`` doesn't exist, and the GitHub integration can
never resolve a developer because the linkage columns don't exist.

This revision uses idempotent ``IF NOT EXISTS`` semantics so it's safe
to apply against the production DB (no-ops because the columns are
already there) AND fresh databases (creates them).

Revision ID: d9e1f2a3b4c5
Revises: c8b3a5e7f0d1
Create Date: 2026-05-04 17:00:00.000000

"""
from alembic import op


revision = "d9e1f2a3b4c5"
down_revision = "c8b3a5e7f0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── team_members.role ──────────────────────────────────────────────
    # The single most-load-bearing column in the RBAC model. New rows
    # default to 'developer' (matches the model default in
    # apps/api/app/models/team_member.py). Existing rows in fresh DBs
    # get the same default so role-gating never returns NULL.
    op.execute(
        """
        ALTER TABLE team_members
        ADD COLUMN IF NOT EXISTS role VARCHAR(30)
        NOT NULL DEFAULT 'developer'
        """
    )

    # ── team_members.imported_project_id ───────────────────────────────
    # Per-project membership. Nullable for legacy org-wide TM rows that
    # pre-date project import (and for some integration paths that
    # create cross-project rows).
    op.execute(
        """
        ALTER TABLE team_members
        ADD COLUMN IF NOT EXISTS imported_project_id VARCHAR
        """
    )
    # Add the FK only if the constraint doesn't already exist. Postgres
    # has no IF NOT EXISTS for constraints; check pg_constraint manually.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'team_members_imported_project_id_fkey'
            ) THEN
                ALTER TABLE team_members
                ADD CONSTRAINT team_members_imported_project_id_fkey
                FOREIGN KEY (imported_project_id)
                REFERENCES imported_projects(id);
            END IF;
        END
        $$;
        """
    )

    # ── team_members.github_username ───────────────────────────────────
    # Caches the GitHub login of the linked developer so we can attribute
    # commits/PRs back to a TM row without an API roundtrip.
    op.execute(
        """
        ALTER TABLE team_members
        ADD COLUMN IF NOT EXISTS github_username VARCHAR
        """
    )

    # ── team_members.github_access_token ───────────────────────────────
    # Per-developer OAuth/PAT token. NOTE: stored plaintext today
    # (HIGH-5 finding). A separate migration will add encryption at rest
    # via Fernet — this revision only restores the column.
    op.execute(
        """
        ALTER TABLE team_members
        ADD COLUMN IF NOT EXISTS github_access_token VARCHAR
        """
    )


def downgrade() -> None:
    # Conservative downgrade — drop only the columns we added. Rollback
    # is destructive (loses RBAC + GitHub linkage data); only intended
    # for test/dev rebuilds. Drops the FK constraint first so the
    # column drop on imported_project_id doesn't fail.
    op.execute(
        "ALTER TABLE team_members "
        "DROP CONSTRAINT IF EXISTS team_members_imported_project_id_fkey"
    )
    op.execute(
        "ALTER TABLE team_members DROP COLUMN IF EXISTS github_access_token"
    )
    op.execute(
        "ALTER TABLE team_members DROP COLUMN IF EXISTS github_username"
    )
    op.execute(
        "ALTER TABLE team_members DROP COLUMN IF EXISTS imported_project_id"
    )
    op.execute(
        "ALTER TABLE team_members DROP COLUMN IF EXISTS role"
    )
