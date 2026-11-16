"""channel posts and direct messages

Revision ID: a4d2f6b1c9e8
Revises: 7c1e5a90d3b2
Create Date: 2026-11-17 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a4d2f6b1c9e8'
down_revision = '7c1e5a90d3b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Рассылка одному клиенту
    op.add_column('broadcasts', sa.Column('client_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'broadcasts_client_id_fkey', 'broadcasts', 'clients', ['client_id'], ['id'], ondelete='CASCADE'
    )

    op.create_table(
        'channel_posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('topic', sa.Text(), server_default='', nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('discount_id', sa.Integer(), nullable=True),
        sa.Column('text', sa.Text(), server_default='', nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('message_id', sa.BigInteger(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['discount_id'], ['discounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_channel_posts_status'), 'channel_posts', ['status'])
    op.create_index(op.f('ix_channel_posts_scheduled_at'), 'channel_posts', ['scheduled_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_channel_posts_scheduled_at'), table_name='channel_posts')
    op.drop_index(op.f('ix_channel_posts_status'), table_name='channel_posts')
    op.drop_table('channel_posts')
    op.drop_constraint('broadcasts_client_id_fkey', 'broadcasts', type_='foreignkey')
    op.drop_column('broadcasts', 'client_id')
