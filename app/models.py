import json
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from app import db

# 金额统一精度：2 位小数，四舍五入（合规：账面金额精确到分，避免浮点漂移）
MONEY_QUANT = Decimal("0.01")


def to_money(value):
    """把任意输入安全转为 2 位小数的 Decimal 金额。
    用 str() 包裹避免二进制浮点误差（如 0.1+0.2）。"""
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _json_money_default(o):
    """json.dumps 兜底：把 Decimal 序列化为 float，便于报表 JSON 存储。"""
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


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

    # ─── 凭证状态机 ───
    # draft 草稿 → reviewed 已审核 → posted 已记账 → void 已作废 / reversed 已红冲
    STATUS_DRAFT = "draft"
    STATUS_REVIEWED = "reviewed"
    STATUS_POSTED = "posted"
    STATUS_VOID = "void"
    STATUS_REVERSED = "reversed"      # 本凭证为红冲生成的冲销凭证
    STATUS_LABELS = {
        STATUS_DRAFT: "草稿",
        STATUS_REVIEWED: "已审核",
        STATUS_POSTED: "已记账",
        STATUS_VOID: "已作废",
        STATUS_REVERSED: "红冲凭证",
    }

    # ─── 来源 ───
    SOURCE_MANUAL = "manual"
    SOURCE_AI = "ai"
    SOURCE_SYSTEM = "system"

    id = db.Column(db.Integer, primary_key=True)
    voucher_no = db.Column(db.String(30), nullable=False)          # "记-2026-001"
    voucher_date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.String(200), default="")                  # 凭证摘要
    preparer = db.Column(db.String(30), default="")                # 制单人
    is_posted = db.Column(db.Boolean, default=False)               # 是否已过账（兼容旧字段）

    # ─── 合规：状态机 / 审核留痕 ───
    status = db.Column(db.String(12), nullable=False, default=STATUS_POSTED)
    reviewer = db.Column(db.String(30), default="")                # 审核人（制单/审核分离）
    posted_at = db.Column(db.DateTime, nullable=True)              # 记账时间
    voided_at = db.Column(db.DateTime, nullable=True)              # 作废时间

    # ─── 合规：红字冲销链路 ───
    is_reversed = db.Column(db.Boolean, default=False)             # 本凭证是否已被红冲
    reversal_of_id = db.Column(db.Integer, db.ForeignKey("voucher.id"), nullable=True)  # 指向被冲销的原凭证

    # ─── AI 溯源 ───
    source = db.Column(db.String(16), nullable=False, default=SOURCE_MANUAL)  # manual/ai/system
    raw_text = db.Column(db.Text, default="")                      # AI 记账时的原始自然语言
    ai_confidence = db.Column(db.Float, nullable=True)             # AI 识别置信度
    confirmed_by = db.Column(db.String(30), default="")            # AI 凭证的人工确认人

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    items = db.relationship("VoucherItem", backref="voucher", cascade="all, delete-orphan",
                            order_by="VoucherItem.sort_order")
    reversal_of = db.relationship("Voucher", remote_side=[id], backref="reversals")

    @property
    def total_debit(self):
        return sum((i.debit_amount for i in self.items), 0)

    @property
    def total_credit(self):
        return sum((i.credit_amount for i in self.items), 0)

    @property
    def is_balanced(self):
        return abs(self.total_debit - self.total_credit) < 0.005

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def is_editable(self):
        """仅草稿/已审核可编辑；已记账、已作废、红冲凭证不可改"""
        return self.status in (self.STATUS_DRAFT, self.STATUS_REVIEWED)

    def __repr__(self):
        return f"<Voucher {self.voucher_no} [{self.status}]>"


class VoucherItem(db.Model):
    """凭证分录"""
    __tablename__ = "voucher_item"

    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("voucher.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    summary = db.Column(db.String(100), default="")
    debit_amount = db.Column(db.Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    credit_amount = db.Column(db.Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    sort_order = db.Column(db.Integer, default=0)

    account = db.relationship("Account")

    def __repr__(self):
        return f"<VoucherItem {self.account_id} D:{self.debit_amount} C:{self.credit_amount}>"


class AuditLog(db.Model):
    """审计日志：记录谁、何时、对哪个对象做了什么（合规留痕，不可被业务流程删除）"""
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False)   # voucher / voucher_item / account / report
    entity_id = db.Column(db.Integer, nullable=True)         # 关联对象主键
    action = db.Column(db.String(20), nullable=False)        # create/update/post/review/void/reverse/ai_generate
    actor = db.Column(db.String(30), default="")             # 操作人
    detail = db.Column(db.Text, default="")                  # JSON：前后值/摘要
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def __repr__(self):
        return f"<AuditLog {self.action} {self.entity_type}#{self.entity_id}>"


def log_audit(entity_type, entity_id, action, actor="", detail=None):
    """写一条审计日志（合规留痕）。detail 可为 dict/list（自动 JSON）或字符串。
    仅 add 到 session，由调用方统一 commit。"""
    if isinstance(detail, (dict, list)):
        detail_str = json.dumps(detail, ensure_ascii=False, default=_json_money_default)
    else:
        detail_str = detail or ""
    entry = AuditLog(entity_type=entity_type, entity_id=entity_id,
                     action=action, actor=actor or "", detail=detail_str)
    db.session.add(entry)
    return entry


def next_voucher_no(kind="记", on_date=None):
    """统一发号器：生成 {kind}-YYYY-NNN，按年内已有最大序号 +1（含本会话未提交但已 flush 的凭证）。
    全系统唯一入口，避免编号重复/跳号。"""
    d = on_date or date.today()
    prefix = f"{kind}-{d.year}-"
    rows = Voucher.query.filter(Voucher.voucher_no.like(f"{prefix}%")).all()
    max_seq = 0
    for v in rows:
        tail = v.voucher_no[len(prefix):]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))
    return f"{prefix}{max_seq + 1:03d}"


def is_period_locked(on_date):
    """期间锁定：若该月已生成期末结转凭证（转-YYYY-MM），则视为已关账，
    不允许再增改该期间的普通凭证（合规：防止事后篡改已结转期间）。"""
    if on_date is None:
        return False
    carry_no = f"转-{on_date.year}-{on_date.month:02d}"
    return Voucher.query.filter_by(voucher_no=carry_no).first() is not None


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

    # ─── 合规：申报锁定 ───
    # 报表一经锁定即视为已申报口径，禁止再修改/覆盖/删除（更正须解锁或红冲调整后重新生成）
    is_locked = db.Column(db.Boolean, nullable=False, default=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    locked_by = db.Column(db.String(30), default="")

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def get_bs(self):
        return json.loads(self.balance_sheet or "{}")

    def set_bs(self, data):
        self.balance_sheet = json.dumps(data, ensure_ascii=False, default=_json_money_default)

    def get_is(self):
        return json.loads(self.income_stmt or "{}")

    def set_is(self, data):
        self.income_stmt = json.dumps(data, ensure_ascii=False, default=_json_money_default)

    def get_cf(self):
        return json.loads(self.cashflow_stmt or "{}")

    def set_cf(self, data):
        self.cashflow_stmt = json.dumps(data, ensure_ascii=False, default=_json_money_default)

    @property
    def label(self):
        if self.report_type == "quarterly":
            return f"{self.year}年第{self.quarter}季度"
        return f"{self.year}年度"

    def __repr__(self):
        return f"<Report {self.label}>"
