import json
from datetime import datetime, date
from decimal import Decimal
from app import db


# ─── 记账模块 ───────────────────────────────────────────────


class Account(db.Model):
    """会计科目"""
    __tablename__ = "account"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)   # "1001", "2221.01"
    name = db.Column(db.String(60), nullable=False)                # "库存现金"
    category = db.Column(db.String(10), nullable=False)            # asset/liability/equity/income/expense
    balance_dir = db.Column(db.String(6), nullable=False)          # debit / credit
    parent_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    parent = db.relationship("Account", remote_side=[id], backref="children")

    CATEGORY_LABELS = {
        "asset": "资产", "liability": "负债", "equity": "所有者权益",
        "income": "收入", "expense": "费用",
    }

    @property
    def full_name(self):
        return f"{self.code} {self.name}"

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    def __repr__(self):
        return f"<Account {self.code} {self.name}>"


class Voucher(db.Model):
    """记账凭证"""
    __tablename__ = "voucher"

    id = db.Column(db.Integer, primary_key=True)
    voucher_no = db.Column(db.String(30), nullable=False)          # "记-2026-001"
    voucher_date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.String(200), default="")                  # 凭证摘要
    preparer = db.Column(db.String(30), default="")                # 制单人
    is_posted = db.Column(db.Boolean, default=False)               # 是否已过账
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    items = db.relationship("VoucherItem", backref="voucher", cascade="all, delete-orphan",
                            order_by="VoucherItem.sort_order")

    @property
    def total_debit(self):
        return sum(i.debit_amount for i in self.items)

    @property
    def total_credit(self):
        return sum(i.credit_amount for i in self.items)

    @property
    def is_balanced(self):
        return abs(self.total_debit - self.total_credit) < 0.005

    def __repr__(self):
        return f"<Voucher {self.voucher_no}>"


class VoucherItem(db.Model):
    """凭证分录"""
    __tablename__ = "voucher_item"

    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("voucher.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    summary = db.Column(db.String(100), default="")
    debit_amount = db.Column(db.Float, default=0.0)
    credit_amount = db.Column(db.Float, default=0.0)
    sort_order = db.Column(db.Integer, default=0)

    account = db.relationship("Account")

    def __repr__(self):
        return f"<VoucherItem {self.account_id} D:{self.debit_amount} C:{self.credit_amount}>"


# ─── 报表模块 ───────────────────────────────────────────────


class FinancialReport(db.Model):
    """财务报表"""
    __tablename__ = "financial_report"

    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(10), nullable=False)  # quarterly / annual
    year = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.Integer, nullable=True)  # 1-4, null for annual
    taxpayer_id = db.Column(db.String(30), default="")
    taxpayer_name = db.Column(db.String(100), default="")
    period_start = db.Column(db.String(20), default="")
    period_end = db.Column(db.String(20), default="")

    # 三张表数据，JSON存储
    balance_sheet = db.Column(db.Text, default="{}")
    income_stmt = db.Column(db.Text, default="{}")
    cashflow_stmt = db.Column(db.Text, default="{}")

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def get_bs(self):
        return json.loads(self.balance_sheet or "{}")

    def set_bs(self, data):
        self.balance_sheet = json.dumps(data, ensure_ascii=False)

    def get_is(self):
        return json.loads(self.income_stmt or "{}")

    def set_is(self, data):
        self.income_stmt = json.dumps(data, ensure_ascii=False)

    def get_cf(self):
        return json.loads(self.cashflow_stmt or "{}")

    def set_cf(self, data):
        self.cashflow_stmt = json.dumps(data, ensure_ascii=False)

    @property
    def label(self):
        if self.report_type == "quarterly":
            return f"{self.year}年第{self.quarter}季度"
        return f"{self.year}年度"

    def __repr__(self):
        return f"<Report {self.label}>"
