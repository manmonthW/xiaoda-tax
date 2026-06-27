"""phase0 step0.1: voucher status machine, AI provenance, red-reversal link, audit_log, unique voucher_no

Revision ID: a1c0mpliance01
Revises: 5b0f736731de
Create Date: 2026-06-12

合规地基 Step 0.1（纯增量，不触碰现有数据）：
- voucher 增加状态机/审核/红冲/AI溯源字段
- 新增 audit_log 审计日志表
- voucher_no 增加唯一索引（防重号）
- 回填：现有凭证 status='posted'，AI助手制单的来源标记为 'ai'
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c0mpliance01'
down_revision = '5b0f736731de'
branch_labels = None
depends_on = None


def upgrade():
    # ── voucher: 新增合规字段（SQLite 原生 ADD COLUMN，逐列增量，不重建表）──
    op.add_column('voucher', sa.Column('status', sa.String(length=12),
                                       nullable=False, server_default='posted'))
    op.add_column('voucher', sa.Column('reviewer', sa.String(length=30),
                                       nullable=True, server_default=''))
    op.add_column('voucher', sa.Column('posted_at', sa.DateTime(), nullable=True))
    op.add_column('voucher', sa.Column('voided_at', sa.DateTime(), nullable=True))
    op.add_column('voucher', sa.Column('is_reversed', sa.Boolean(),
                                       nullable=True, server_default=sa.text('0')))
    op.add_column('voucher', sa.Column('reversal_of_id', sa.Integer(), nullable=True))
    op.add_column('voucher', sa.Column('source', sa.String(length=16),
                                       nullable=False, server_default='manual'))
    op.add_column('voucher', sa.Column('raw_text', sa.Text(),
                                       nullable=True, server_default=''))
    op.add_column('voucher', sa.Column('ai_confidence', sa.Float(), nullable=True))
    op.add_column('voucher', sa.Column('confirmed_by', sa.String(length=30),
                                       nullable=True, server_default=''))

    # ── 防重号：voucher_no 唯一索引 ──
    op.create_index('uq_voucher_no', 'voucher', ['voucher_no'], unique=True)

    # ── 审计日志表 ──
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('actor', sa.String(length=30), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'])

    # ── 数据回填：现有凭证视为“已记账”，AI助手制单的标记来源为 ai ──
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE voucher SET status='posted' WHERE status IS NULL OR status=''"))
    conn.execute(sa.text("UPDATE voucher SET source='ai' WHERE preparer='AI助手'"))
    conn.execute(sa.text("UPDATE voucher SET is_reversed=0 WHERE is_reversed IS NULL"))


def downgrade():
    op.drop_index('ix_audit_log_created_at', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index('uq_voucher_no', table_name='voucher')
    op.drop_column('voucher', 'confirmed_by')
    op.drop_column('voucher', 'ai_confidence')
    op.drop_column('voucher', 'raw_text')
    op.drop_column('voucher', 'source')
    op.drop_column('voucher', 'reversal_of_id')
    op.drop_column('voucher', 'is_reversed')
    op.drop_column('voucher', 'voided_at')
    op.drop_column('voucher', 'posted_at')
    op.drop_column('voucher', 'reviewer')
    op.drop_column('voucher', 'status')
