import json
from datetime import datetime
from app import db


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
