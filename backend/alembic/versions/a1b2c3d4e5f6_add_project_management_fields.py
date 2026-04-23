"""add project management fields

Revision ID: a1b2c3d4e5f6
Revises: 5b8fc5b8972b
Create Date: 2026-04-17 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '5b8fc5b8972b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Helper: only add column if it doesn't already exist (handles partial runs)
    conn = op.get_bind()
    existing = {row[1] for row in conn.execute(sa.text("PRAGMA table_info('projects')"))}

    def _add_if_missing(col_name, col):
        if col_name not in existing:
            op.add_column('projects', col)

    _add_if_missing('description', sa.Column('description', sa.Text(), nullable=True))
    _add_if_missing('project_type', sa.Column('project_type', sa.String(length=50), nullable=False, server_default='住宅'))
    _add_if_missing('status', sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'))
    _add_if_missing('budget', sa.Column('budget', sa.Float(), nullable=True))
    _add_if_missing('start_date', sa.Column('start_date', sa.Date(), nullable=True))
    _add_if_missing('end_date', sa.Column('end_date', sa.Date(), nullable=True))
    _add_if_missing('owner', sa.Column('owner', sa.String(length=100), nullable=True))
    # SQLite does not support non-constant defaults with ADD COLUMN,
    # so we use a literal string default for the timestamp columns.
    _add_if_missing('created_at', sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("'2025-01-01 00:00:00'")))
    _add_if_missing('updated_at', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("'2025-01-01 00:00:00'")))


def downgrade() -> None:
    op.drop_column('projects', 'updated_at')
    op.drop_column('projects', 'created_at')
    op.drop_column('projects', 'owner')
    op.drop_column('projects', 'end_date')
    op.drop_column('projects', 'start_date')
    op.drop_column('projects', 'budget')
    op.drop_column('projects', 'status')
    op.drop_column('projects', 'project_type')
    op.drop_column('projects', 'description')
