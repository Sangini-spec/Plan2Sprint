"""add imported_project_id to work_items and iterations

Revision ID: c5d8e2f17a03
Revises: a3c9f1d42e01
Create Date: 2026-02-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5d8e2f17a03'
down_revision: Union[str, None] = 'a3c9f1d42e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add imported_project_id FK to work_items (nullable — existing rows stay NULL)
    op.add_column(
        'work_items',
        sa.Column('imported_project_id', sa.String(25), sa.ForeignKey('imported_projects.id'), nullable=True),
    )
    op.create_index('ix_work_items_project', 'work_items', ['imported_project_id'])

    # Add imported_project_id FK to iterations (nullable — existing rows stay NULL)
    op.add_column(
        'iterations',
        sa.Column('imported_project_id', sa.String(25), sa.ForeignKey('imported_projects.id'), nullable=True),
    )
    op.create_index('ix_iterations_project', 'iterations', ['imported_project_id'])


def downgrade() -> None:
    op.drop_index('ix_iterations_project', table_name='iterations')
    op.drop_column('iterations', 'imported_project_id')
    op.drop_index('ix_work_items_project', table_name='work_items')
    op.drop_column('work_items', 'imported_project_id')
