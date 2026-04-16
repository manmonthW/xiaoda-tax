from datetime import datetime
from app import db


class QuarterlyReport(db.Model):
    """季度报税记录"""

    __tablename__ = "quarterly_report"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.Integer, nullable=False)  # 1-4
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    status = db.Column(db.String(20), default="draft")  # draft / submitted

    # 增值税 - 小规模纳税人
    income_total = db.Column(db.Float, default=0.0)  # 营业收入合计（含税）
    income_tax_free = db.Column(db.Float, default=0.0)  # 免税收入
    income_taxable = db.Column(db.Float, default=0.0)  # 应税收入（不含税）
    vat_rate = db.Column(db.Float, default=0.01)  # 征收率（小规模通常1%或3%）
    vat_amount = db.Column(db.Float, default=0.0)  # 应纳增值税额
    vat_exempt = db.Column(db.Boolean, default=False)  # 是否享受免征（季度≤30万）

    # 附加税
    urban_maintenance_tax = db.Column(db.Float, default=0.0)  # 城市维护建设税
    education_surcharge = db.Column(db.Float, default=0.0)  # 教育费附加
    local_education_surcharge = db.Column(db.Float, default=0.0)  # 地方教育附加

    # 企业所得税（季度预缴）
    total_profit = db.Column(db.Float, default=0.0)  # 利润总额
    taxable_income = db.Column(db.Float, default=0.0)  # 应纳税所得额
    income_tax_rate = db.Column(db.Float, default=0.05)  # 税率（小微5%/10%/25%）
    income_tax_amount = db.Column(db.Float, default=0.0)  # 应纳所得税额
    income_tax_prepaid = db.Column(db.Float, default=0.0)  # 已预缴所得税
    income_tax_due = db.Column(db.Float, default=0.0)  # 本期应补(退)所得税

    # 印花税
    stamp_tax = db.Column(db.Float, default=0.0)

    # 备注
    notes = db.Column(db.Text, default="")

    invoices = db.relationship("Invoice", backref="report", lazy=True)

    @property
    def tax_total(self):
        """本季度应缴税费合计"""
        vat = 0 if self.vat_exempt else self.vat_amount
        return (
            vat
            + self.urban_maintenance_tax
            + self.education_surcharge
            + self.local_education_surcharge
            + self.income_tax_due
            + self.stamp_tax
        )

    def __repr__(self):
        return f"<Report {self.year}Q{self.quarter}>"


class Invoice(db.Model):
    """发票明细"""

    __tablename__ = "invoice"

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("quarterly_report.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    invoice_no = db.Column(db.String(50), default="")  # 发票号
    buyer = db.Column(db.String(200), default="")  # 购买方
    amount = db.Column(db.Float, nullable=False)  # 金额（含税）
    tax_amount = db.Column(db.Float, default=0.0)  # 税额
    invoice_type = db.Column(db.String(20), default="normal")  # normal/special 普票/专票
    notes = db.Column(db.String(200), default="")

    def __repr__(self):
        return f"<Invoice {self.invoice_no} ¥{self.amount}>"
