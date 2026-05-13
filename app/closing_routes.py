"""期末结转 + 报表自动生成"""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import func
from app import db
from app.models import Account, Voucher, VoucherItem, FinancialReport
from app.calc import calc_balance_sheet, calc_income_stmt, calc_cashflow

closing_bp = Blueprint("closing", __name__)


def _get_account_by_code(code):
    return Account.query.filter_by(code=code).first()


def _period_sums(year, month_start, month_end):
    """汇总指定期间各科目的借贷发生额，返回 {account_id: (debit, credit)}"""
    d_start = date(year, month_start, 1)
    if month_end == 12:
        d_end = date(year, 12, 31)
    else:
        d_end = date(year, month_end + 1, 1)

    rows = (
        db.session.query(
            VoucherItem.account_id,
            func.coalesce(func.sum(VoucherItem.debit_amount), 0).label("d"),
            func.coalesce(func.sum(VoucherItem.credit_amount), 0).label("c"),
        )
        .join(Voucher, Voucher.id == VoucherItem.voucher_id)
        .filter(Voucher.voucher_date >= d_start, Voucher.voucher_date < d_end)
        .group_by(VoucherItem.account_id)
        .all()
    )
    return {r.account_id: (r.d, r.c) for r in rows}


def _account_balance(acct, sums):
    """根据科目余额方向计算余额"""
    d, c = sums.get(acct.id, (0, 0))
    if acct.balance_dir == "debit":
        return round(d - c, 2)
    else:
        return round(c - d, 2)


# ────────────────────────────────────────────────────────
# 期末结转
# ────────────────────────────────────────────────────────
@closing_bp.route("/carry-forward", methods=["GET", "POST"])
def carry_forward():
    """期末损益结转：收入类/费用类 → 本年利润"""
    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    # 找本年利润科目
    profit_acct = _get_account_by_code("3131")
    if not profit_acct:
        flash("未找到「本年利润」科目(3131)，请先初始化科目表", "danger")
        return redirect(url_for("voucher.voucher_list"))

    # 计算当月各科目发生额
    sums = _period_sums(year, month, month)
    accounts = {a.id: a for a in Account.query.all()}

    # 收集需要结转的损益类科目
    items_to_close = []
    for acct_id, (d, c) in sums.items():
        acct = accounts.get(acct_id)
        if not acct:
            continue
        if acct.category == "income":
            # 收入类结转：借-收入科目，贷-本年利润
            balance = round(c - d, 2)
            if abs(balance) > 0.005:
                items_to_close.append({
                    "account": acct, "balance": balance,
                    "debit_amount": balance if balance > 0 else 0,
                    "credit_amount": -balance if balance < 0 else 0,
                    "direction": "收入→本年利润",
                })
        elif acct.category == "expense":
            # 费用类结转：借-本年利润，贷-费用科目
            balance = round(d - c, 2)
            if abs(balance) > 0.005:
                items_to_close.append({
                    "account": acct, "balance": balance,
                    "debit_amount": 0,
                    "credit_amount": balance if balance > 0 else 0,
                    "direction": "费用→本年利润",
                })

    total_income = sum(i["balance"] for i in items_to_close if i["account"].category == "income")
    total_expense = sum(i["balance"] for i in items_to_close if i["account"].category == "expense")
    net_profit = round(total_income - total_expense, 2)

    # 检查是否已有结转凭证
    carry_no = f"转-{year}-{month:02d}"
    existing = Voucher.query.filter_by(voucher_no=carry_no).first()

    if request.method == "POST":
        if existing:
            flash(f"{year}年{month}月已有结转凭证 {carry_no}，不可重复结转", "warning")
            return redirect(url_for("closing.carry_forward", year=year, month=month))

        if not items_to_close:
            flash("当月无损益类发生额，无需结转", "info")
            return redirect(url_for("closing.carry_forward", year=year, month=month))

        # 创建结转凭证
        v = Voucher(
            voucher_no=carry_no,
            voucher_date=date(year, month, 28) if month != 2 else date(year, 2, 28),
            notes=f"{year}年{month}月期末损益结转",
            preparer="系统自动",
        )
        db.session.add(v)
        db.session.flush()

        sort = 0
        profit_debit = 0.0
        profit_credit = 0.0

        for item in items_to_close:
            acct = item["account"]
            if acct.category == "income":
                # 借-收入科目（冲减收入），贷-本年利润
                vi = VoucherItem(
                    voucher_id=v.id, account_id=acct.id,
                    summary=f"结转{acct.name}",
                    debit_amount=item["balance"], credit_amount=0,
                    sort_order=sort,
                )
                profit_credit += item["balance"]
            else:
                # 借-本年利润，贷-费用科目（冲减费用）
                vi = VoucherItem(
                    voucher_id=v.id, account_id=acct.id,
                    summary=f"结转{acct.name}",
                    debit_amount=0, credit_amount=item["balance"],
                    sort_order=sort,
                )
                profit_debit += item["balance"]
            db.session.add(vi)
            sort += 1

        # 本年利润汇总行
        vi_profit = VoucherItem(
            voucher_id=v.id, account_id=profit_acct.id,
            summary="结转本期损益",
            debit_amount=profit_debit, credit_amount=profit_credit,
            sort_order=sort,
        )
        db.session.add(vi_profit)

        db.session.commit()
        flash(f"已生成结转凭证 {carry_no}，净利润 ¥{net_profit:,.2f}", "success")
        return redirect(url_for("closing.carry_forward", year=year, month=month))

    return render_template("closing_carry_forward.html",
                           items=items_to_close, year=year, month=month,
                           total_income=total_income, total_expense=total_expense,
                           net_profit=net_profit, existing=existing,
                           active_page="carry_forward")


