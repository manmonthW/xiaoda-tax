"""期末结转 + 报表自动生成"""
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import func
from app import db
from app.models import Account, Voucher, VoucherItem, FinancialReport, log_audit
from app.calc import calc_balance_sheet, calc_income_stmt, calc_cashflow

closing_bp = Blueprint("closing", __name__)


def _get_account_by_code(code):
    return Account.query.filter_by(code=code).first()


def _period_sums(year, month_start, month_end):
    """汇总指定期间各科目的借贷发生额，返回 {account_id: (debit, credit)}。
    口径：仅统计「已记账」(posted) 凭证，排除草稿/已作废，保证申报数据准确。
    （红冲：原凭证与冲销凭证均为 posted，借贷相抵净额为零，无需特殊处理。）"""
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
        .filter(Voucher.status == Voucher.STATUS_POSTED)
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


def _sums_before(year):
    """年初数：本年 1 月 1 日之前所有已记账凭证的累计发生额，返回 {account_id: (debit, credit)}。
    用于资产负债表「年初余额」=上年末余额。首年无历史数据则为空（年初数=0）。"""
    d_start = date(year, 1, 1)
    rows = (
        db.session.query(
            VoucherItem.account_id,
            func.coalesce(func.sum(VoucherItem.debit_amount), 0).label("d"),
            func.coalesce(func.sum(VoucherItem.credit_amount), 0).label("c"),
        )
        .join(Voucher, Voucher.id == VoucherItem.voucher_id)
        .filter(Voucher.voucher_date < d_start)
        .filter(Voucher.status == Voucher.STATUS_POSTED)
        .group_by(VoucherItem.account_id)
        .all()
    )
    return {r.account_id: (r.d, r.c) for r in rows}


def _cashflow_for_period(year, month_start, month_end, accounts):
    """按现金/银行科目的对方科目，推算一段期间的经营现金流。
    返回 dict: {in, salary, tax, other}。仅统计已记账凭证。"""
    d_start = date(year, month_start, 1)
    d_end = date(year, 12, 31) if month_end == 12 else date(year, month_end + 1, 1)

    cash_acct_ids = {accounts[c].id for c in ("1001", "1002") if accounts.get(c)}
    result = {"in": 0.0, "salary": 0.0, "tax": 0.0, "other": 0.0}
    if not cash_acct_ids:
        return result

    salary_acct = accounts.get("2211")
    tax_accts = {accounts[c].id for c in ("2221", "2221.01", "2221.02", "2221.03")
                 if accounts.get(c)}

    vouchers = (
        Voucher.query
        .join(VoucherItem)
        .filter(VoucherItem.account_id.in_(cash_acct_ids))
        .filter(Voucher.voucher_date >= d_start, Voucher.voucher_date < d_end)
        .filter(Voucher.status == Voucher.STATUS_POSTED)
        .distinct()
        .all()
    )
    for v in vouchers:
        cash_debit = sum((i.debit_amount for i in v.items
                          if i.account_id in cash_acct_ids), 0)
        cash_credit = sum((i.credit_amount for i in v.items
                           if i.account_id in cash_acct_ids), 0)
        other_ids = {i.account_id for i in v.items if i.account_id not in cash_acct_ids}
        if cash_debit > 0:
            result["in"] += float(cash_debit)
        if cash_credit > 0:
            if salary_acct and salary_acct.id in other_ids:
                result["salary"] += float(cash_credit)
            elif tax_accts & other_ids:
                result["tax"] += float(cash_credit)
            else:
                result["other"] += float(cash_credit)
    return result


