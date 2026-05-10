"""Hotfix 17 — swap UAT and Deployment phase sort_orders for cloud-native flow.

Cloud-native release process is:
    Testing & QA  →  Deployment  →  UAT  →  Ready

(Deploy to UAT/staging environment, THEN users do acceptance testing on
the deployed app.) The pre-cloud ordering had UAT before Deployment,
which only made sense when UAT happened in a permanent staging env and
"Deployment" meant production release.

This migration swaps the two phases for any project where the OLD
default ordering is still in place untouched:
    UAT & Staging at sort_order=4 AND Deployment & Launch at sort_order=5

Projects whose POs have manually drag-reordered their phases (so sort
orders don't match the old defaults) are LEFT ALONE — we don't override
explicit user customisation.

Revision ID: a7c4e1d2b9f3
Revises: f1a2b3c4d5e6
Create Date: 2026-05-02
"""
from alembic import op


revision = "a7c4e1d2b9f3"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Atomic swap using a CASE expression — no temporary placeholder
    # value needed. Only mutates rows in projects where BOTH phases are
    # at the old default positions; projects where someone has reordered
    # manually keep their custom ordering.
    op.execute(
        """
        UPDATE project_phases AS pp
        SET sort_order = CASE
            WHEN pp.slug = 'deployment-launch' THEN 4
            WHEN pp.slug = 'uat-staging' THEN 5
            ELSE pp.sort_order
        END
        WHERE pp.slug IN ('deployment-launch', 'uat-staging')
          AND EXISTS (
            SELECT 1 FROM project_phases AS pp_uat
            WHERE pp_uat.project_id = pp.project_id
              AND pp_uat.organization_id = pp.organization_id
              AND pp_uat.slug = 'uat-staging'
              AND pp_uat.sort_order = 4
          )
          AND EXISTS (
            SELECT 1 FROM project_phases AS pp_dep
            WHERE pp_dep.project_id = pp.project_id
              AND pp_dep.organization_id = pp.organization_id
              AND pp_dep.slug = 'deployment-launch'
              AND pp_dep.sort_order = 5
          );
        """
    )


def downgrade() -> None:
    # Reverse the swap — only on projects that match the NEW default
    # ordering (i.e. ones we'd have flipped on upgrade).
    op.execute(
        """
        UPDATE project_phases AS pp
        SET sort_order = CASE
            WHEN pp.slug = 'deployment-launch' THEN 5
            WHEN pp.slug = 'uat-staging' THEN 4
            ELSE pp.sort_order
        END
        WHERE pp.slug IN ('deployment-launch', 'uat-staging')
          AND EXISTS (
            SELECT 1 FROM project_phases AS pp_dep
            WHERE pp_dep.project_id = pp.project_id
              AND pp_dep.organization_id = pp.organization_id
              AND pp_dep.slug = 'deployment-launch'
              AND pp_dep.sort_order = 4
          )
          AND EXISTS (
            SELECT 1 FROM project_phases AS pp_uat
            WHERE pp_uat.project_id = pp.project_id
              AND pp_uat.organization_id = pp.organization_id
              AND pp_uat.slug = 'uat-staging'
              AND pp_uat.sort_order = 5
          );
        """
    )
