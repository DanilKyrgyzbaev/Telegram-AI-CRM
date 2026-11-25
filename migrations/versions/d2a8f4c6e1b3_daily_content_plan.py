"""daily content plan: post kind, rubric, planned time

Revision ID: d2a8f4c6e1b3
Revises: b7e3c1d5f2a9
Create Date: 2026-11-25 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd2a8f4c6e1b3'
down_revision = 'b7e3c1d5f2a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('channel_posts', sa.Column('kind', sa.String(length=16), server_default='post', nullable=False))
    op.add_column('channel_posts', sa.Column('rubric', sa.String(length=32), nullable=True))
    op.add_column('channel_posts', sa.Column('planned_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('channel_posts', 'planned_at')
    op.drop_column('channel_posts', 'rubric')
    op.drop_column('channel_posts', 'kind')
