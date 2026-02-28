"""add imported_projects and user_project_preferences

Revision ID: a3c9f1d42e01
Revises: b78fb27e9622
Create Date: 2026-02-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3c9f1d42e01'
down_revision: Union[str, None] = 'b78fb27e9622'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- imported_projects ---
    op.create_table('imported_projects',
        sa.Column('id', sa.String(length=25), nullable=False),
        sa.Column('organization_id', sa.String(length=25), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('source_tool', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('board_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('cached_data', sa.JSON(), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'external_id', 'source_tool', name='uq_imported_project'),
    )

    # --- user_project_preferences ---
    op.create_table('user_project_preferences',
        sa.Column('id', sa.String(length=25), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(length=25), nullable=False),
        sa.Column('selected_project_id', sa.String(length=25), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['selected_project_id'], ['imported_projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_user_project_pref'),
    )


def downgrade() -> None:
    op.drop_table('user_project_preferences')
    op.drop_table('imported_projects')
