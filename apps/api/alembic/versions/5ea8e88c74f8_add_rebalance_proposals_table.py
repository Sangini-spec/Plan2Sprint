"""add_rebalance_proposals_table

Revision ID: 5ea8e88c74f8
Revises: e6b2a4f93d17
Create Date: 2026-04-09 20:01:53.549252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5ea8e88c74f8'
down_revision: Union[str, None] = 'e6b2a4f93d17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create rebalance_proposals table
    op.create_table('rebalance_proposals',
    sa.Column('id', sa.String(length=25), nullable=False),
    sa.Column('organization_id', sa.String(length=25), nullable=False),
    sa.Column('sprint_plan_id', sa.String(length=25), nullable=False),
    sa.Column('project_id', sa.String(length=25), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('mode', sa.String(length=50), nullable=False),
    sa.Column('target_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('summary', sa.String(), nullable=True),
    sa.Column('ai_rationale', sa.JSON(), nullable=True),
    sa.Column('po_guidance', sa.String(), nullable=True),
    sa.Column('original_success_probability', sa.Integer(), nullable=True),
    sa.Column('projected_success_probability', sa.Integer(), nullable=True),
    sa.Column('original_end_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('projected_end_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sprint_allocations', sa.JSON(), nullable=True),
    sa.Column('changes_summary', sa.JSON(), nullable=True),
    sa.Column('downstream_impact', sa.JSON(), nullable=True),
    sa.Column('new_plan_id', sa.String(length=25), nullable=True),
    sa.Column('ai_model_used', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['imported_projects.id'], ),
    sa.ForeignKeyConstraint(['sprint_plan_id'], ['sprint_plans.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Add rebalancing columns to sprint_plans
    op.add_column('sprint_plans', sa.Column('is_rebalanced', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('sprint_plans', sa.Column('rebalance_source_id', sa.String(length=25), nullable=True))


def downgrade() -> None:
    op.drop_column('sprint_plans', 'rebalance_source_id')
    op.drop_column('sprint_plans', 'is_rebalanced')
    op.drop_table('rebalance_proposals')
