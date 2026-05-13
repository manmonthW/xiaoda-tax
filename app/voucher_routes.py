"""记账凭证路由"""
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Account, Voucher, VoucherItem

voucher_bp = Blueprint("voucher", __name__)


def _next_voucher_no():
    """生成下一个凭证编号：记-YYYY-NNN"""
    year = date.today().year
    prefix = f"记-{year}-"
    last = Voucher.query.filter(
        Voucher.voucher_no.like(f"{prefix}%")
    ).order_by(Voucher.voucher_no.desc()).first()
    if last:
        try:
            seq = int(last.voucher_no.replace(prefix, "")) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:03d}"


@voucher_bp.route("/")
def voucher_list():
    """凭证列表"""
    vouchers = Voucher.query.order_by(Voucher.voucher_date.desc(), Voucher.id.desc()).all()
    return render_template("voucher_list.html", vouchers=vouchers, active_page="voucher_list")


@voucher_bp.route("/new", methods=["GET", "POST"])
def voucher_new():
    """新建凭证"""
    if request.method == "POST":
        return _save_voucher(None)

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    voucher_no = _next_voucher_no()
    return render_template("voucher_edit.html",
                           voucher=None, voucher_no=voucher_no,
                           accounts=accounts, today=date.today().isoformat(),
                           active_page="voucher_new")


@voucher_bp.route("/<int:voucher_id>/edit", methods=["GET", "POST"])
def voucher_edit(voucher_id):
    """编辑凭证"""
    v = Voucher.query.get_or_404(voucher_id)
    if request.method == "POST":
        return _save_voucher(v)

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return render_template("voucher_edit.html",
                           voucher=v, voucher_no=v.voucher_no,
                           accounts=accounts, today=v.voucher_date.isoformat(),
                           active_page="voucher_edit")


@voucher_bp.route("/<int:voucher_id>/delete", methods=["POST"])
def voucher_delete(voucher_id):
    """删除凭证"""
    v = Voucher.query.get_or_404(voucher_id)
    db.session.delete(v)
    db.session.commit()
    flash(f"凭证 {v.voucher_no} 已删除", "info")
    return redirect(url_for("voucher.voucher_list"))


@voucher_bp.route("/accounts")
def account_list():
    """科目列表"""
    accounts = Account.query.order_by(Account.code).all()
    return render_template("account_list.html", accounts=accounts, active_page="account_list")


def _save_voucher(voucher):
    """保存凭证（新建或编辑通用）"""
    voucher_no = request.form.get("voucher_no", "").strip()
    voucher_date_str = request.form.get("voucher_date", "")
    notes = request.form.get("notes", "").strip()
    preparer = request.form.get("preparer", "").strip()

    try:
        voucher_date = date.fromisoformat(voucher_date_str)
    except (ValueError, TypeError):
        voucher_date = date.today()

    # 收集分录
    items_data = []
    idx = 0
    while True:
        acct_id = request.form.get(f"item_{idx}_account")
        if acct_id is None:
            break
        summary = request.form.get(f"item_{idx}_summary", "").strip()
        debit = request.form.get(f"item_{idx}_debit", "0").strip()
        credit = request.form.get(f"item_{idx}_credit", "0").strip()

        try:
            debit_val = float(debit) if debit else 0.0
        except ValueError:
            debit_val = 0.0
        try:
            credit_val = float(credit) if credit else 0.0
        except ValueError:
            credit_val = 0.0

        if int(acct_id) > 0 and (debit_val > 0 or credit_val > 0):
            items_data.append({
                "account_id": int(acct_id),
                "summary": summary,
                "debit_amount": debit_val,
                "credit_amount": credit_val,
                "sort_order": idx,
            })
        idx += 1

    if not items_data:
        flash("至少需要一条分录", "danger")
        return redirect(request.referrer or url_for("voucher.voucher_new"))

    # 验证借贷平衡
    total_d = sum(i["debit_amount"] for i in items_data)
    total_c = sum(i["credit_amount"] for i in items_data)
    if abs(total_d - total_c) >= 0.005:
        flash(f"借贷不平衡！借方合计 {total_d:.2f}，贷方合计 {total_c:.2f}", "danger")
        return redirect(request.referrer or url_for("voucher.voucher_new"))

    if voucher is None:
        voucher = Voucher(voucher_no=voucher_no, voucher_date=voucher_date,
                          notes=notes, preparer=preparer)
        db.session.add(voucher)
    else:
        voucher.voucher_no = voucher_no
        voucher.voucher_date = voucher_date
        voucher.notes = notes
        voucher.preparer = preparer
        # 清除旧分录
        VoucherItem.query.filter_by(voucher_id=voucher.id).delete()

    db.session.flush()

    for item in items_data:
        vi = VoucherItem(voucher_id=voucher.id, **item)
        db.session.add(vi)

    db.session.commit()
    flash(f"凭证 {voucher.voucher_no} 已保存", "success")
    return redirect(url_for("voucher.voucher_list"))