def _filing_checklist(year, quarter):
    """申报前结账检查清单：返回 (checks, has_error)。
    checks: [{level: 'error'|'warn'|'ok', text: str}]
    任何 error 都应阻止正式生成报表，避免报出不准确的申报数据。"""
    month_start = (quarter - 1) * 3 + 1
    month_end = quarter * 3
    d_start = date(year, month_start, 1)
    d_end = date(year, 12, 31) if month_end == 12 else date(year, month_end + 1, 1)

    checks = []
    has_error = False

    q_vouchers = (
        Voucher.query
        .filter(Voucher.voucher_date >= d_start, Voucher.voucher_date < d_end)
        .all()
    )

    # 1) 未过账凭证（草稿/已审核）不计入报表
    unposted = [v for v in q_vouchers
                if v.status in (Voucher.STATUS_DRAFT, Voucher.STATUS_REVIEWED)]
    if unposted:
        has_error = True
        nos = "、".join(v.voucher_no for v in unposted[:8])
        more = f" 等{len(unposted)}张" if len(unposted) > 8 else ""
        checks.append({"level": "error",
                       "text": f"有 {len(unposted)} 张凭证未记账（{nos}{more}），"
                               f"不会计入报表。请先到「记账」页面过账或作废。"})
    else:
        checks.append({"level": "ok", "text": "本季所有凭证均已记账或作废。"})

    # 2) 已记账凭证借贷平衡
    unbalanced = [v for v in q_vouchers
                  if v.status == Voucher.STATUS_POSTED and not v.is_balanced]
    if unbalanced:
        has_error = True
        nos = "、".join(v.voucher_no for v in unbalanced[:8])
        checks.append({"level": "error",
                       "text": f"有 {len(unbalanced)} 张已记账凭证借贷不平衡（{nos}），"
                               f"请红冲更正后再生成报表。"})
    else:
        checks.append({"level": "ok", "text": "已记账凭证全部借贷平衡。"})

    # 3) 各有损益发生额的月份是否均已期末结转
    accounts = {a.id: a for a in Account.query.all()}
    missing_carry = []
    for m in range(month_start, month_end + 1):
        msums = _period_sums(year, m, m)
        has_pl = any(
            accounts.get(aid) and accounts[aid].category in ("income", "expense")
            and (d > 0.005 or c > 0.005)
            for aid, (d, c) in msums.items()
        )
        if not has_pl:
            continue
        carry_no = f"转-{year}-{m:02d}"
        if not Voucher.query.filter_by(voucher_no=carry_no).first():
            missing_carry.append(m)
    if missing_carry:
        has_error = True
        months = "、".join(f"{m}月" for m in missing_carry)
        checks.append({"level": "error",
                       "text": f"{months} 有损益发生但尚未期末结转，"
                               f"资产负债表「未分配利润」将不准确。请先到「期末结转」完成结转。"})
    else:
        checks.append({"level": "ok", "text": "本季各月损益均已结转。"})

    # 4) 期间是否有已记账业务
    posted_cnt = sum(1 for v in q_vouchers if v.status == Voucher.STATUS_POSTED)
    if posted_cnt == 0:
        checks.append({"level": "warn",
                       "text": "本季没有任何已记账凭证，生成的报表将为空。"})
    else:
        checks.append({"level": "ok", "text": f"本季共 {posted_cnt} 张已记账凭证纳入报表。"})

    return checks, has_error


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
            status=Voucher.STATUS_POSTED,
            posted_at=datetime.now(),
            source=Voucher.SOURCE_SYSTEM,
        )
        db.session.add(v)
        db.session.flush()

        sort = 0
        profit_debit = 0
        profit_credit = 0

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

        log_audit("voucher", v.id, "carry_forward", "系统自动",
                  {"voucher_no": carry_no, "period": f"{year}-{month:02d}",
                   "net_profit": net_profit})
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

    # 申报前结账检查
    checklist, has_error = _filing_checklist(year, quarter)

    # 计算期间发生额
    sums = _period_sums(year, month_start, month_end)
    # 年初至今累计
    sums_ytd = _period_sums(year, 1, month_end)
    # 年初余额（上年末数）
    sums_year_begin = _sums_before(year)

    # 截至期末的全部累计发生额（含年初余额）：用于资产负债表期末余额
    # 资产负债表是时点报表，期末余额 = 上年末累计 + 本年累计发生额
    sums_full = {}
    for src in (sums_year_begin, sums_ytd):
        for aid, (d, c) in src.items():
            pd, pc = sums_full.get(aid, (0, 0))
            sums_full[aid] = (pd + d, pc + c)

    accounts = {a.code: a for a in Account.query.all()}
    acct_by_id = {a.id: a for a in Account.query.all()}

    def bal(code, use_sums=None):
        """获取科目期末余额（默认含年初余额的累计口径）"""
        acct = accounts.get(code)
        if not acct:
            return 0
        s = use_sums or sums_full
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

    def bal_y(code):
        """科目年初余额（上年末数）"""
        acct = accounts.get(code)
        if not acct:
            return 0
        return _account_balance(acct, sums_year_begin)

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

    # 年初数（上年末余额；首年无历史数据则自然为 0）
    bs["a1_y"] = bal_y("1001") + bal_y("1002")
    bs["a4_y"] = bal_y("1122")
    bs["a18_y"] = bal_y("1401")
    bs["a19_y"] = bal_y("1602")
    bs["l32_y"] = bal_y("2202")
    bs["l34_y"] = bal_y("2211")
    bs["l36_y"] = bal_y("2221") + bal_y("2221.01") + bal_y("2221.02") + bal_y("2221.03")
    bs["e48_y"] = bal_y("3001")
    bs["e49_y"] = bal_y("3101")
    bs["e51_y"] = bal_y("3131") + bal_y("3141")

    bs = calc_balance_sheet(bs)

    # ── 利润表 ──
    ist = {}
    # 本期数（当季）
    ist["r1"] = credit_sum("5001", sums)                       # 营业收入
    ist["r2"] = debit_sum("5401", sums)                        # 营业成本
    ist["r14"] = debit_sum("5602", sums) + debit_sum("5602.01", sums) + debit_sum("5602.02", sums) + debit_sum("5602.03", sums) + debit_sum("5602.04", sums)  # 管理费用
    ist["r18"] = debit_sum("5603", sums)                       # 财务费用
    ist["r22"] = credit_sum("5301", sums)                      # 营业外收入（含小规模增值税减免计入）
    ist["r24"] = debit_sum("5711", sums)                       # 营业外支出
    ist["r31"] = debit_sum("2221.03", sums)                    # 所得税费用

    # 累计数（年初至今）
    ist["r1_acc"] = credit_sum("5001", sums_ytd)
    ist["r2_acc"] = debit_sum("5401", sums_ytd)
    ist["r14_acc"] = debit_sum("5602", sums_ytd) + debit_sum("5602.01", sums_ytd) + debit_sum("5602.02", sums_ytd) + debit_sum("5602.03", sums_ytd) + debit_sum("5602.04", sums_ytd)
    ist["r18_acc"] = debit_sum("5603", sums_ytd)
    ist["r22_acc"] = credit_sum("5301", sums_ytd)             # 营业外收入累计
    ist["r24_acc"] = debit_sum("5711", sums_ytd)
    ist["r31_acc"] = debit_sum("2221.03", sums_ytd)

    ist = calc_income_stmt(ist)

    # ── 现金流量表（按现金/银行科目的对方科目推算经营现金流）──
    cf = {}
    # 本期（当季）
    q_cf = _cashflow_for_period(year, month_start, month_end, accounts)
    cf["c1"] = round(q_cf["in"], 2)                             # 销售收到的现金
    cf["c4"] = round(q_cf["salary"], 2)                         # 支付职工薪酬
    cf["c5"] = round(q_cf["tax"], 2)                            # 支付税费
    cf["c6"] = round(q_cf["other"], 2)                          # 支付其他经营活动现金

    # 本年累计（年初至本季末）
    ytd_cf = _cashflow_for_period(year, 1, month_end, accounts)
    cf["c1_acc"] = round(ytd_cf["in"], 2)
    cf["c4_acc"] = round(ytd_cf["salary"], 2)
    cf["c5_acc"] = round(ytd_cf["tax"], 2)
    cf["c6_acc"] = round(ytd_cf["other"], 2)

    # 期初现金：年初现金余额（上年末）
    cash_year_begin = float(bal_y("1001")) + float(bal_y("1002"))
    cf["c21_acc"] = round(cash_year_begin, 2)
    # 本季期初现金 = 年初现金 + 1月至上季末的现金净流量
    if month_start > 1:
        pre = _cashflow_for_period(year, 1, month_start - 1, accounts)
        pre_net = pre["in"] - pre["salary"] - pre["tax"] - pre["other"]
    else:
        pre_net = 0.0
    cf["c21"] = round(cash_year_begin + pre_net, 2)

    cf = calc_cashflow(cf)

    preview = {
        "bs": bs, "ist": ist, "cf": cf,
        "year": year, "quarter": quarter,
        "month_start": month_start, "month_end": month_end,
    }

    if request.method == "POST":
        # 有阻断级问题时，不允许生成正式报表
        if has_error:
            flash("结账检查未通过，请先处理下方红色提示项后再生成报表。", "danger")
            return redirect(url_for("closing.generate_report", year=year, quarter=quarter))

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

        if existing and existing.is_locked:
            flash(f"{year}年第{quarter}季度报表已锁定（申报口径），不能覆盖。"
                  f"如需重新生成，请先到预览页解锁。", "warning")
            return redirect(url_for("report.review", report_id=existing.id))

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
                           checklist=checklist, has_error=has_error,
                           active_page="generate_report")
