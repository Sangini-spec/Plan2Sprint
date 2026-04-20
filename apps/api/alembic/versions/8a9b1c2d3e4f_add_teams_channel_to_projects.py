"""add_teams_channel_to_projects

Revision ID: 8a9b1c2d3e4f
Revises: 7f3a2b1c8d90
Create Date: 2026-04-13 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '8a9b1c2d3e4f'
down_revision: Union[str, None] = '7f3a2b1c8d90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('imported_projects', sa.Column('teams_channel_id', sa.String(), nullable=True))
    op.add_column('imported_projects', sa.Column('teams_channel_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('imported_projects', 'teams_channel_name')
    op.drop_column('imported_projects', 'teams_channel_id')
