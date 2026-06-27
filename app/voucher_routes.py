"""记账凭证路由"""
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Account, Voucher, VoucherItem, to_money, log_audit, next_voucher_no, is_period_locked

voucher_bp = Blueprint("voucher", __name__)


def _next_voucher_no():
    """生成下一个凭证编号：记-YYYY-NNN（统一调用 models.next_voucher_no）"""
    return next_voucher_no("记")


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
    if not v.is_editable:
        flash(f"凭证 {v.voucher_no} 当前为「{v.status_label}」，不可编辑。"
              f"如需更正，请使用作废或红冲。", "warning")
        return redirect(url_for("voucher.voucher_list"))
    if request.method == "POST":
        return _save_voucher(v)

    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return render_template("voucher_edit.html",
                           voucher=v, voucher_no=v.voucher_no,
                           accounts=accounts, today=v.voucher_date.isoformat(),
                           active_page="voucher_edit")


@voucher_bp.route("/<int:voucher_id>/post", methods=["POST"])
def voucher_post(voucher_id):
    """记账（过账）：草稿/已审核 → 已记账。需借贷平衡且期间未关账。"""
    v = Voucher.query.get_or_404(voucher_id)
    if v.status not in (Voucher.STATUS_DRAFT, Voucher.STATUS_REVIEWED):
        flash(f"凭证 {v.voucher_no} 当前为「{v.status_label}」，无需记账。", "info")
        return redirect(url_for("voucher.voucher_list"))
    if not v.is_balanced:
        flash(f"凭证 {v.voucher_no} 借贷不平衡，不能记账，请先修改。", "danger")
        return redirect(url_for("voucher.voucher_list"))
    if is_period_locked(v.voucher_date):
        flash(f"{v.voucher_date.year}年{v.voucher_date.month}月已关账，不能记账到该期间。", "danger")
        return redirect(url_for("voucher.voucher_list"))

    actor = (request.form.get("actor") or "").strip()
    old_status = v.status
    v.status = Voucher.STATUS_POSTED
    v.posted_at = datetime.now()
    log_audit("voucher", v.id, "post", actor,
              {"voucher_no": v.voucher_no, "from": old_status, "to": v.status})
    db.session.commit()
    flash(f"凭证 {v.voucher_no} 已记账。", "success")
    return redirect(url_for("voucher.voucher_list"))


@voucher_bp.route("/<int:voucher_id>/void", methods=["POST"])
def voucher_void(voucher_id):
    """作废凭证（仅限草稿/已审核，未记账）。不物理删除，保留留痕。"""
    v = Voucher.query.get_or_404(voucher_id)
    if v.status == Voucher.STATUS_VOID:
        flash(f"凭证 {v.voucher_no} 已是作废状态", "info")
        return redirect(url_for("voucher.voucher_list"))
    if v.status == Voucher.STATUS_POSTED:
        flash(f"凭证 {v.voucher_no} 已记账，不能直接作废，请使用「红冲」冲销。", "warning")
        return redirect(url_for("voucher.voucher_list"))

    actor = (request.form.get("actor") or "").strip()
    old_status = v.status
    v.status = Voucher.STATUS_VOID
    v.voided_at = datetime.now()
    log_audit("voucher", v.id, "void", actor,
              {"voucher_no": v.voucher_no, "from": old_status, "to": v.status})
    db.session.commit()
    flash(f"凭证 {v.voucher_no} 已作废（留痕保存，未删除）", "info")
    return redirect(url_for("voucher.voucher_list"))


@voucher_bp.route("/<int:voucher_id>/reverse", methods=["POST"])
def voucher_reverse(voucher_id):
    """红字冲销已记账凭证：生成一张借贷反向的冲销凭证，原凭证标记已红冲。"""
    v = Voucher.query.get_or_404(voucher_id)
    if v.status != Voucher.STATUS_POSTED:
        flash(f"仅「已记账」凭证可红冲，当前为「{v.status_label}」。", "warning")
        return redirect(url_for("voucher.voucher_list"))
    if v.is_reversed:
        flash(f"凭证 {v.voucher_no} 已被红冲，不能重复冲销。", "warning")
        return redirect(url_for("voucher.voucher_list"))

    actor = (request.form.get("actor") or "").strip()
    rev = Voucher(
        voucher_no=next_voucher_no("记", v.voucher_date),
        voucher_date=date.today(),
        notes=f"红冲：{v.voucher_no} {v.notes or ''}".strip(),
        preparer=actor or "system",
        status=Voucher.STATUS_POSTED,
        posted_at=datetime.now(),
        source=Voucher.SOURCE_SYSTEM,
        reversal_of_id=v.id,
    )
    db.session.add(rev)
    db.session.flush()

    # 借贷互换实现红冲（等额反向）
    for it in v.items:
        db.session.add(VoucherItem(
            voucher_id=rev.id,
            account_id=it.account_id,
            summary=f"红冲 {it.summary or ''}".strip(),
            debit_amount=it.credit_amount,
            credit_amount=it.debit_amount,
            sort_order=it.sort_order,
        ))

    v.is_reversed = True
    log_audit("voucher", v.id, "reverse", actor,
              {"voucher_no": v.voucher_no, "reversal_voucher_no": rev.voucher_no})
    log_audit("voucher", rev.id, "create", actor or "system",
              {"voucher_no": rev.voucher_no, "reversal_of": v.voucher_no, "source": "system"})
    db.session.commit()
    flash(f"已生成红冲凭证 {rev.voucher_no}（原凭证 {v.voucher_no} 保留留痕）", "success")
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

    # 期间锁定：已结转月份不允许再增改普通凭证
    if is_period_locked(voucher_date):
        flash(f"{voucher_date.year}年{voucher_date.month}月已期末结转（关账），"
              f"不能在该期间新增或修改凭证。如需更正，请红冲相关凭证。", "danger")
        return redirect(request.referrer or url_for("voucher.voucher_list"))

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
            debit_val = to_money(debit) if debit else to_money(0)
        except (ValueError, ArithmeticError):
            debit_val = to_money(0)
        try:
            credit_val = to_money(credit) if credit else to_money(0)
        except (ValueError, ArithmeticError):
            credit_val = to_money(0)

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
                          notes=notes, preparer=preparer,
                          status=Voucher.STATUS_POSTED, posted_at=datetime.now(),
                          source=Voucher.SOURCE_MANUAL)
        db.session.add(voucher)
        is_new = True
    else:
        voucher.voucher_no = voucher_no
        voucher.voucher_date = voucher_date
        voucher.notes = notes
        voucher.preparer = preparer
        # 清除旧分录
        VoucherItem.query.filter_by(voucher_id=voucher.id).delete()
        is_new = False

    db.session.flush()

    for item in items_data:
        vi = VoucherItem(voucher_id=voucher.id, **item)
        db.session.add(vi)

    log_audit("voucher", voucher.id, "create" if is_new else "update", preparer,
              {"voucher_no": voucher.voucher_no,
               "total_debit": total_d, "total_credit": total_c,
               "items": len(items_data)})
    db.session.commit()
    flash(f"凭证 {voucher.voucher_no} 已保存", "success")
    return redirect(url_for("voucher.voucher_list"))
