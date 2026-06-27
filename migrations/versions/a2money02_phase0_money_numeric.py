"""phase0 step0.2: voucher_item amounts Float -> Numeric(18,2)

Revision ID: a2money02
Revises: a1c0mpliance01
Create Date: 2026-06-12

合规地基 Step 0.2：将凭证分录金额由浮点改为定点小数(18,2)，
避免浮点误差导致账证不平。数据值本身已是 2 位小数，迁移仅改变列类型。
使用 batch 模式（SQLite 需重建表），并保留外键。
"""
from alembic import op
import sqlalchemy as sa


revision = 'a2money02'
down_revision = 'a1c0mpliance01'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('voucher_item', schema=None) as batch_op:
        batch_op.alter_column(
            'debit_amount',
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=18, scale=2),
            existing_nullable=True,
            nullable=False,
            existing_server_default=None,
        )
        batch_op.alter_column(
            'credit_amount',
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=18, scale=2),
            existing_nullable=True,
            nullable=False,
            existing_server_default=None,
        )


def downgrade():
    with op.batch_alter_table('voucher_item', schema=None) as batch_op:
        batch_op.alter_column(
            'credit_amount',
            existing_type=sa.Numeric(precision=18, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.alter_column(
            'debit_amount',
            existing_type=sa.Numeric(precision=18, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
            nullable=True,
        )
