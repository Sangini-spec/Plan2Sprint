"""add_org_name_canonical

Adds ``name_canonical`` to ``organizations`` so two POs typing the same
organization name (any case, any leading/trailing whitespace) land in
the same org row instead of getting two parallel orgs.

The column is the canonical form ``LOWER(TRIM(name))`` and is
``UNIQUE`` — that's the matching key Phase 1 of Hotfix 85 uses at
signup AND at Settings → org-rename. Future signups can never produce
duplicate orgs for the same typed name.

Existing duplicates (4 "C2A" orgs, 2 "Shreshth..." orgs as of this
migration) get numeric suffixes on their canonical column ("c2a-2",
"c2a-3", etc.) so the unique constraint is satisfiable without
destroying any data — the user explicitly said the existing test
duplicates are not worth merging.

Revision ID: f3a4b5c6d7e8
Revises: e7f1c8a4b3d2
Create Date: 2026-05-10 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e7f1c8a4b3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the column (nullable initially so we can backfill)
    op.add_column(
        "organizations",
        sa.Column("name_canonical", sa.String(), nullable=True),
    )

    # 2. Backfill: LOWER(TRIM(name)) for everyone, then disambiguate
    #    duplicates with a row-number suffix tied to creation order so
    #    the oldest row keeps the bare canonical.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                LOWER(TRIM(name)) AS base_canonical,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(TRIM(name))
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM organizations
        )
        UPDATE organizations o
        SET name_canonical = CASE
            WHEN r.rn = 1 THEN r.base_canonical
            ELSE r.base_canonical || '-' || r.rn::text
        END
        FROM ranked r
        WHERE o.id = r.id
        """
    )

    # 3. Lock it down: NOT NULL + UNIQUE INDEX. From now on every
    #    Organization row has a canonical key and no two rows can share
    #    one. The signup / rename code paths look up by this column
    #    before creating a new org.
    op.alter_column("organizations", "name_canonical", nullable=False)
    op.create_index(
        "ix_organizations_name_canonical",
        "organizations",
        ["name_canonical"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_name_canonical", table_name="organizations")
    op.drop_column("organizations", "name_canonical")
