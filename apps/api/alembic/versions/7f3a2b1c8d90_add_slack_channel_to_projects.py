"""add_slack_channel_to_projects

Revision ID: 7f3a2b1c8d90
Revises: 5ea8e88c74f8
Create Date: 2026-04-12 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7f3a2b1c8d90'
down_revision: Union[str, None] = '5ea8e88c74f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('imported_projects', sa.Column('slack_channel_id', sa.String(), nullable=True))
    op.add_column('imported_projects', sa.Column('slack_channel_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('imported_projects', 'slack_channel_name')
    op.drop_column('imported_projects', 'slack_channel_id')
