"""instagram

Revision ID: b7e3c1d5f2a9
Revises: a4d2f6b1c9e8
Create Date: 2026-11-17 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e3c1d5f2a9'
down_revision = 'a4d2f6b1c9e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Клиенты из Instagram Direct: у них нет Telegram ID
    op.alter_column('clients', 'telegram_id', existing_type=sa.BigInteger(), nullable=True)
    op.add_column('clients', sa.Column('instagram_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_clients_instagram_id'), 'clients', ['instagram_id'], unique=True)

    op.add_column('channel_posts', sa.Column('instagram_media_id', sa.String(length=64), nullable=True))
    op.add_column('channel_posts', sa.Column('instagram_error', sa.Text(), nullable=True))

    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_column('channel_posts', 'instagram_error')
    op.drop_column('channel_posts', 'instagram_media_id')
    op.drop_index(op.f('ix_clients_instagram_id'), table_name='clients')
    op.drop_column('clients', 'instagram_id')
    # Клиентов из Instagram без Telegram ID удаляем вместе с историей — иначе колонку не сделать NOT NULL
    op.execute("DELETE FROM messages WHERE client_id IN (SELECT id FROM clients WHERE telegram_id IS NULL)")
    op.execute("DELETE FROM purchases WHERE client_id IN (SELECT id FROM clients WHERE telegram_id IS NULL)")
    op.execute("DELETE FROM clients WHERE telegram_id IS NULL")
    op.alter_column('clients', 'telegram_id', existing_type=sa.BigInteger(), nullable=False)