# ────────────────────────────────────────────────────────
# 自动生成报表
# ────────────────────────────────────────────────────────
@closing_bp.route("/generate-report", methods=["GET", "POST"])
def generate_report():
    """从账簿数据自动生成三表"""
    today = date.today()
    year = int(request.args.get("year", today.year))
    quarter = int(request.args.get("quarter", (today.month - 1) // 3 + 1))

    month_start = (quarter - 1) * 3 + 1
    month_end = quarter * 3

    # 计算期间发生额
    sums = _period_sums(year, month_start, month_end)
    # 年初至今累计
    sums_ytd = _period_sums(year, 1, month_end)

    accounts = {a.code: a for a in Account.query.all()}
    acct_by_id = {a.id: a for a in Account.query.all()}

    def bal(code, use_sums=None):
        """获取科目余额"""
        acct = accounts.get(code)
        if not acct:
            return 0
        s = use_sums or sums_ytd
        return _account_balance(acct, s)

    def debit_sum(code, use_sums=None):
        """获取科目借方发生额"""
        acct = accounts.get(code)
        if not acct:
            return 0
        s = use_sums or sums
        d, c = s.get(acct.id, (0, 0))
        return round(d, 2)

    def credit_sum(code, use_sums=None):
        """获取科目贷方发生额"""
        acct = accounts.get(code)
        if not acct:
            return 0
        s = use_sums or sums
        d, c = s.get(acct.id, (0, 0))
        return round(c, 2)

    # ── 资产负债表 ──
    bs = {}
    # 资产类（期末余额）
    bs["a1"] = bal("1001") + bal("1002")                      # 货币资金
    bs["a4"] = bal("1122")                                     # 应收账款
    bs["a18"] = bal("1401")                                    # 固定资产原价
    bs["a19"] = bal("1602")                                    # 累计折旧
    # 负债类
    bs["l32"] = bal("2202")                                    # 应付账款
    bs["l34"] = bal("2211")                                    # 应付职工薪酬
    bs["l36"] = bal("2221") + bal("2221.01") + bal("2221.02") + bal("2221.03")  # 应交税费
    # 所有者权益
    bs["e48"] = bal("3001")                                    # 实收资本
    bs["e49"] = bal("3101")                                    # 盈余公积
    bs["e51"] = bal("3131") + bal("3141")                      # 未分配利润 = 本年利润 + 利润分配

    # 年初数（简化处理：如果是Q1则年初=0，否则从上一期报表读取或设0）
    for k in list(bs.keys()):
        bs[k + "_y"] = 0  # 年初数默认0（后续可从上期报表读取）

    bs = calc_balance_sheet(bs)

    # ── 利润表 ──
    ist = {}
    # 本期数（当季）
    ist["r1"] = credit_sum("5001", sums)                       # 营业收入
    ist["r2"] = debit_sum("5401", sums)                        # 营业成本
    ist["r14"] = debit_sum("5602", sums) + debit_sum("5602.01", sums) + debit_sum("5602.02", sums) + debit_sum("5602.03", sums) + debit_sum("5602.04", sums)  # 管理费用
    ist["r18"] = debit_sum("5603", sums)                       # 财务费用
    ist["r24"] = debit_sum("5711", sums)                       # 营业外支出
    ist["r31"] = debit_sum("2221.03", sums)                    # 所得税费用

    # 累计数（年初至今）
    ist["r1_acc"] = credit_sum("5001", sums_ytd)
    ist["r2_acc"] = debit_sum("5401", sums_ytd)
    ist["r14_acc"] = debit_sum("5602", sums_ytd) + debit_sum("5602.01", sums_ytd) + debit_sum("5602.02", sums_ytd) + debit_sum("5602.03", sums_ytd) + debit_sum("5602.04", sums_ytd)
    ist["r18_acc"] = debit_sum("5603", sums_ytd)
    ist["r24_acc"] = debit_sum("5711", sums_ytd)
    ist["r31_acc"] = debit_sum("2221.03", sums_ytd)

    ist = calc_income_stmt(ist)

    # ── 现金流量表（简化：从银行存款+库存现金的对方科目推算）──
    cf = {}
    # 简化处理：直接从科目发生额映射
    cf["c1"] = credit_sum("1122", sums) + debit_sum("1002", sums) + debit_sum("1001", sums)  # 近似：银行存款借方（收入相关）
    # 更精确的方法需要分析每笔凭证的对方科目，这里用简化版
    # 收到的现金 ≈ 收入科目的贷方（含税）
    cash_in = 0
    cash_out_salary = 0
    cash_out_tax = 0
    cash_out_other = 0

    # 遍历当期凭证精确计算现金流
    d_start = date(year, month_start, 1)
    d_end = date(year, month_end + 1, 1) if month_end < 12 else date(year, 12, 31)
    cash_acct_ids = set()
    for code in ["1001", "1002"]:
        a = accounts.get(code)
        if a:
            cash_acct_ids.add(a.id)

    if cash_acct_ids:
        # 找所有涉及现金/银行的凭证
        vouchers = (
            Voucher.query
            .join(VoucherItem)
            .filter(VoucherItem.account_id.in_(cash_acct_ids))
            .filter(Voucher.voucher_date >= d_start)
            .filter(Voucher.voucher_date < d_end)
            .all()
        )
        salary_acct = accounts.get("2211")
        tax_accts = {accounts.get(c).id for c in ["2221", "2221.01", "2221.02", "2221.03"] if accounts.get(c)}
        income_acct = accounts.get("5001")

        for v in vouchers:
            # 分析每张凭证：现金科目的借方=流入，贷方=流出
            cash_debit = sum(i.debit_amount for i in v.items if i.account_id in cash_acct_ids)
            cash_credit = sum(i.credit_amount for i in v.items if i.account_id in cash_acct_ids)
            other_acct_ids = {i.account_id for i in v.items if i.account_id not in cash_acct_ids}

            if cash_debit > 0:
                # 现金流入
                if income_acct and income_acct.id in other_acct_ids:
                    cash_in += cash_debit
                else:
                    cash_in += cash_debit  # 其他流入也算经营收入
            if cash_credit > 0:
                # 现金流出 - 根据对方科目分类
                if salary_acct and salary_acct.id in other_acct_ids:
                    cash_out_salary += cash_credit
                elif tax_accts & other_acct_ids:
                    cash_out_tax += cash_credit
                else:
                    cash_out_other += cash_credit

    cf["c1"] = round(cash_in, 2)                                # 销售收到的现金
    cf["c4"] = round(cash_out_salary, 2)                        # 支付职工薪酬
    cf["c5"] = round(cash_out_tax, 2)                           # 支付税费
    cf["c6"] = round(cash_out_other, 2)                         # 支付其他经营活动现金

    # 累计 = 年初至今（简化：如果Q1则同本期）
    cf["c1_acc"] = cf["c1"]
    cf["c4_acc"] = cf["c4"]
    cf["c5_acc"] = cf["c5"]
    cf["c6_acc"] = cf["c6"]

    # 期初现金
    cf["c21"] = bal("3001")  # 简化：期初现金 ≈ 实收资本（首年）
    cf["c21_acc"] = cf["c21"]

    cf = calc_cashflow(cf)

    preview = {
        "bs": bs, "ist": ist, "cf": cf,
        "year": year, "quarter": quarter,
        "month_start": month_start, "month_end": month_end,
    }

    if request.method == "POST":
        # 创建或更新报表
        period_start = f"{year}-{month_start:02d}-01"
        m_end = month_end
        period_end = f"{year}-{m_end:02d}-{'30' if m_end in (4,6,9,11) else '31'}"
        if m_end == 2:
            period_end = f"{year}-02-28"

        # 查找已有同期报表
        existing = FinancialReport.query.filter_by(
            report_type="quarterly", year=year, quarter=quarter
        ).first()

        if existing:
            r = existing
        else:
            r = FinancialReport(
                report_type="quarterly", year=year, quarter=quarter,
                period_start=period_start, period_end=period_end,
            )
            db.session.add(r)

        r.set_bs(bs)
        r.set_is(ist)
        r.set_cf(cf)
        db.session.commit()

        action = "更新" if existing else "生成"
        flash(f"已{action} {year}年第{quarter}季度报表", "success")
        return redirect(url_for("report.review", report_id=r.id))

    return render_template("closing_generate.html", preview=preview,
                           active_page="generate_report")
