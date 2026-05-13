"""账簿查询路由：科目余额表、明细账、总账"""
from datetime import date
from flask import Blueprint, render_template, request
from sqlalchemy import func, extract
from app import db
from app.models import Account, Voucher, VoucherItem

ledger_bp = Blueprint("ledger", __name__)


def _parse_period(args):
    """从请求参数解析年月范围"""
    today = date.today()
    year = int(args.get("year", today.year))
    month_start = int(args.get("month_start", 1))
    month_end = int(args.get("month_end", today.month))
    return year, month_start, month_end


def _period_filter(query, year, month_start, month_end):
    """对 Voucher.voucher_date 施加年月范围过滤"""
    d_start = date(year, month_start, 1)
    if month_end == 12:
        d_end = date(year, 12, 31)
    else:
        d_end = date(year, month_end + 1, 1)  # exclusive
    return query.filter(Voucher.voucher_date >= d_start, Voucher.voucher_date < d_end)


# ────────────────────────────────────────────────────────
# 科目余额表
# ────────────────────────────────────────────────────────
@ledger_bp.route("/balance")
def trial_balance():
    """科目余额表：汇总各科目期间借贷发生额和期末余额"""
    year, m1, m2 = _parse_period(request.args)

    # 查询期间内所有分录汇总
    q = (
        db.session.query(
            VoucherItem.account_id,
            func.coalesce(func.sum(VoucherItem.debit_amount), 0).label("sum_debit"),
            func.coalesce(func.sum(VoucherItem.credit_amount), 0).label("sum_credit"),
        )
        .join(Voucher, Voucher.id == VoucherItem.voucher_id)
    )
    q = _period_filter(q, year, m1, m2)
    q = q.group_by(VoucherItem.account_id)
    sums = {row.account_id: (row.sum_debit, row.sum_credit) for row in q.all()}

    accounts = Account.query.order_by(Account.code).all()
    rows = []
    total_debit = total_credit = 0
    for acct in accounts:
        d, c = sums.get(acct.id, (0, 0))
        if d == 0 and c == 0:
            continue
        # 余额 = 根据余额方向计算
        if acct.balance_dir == "debit":
            balance = d - c
        else:
            balance = c - d
        rows.append({
            "account": acct,
            "debit": d,
            "credit": c,
            "balance": balance,
            "balance_dir": "借" if balance >= 0 else "贷",
            "balance_abs": abs(balance),
        })
        total_debit += d
        total_credit += c

    return render_template("ledger_balance.html",
                           rows=rows, year=year, month_start=m1, month_end=m2,
                           total_debit=total_debit, total_credit=total_credit,
                           active_page="trial_balance")


# ────────────────────────────────────────────────────────
# 明细账
# ────────────────────────────────────────────────────────
@ledger_bp.route("/detail")
def detail_ledger():
    """明细账：显示某科目在期间内的所有分录，逐笔计算余额"""
    year, m1, m2 = _parse_period(request.args)
    account_id = request.args.get("account_id", type=int)

    accounts = Account.query.order_by(Account.code).all()
    entries = []
    account = None
    running_balance = 0

    if account_id:
        account = Account.query.get(account_id)
        if account:
            q = (
                db.session.query(VoucherItem, Voucher)
                .join(Voucher, Voucher.id == VoucherItem.voucher_id)
                .filter(VoucherItem.account_id == account_id)
            )
            q = _period_filter(q, year, m1, m2)
            q = q.order_by(Voucher.voucher_date, Voucher.id, VoucherItem.sort_order)

            for item, voucher in q.all():
                if account.balance_dir == "debit":
                    running_balance += item.debit_amount - item.credit_amount
                else:
                    running_balance += item.credit_amount - item.debit_amount
                entries.append({
                    "date": voucher.voucher_date,
                    "voucher_no": voucher.voucher_no,
                    "summary": item.summary or voucher.notes,
                    "debit": item.debit_amount,
                    "credit": item.credit_amount,
                    "balance": running_balance,
                    "balance_dir": "借" if running_balance >= 0 else "贷",
                    "balance_abs": abs(running_balance),
                })

    return render_template("ledger_detail.html",
                           entries=entries, account=account, accounts=accounts,
                           year=year, month_start=m1, month_end=m2,
                           active_page="detail_ledger")


# ────────────────────────────────────────────────────────
# 总账
# ────────────────────────────────────────────────────────
@ledger_bp.route("/general")
def general_ledger():
    """总账：按科目按月汇总发生额"""
    year, m1, m2 = _parse_period(request.args)

    # 按科目 + 月份汇总
    q = (
        db.session.query(
            VoucherItem.account_id,
            extract("month", Voucher.voucher_date).label("month"),
            func.coalesce(func.sum(VoucherItem.debit_amount), 0).label("sum_debit"),
            func.coalesce(func.sum(VoucherItem.credit_amount), 0).label("sum_credit"),
        )
        .join(Voucher, Voucher.id == VoucherItem.voucher_id)
    )
    q = _period_filter(q, year, m1, m2)
    q = q.group_by(VoucherItem.account_id, "month")

    # 组织数据：{account_id: [(month, debit, credit), ...]}
    from collections import defaultdict
    acct_months = defaultdict(list)
    for row in q.all():
        acct_months[row.account_id].append({
            "month": int(row.month),
            "debit": row.sum_debit,
            "credit": row.sum_credit,
        })

    accounts_map = {a.id: a for a in Account.query.all()}
    ledger_data = []
    for acct_id in sorted(acct_months.keys(), key=lambda x: accounts_map[x].code):
        acct = accounts_map[acct_id]
        months = sorted(acct_months[acct_id], key=lambda x: x["month"])
        total_d = sum(m["debit"] for m in months)
        total_c = sum(m["credit"] for m in months)
        if acct.balance_dir == "debit":
            balance = total_d - total_c
        else:
            balance = total_c - total_d
        ledger_data.append({
            "account": acct,
            "months": months,
            "total_debit": total_d,
            "total_credit": total_c,
            "balance": balance,
            "balance_dir": "借" if balance >= 0 else "贷",
            "balance_abs": abs(balance),
        })

    return render_template("ledger_general.html",
                           ledger_data=ledger_data,
                           year=year, month_start=m1, month_end=m2,
                           active_page="general_ledger")
