"""product specs and size chart from Wildberries card

Revision ID: e5b9c2d7f3a1
Revises: d2a8f4c6e1b3
Create Date: 2026-11-25 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5b9c2d7f3a1'
down_revision = 'd2a8f4c6e1b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('specs', sa.Text(), server_default='', nullable=False))
    op.add_column('products', sa.Column('size_chart', sa.Text(), server_default='', nullable=False))


def downgrade() -> None:
    op.drop_column('products', 'size_chart')
    op.drop_column('products', 'specs')
