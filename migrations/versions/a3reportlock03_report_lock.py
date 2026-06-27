"""phase: financial_report lock fields (申报锁定)

Revision ID: a3reportlock03
Revises: a2money02
Create Date: 2026-06-12

新增 financial_report.is_locked / locked_at / locked_by，用于报表申报锁定。
additive add_column，SQLite 原生支持，不动任何已有数据。
"""
from alembic import op
import sqlalchemy as sa


revision = "a3reportlock03"
down_revision = "a2money02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("financial_report",
                  sa.Column("is_locked", sa.Boolean(), nullable=False,
                            server_default=sa.text("0")))
    op.add_column("financial_report",
                  sa.Column("locked_at", sa.DateTime(), nullable=True))
    op.add_column("financial_report",
                  sa.Column("locked_by", sa.String(length=30), nullable=True,
                            server_default=""))


def downgrade():
    op.drop_column("financial_report", "locked_by")
    op.drop_column("financial_report", "locked_at")
    op.drop_column("financial_report", "is_locked")
