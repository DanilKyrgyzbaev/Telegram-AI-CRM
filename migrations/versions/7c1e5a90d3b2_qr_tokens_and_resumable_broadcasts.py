"""qr tokens and resumable broadcasts

Revision ID: 7c1e5a90d3b2
Revises: ead20aef377e
Create Date: 2026-11-15 01:10:00.000000
"""
import secrets

from alembic import op
import sqlalchemy as sa


revision = '7c1e5a90d3b2'
down_revision = 'ead20aef377e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Случайный код для QR вместо номера товара: ссылку нельзя подобрать перебором
    op.add_column('products', sa.Column('qr_token', sa.String(length=16), nullable=True))
    conn = op.get_bind()
    for (product_id,) in conn.execute(sa.text("SELECT id FROM products")).fetchall():
        conn.execute(
            sa.text("UPDATE products SET qr_token = :token WHERE id = :id"),
            {"token": secrets.token_hex(6), "id": product_id},
        )
    op.alter_column('products', 'qr_token', nullable=False)
    op.create_unique_constraint('products_qr_token_key', 'products', ['qr_token'])

    # Прогресс рассылки: с какого клиента продолжать и когда она в последний раз подавала признаки жизни
    op.add_column('broadcasts', sa.Column('last_client_id', sa.Integer(), server_default='0', nullable=False))
    op.add_column('broadcasts', sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False))
    # У старых незавершённых рассылок прогресс неизвестен: возобновлять их нельзя — уйдут повторно
    op.execute("UPDATE broadcasts SET status = 'interrupted' WHERE status IN ('pending', 'sending')")


def downgrade() -> None:
    op.execute("UPDATE broadcasts SET status = 'done' WHERE status = 'interrupted'")
    op.drop_column('broadcasts', 'updated_at')
    op.drop_column('broadcasts', 'last_client_id')
    op.drop_constraint('products_qr_token_key', 'products', type_='unique')
    op.drop_column('products', 'qr_token')
