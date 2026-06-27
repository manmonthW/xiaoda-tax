"""AI 记账路由：自然语言 → 凭证草稿 → 人工确认后落为草稿（待记账）。"""
from datetime import date, datetime
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, session as flask_session)
from app import db
from app.models import (Account, Voucher, VoucherItem, to_money, log_audit,
                        next_voucher_no, is_period_locked)
from app.bookkeeping import parse_bookkeeping

bookkeeping_bp = Blueprint("bookkeeping", __name__)

SESSION_KEY = "ai_bk_proposals"


@bookkeeping_bp.route("/")
def index():
    """AI 记账主页面。"""
    return render_template("ai_bookkeeping.html", active_page="ai_bookkeeping",
                           today=date.today().isoformat())


@bookkeeping_bp.route("/parse", methods=["POST"])
def parse():
    """解析自然语言，返回凭证草稿提案（JSON），并暂存到 session 供确认。"""
    payload_in = request.get_json(silent=True) if request.is_json else None
    if payload_in is None:
        payload_in = request.form
    text = (payload_in.get("text") or "").strip()
    date_str = (payload_in.get("date") or "")
    try:
        default_date = date.fromisoformat(date_str) if date_str else date.today()
    except (ValueError, TypeError):
        default_date = date.today()

    result = parse_bookkeeping(text, default_date)

    # 暂存（日期转字符串以便 JSON 序列化）
    stored = []
    for v in result.get("vouchers", []):
        sv = dict(v)
        sv["date"] = v["date"].isoformat() if isinstance(v["date"], date) else v["date"]
        stored.append(sv)
    flask_session[SESSION_KEY] = {"text": text, "vouchers": stored}

    # 同样把日期字符串化返回前端
    payload = dict(result)
    payload["vouchers"] = stored
    return jsonify(payload)


@bookkeeping_bp.route("/confirm", methods=["POST"])
def confirm():
    """把用户选中的提案保存为草稿凭证（status=draft, source=ai）。"""
    data = flask_session.get(SESSION_KEY)
    if not data or not data.get("vouchers"):
        flash("没有可保存的凭证提案，请先解析业务描述。", "warning")
        return redirect(url_for("bookkeeping.index"))

    raw_text = data.get("text", "")
    selected = request.form.getlist("selected")  # 选中的提案下标
    if not selected:
        flash("请至少勾选一张凭证再保存。", "warning")
        return redirect(url_for("bookkeeping.index"))
    selected_idx = {int(i) for i in selected if i.isdigit()}

    created = 0
    skipped = []
    for idx, v in enumerate(data["vouchers"]):
        if idx not in selected_idx:
            continue
        try:
            v_date = date.fromisoformat(v["date"])
        except (ValueError, TypeError):
            v_date = date.today()

        if is_period_locked(v_date):
            skipped.append(f"{v.get('summary', '')}（{v_date} 已关账）")
            continue

        voucher = Voucher(
            voucher_no=next_voucher_no("记"),
            voucher_date=v_date,
            notes=v.get("summary", ""),
            preparer="AI助手",
            status=Voucher.STATUS_DRAFT,        # 草稿：待人工确认记账
            source=Voucher.SOURCE_AI,
            raw_text=raw_text,
            ai_confidence=float(v.get("confidence") or 0),
        )
        db.session.add(voucher)
        db.session.flush()

        for j, e in enumerate(v.get("entries", [])):
            acct = Account.query.filter_by(code=e["account_code"]).first()
            if not acct:
                continue
            db.session.add(VoucherItem(
                voucher_id=voucher.id,
                account_id=acct.id,
                summary=e.get("summary", ""),
                debit_amount=to_money(e.get("debit", 0)),
                credit_amount=to_money(e.get("credit", 0)),
                sort_order=j,
            ))
        log_audit("voucher", voucher.id, "ai_generate", "AI助手",
                  {"voucher_no": voucher.voucher_no, "scenario": v.get("scenario"),
                   "confidence": v.get("confidence"), "raw_text": raw_text})
        created += 1

    db.session.commit()
    flask_session.pop(SESSION_KEY, None)

    if created:
        flash(f"已生成 {created} 张草稿凭证，请到「记账」页面核对后点击「记账」过账。", "success")
    if skipped:
        flash("以下凭证因期间已关账未保存：" + "；".join(skipped), "warning")
    if not created and not skipped:
        flash("未保存任何凭证。", "info")
    return redirect(url_for("voucher.voucher_list"))
