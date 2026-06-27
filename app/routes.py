from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from app import db
from app.models import FinancialReport, Voucher, VoucherItem, Account, to_money, log_audit, next_voucher_no
from app.calc import calc_balance_sheet, calc_income_stmt, calc_cashflow
from app.export_xls import export_xls
from app.assistant import parse_query, generate_suggestion
from datetime import date, datetime

main_bp = Blueprint("main", __name__)
report_bp = Blueprint("report", __name__)


def _nav_ctx(report=None, active_page="home"):
    """生成侧边栏导航上下文"""
    from flask import session as flask_session
    ctx = {"active_page": active_page, "report_id": None, "report_label": "",
           "ai_suggestion": None, "ai_query": "", "ai_just_analyzed": False,
           "ai_can_undo": False}
    if report:
        ctx["report_id"] = report.id
        ctx["report_label"] = report.label
        # 恢复AI面板的上次结果
        ai_data = flask_session.get(f"ai_{report.id}")
        if ai_data:
            ctx["ai_query"] = ai_data.get("query", "")
            ctx["ai_suggestion"] = ai_data.get("suggestion")
        # 是否有可撤销的快照
        if flask_session.get(f"ai_undo_{report.id}"):
            ctx["ai_can_undo"] = True
        # 仅在刚刚分析完成后自动展开抽屉，取出后立即清除标志
        if flask_session.pop(f"ai_open_{report.id}", False):
            ctx["ai_just_analyzed"] = True
    return ctx


@main_bp.route("/")
def index():
    reports = FinancialReport.query.order_by(
        FinancialReport.year.desc(),
        FinancialReport.quarter.desc()
    ).all()
    stats = {
        "voucher_count": Voucher.query.filter(
            ~Voucher.voucher_no.like("转-%")).count(),
        "account_count": Account.query.filter_by(is_active=True).count(),
        "report_count": len(reports),
    }
    return render_template("index.html", reports=reports, stats=stats,
                           **_nav_ctx(active_page='home'))


@main_bp.route("/reports")
def reports():
    reports = FinancialReport.query.order_by(
        FinancialReport.year.desc(),
        FinancialReport.quarter.desc()
    ).all()
    return render_template("report_list.html", reports=reports,
                           **_nav_ctx(active_page='reports'))


@report_bp.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "POST":
        rtype = request.form["report_type"]
        year = int(request.form["year"])
        quarter = int(request.form.get("quarter", 0)) or None
        taxpayer_id = request.form.get("taxpayer_id", "")
        taxpayer_name = request.form.get("taxpayer_name", "")

        if rtype == "quarterly" and quarter:
            period_start = f"{year}-{(quarter-1)*3+1:02d}-01"
            m_end = quarter * 3
            period_end = f"{year}-{m_end:02d}-{'30' if m_end in (4,6,9,11) else '31'}"
            if m_end == 2:
                period_end = f"{year}-02-28"
        else:
            period_start = f"{year}-01-01"
            period_end = f"{year}-12-31"

        r = FinancialReport(
            report_type=rtype, year=year, quarter=quarter,
            taxpayer_id=taxpayer_id, taxpayer_name=taxpayer_name,
            period_start=period_start, period_end=period_end,
        )
        db.session.add(r)
        db.session.commit()
        return redirect(url_for("report.edit_bs", report_id=r.id))

    from datetime import date
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return render_template("new_report.html", year=today.year, quarter=q, **_nav_ctx(active_page='home'))


def _collect_form(prefix, form):
    """从表单中收集指定前缀的字段"""
    data = {}
    for key in form:
        if key.startswith(prefix):
            val = form[key].strip()
            data[key[len(prefix):]] = float(val) if val else 0.0
    return data


# ---------- Step 1: 资产负债表 ----------
@report_bp.route("/<int:report_id>/bs", methods=["GET", "POST"])
def edit_bs(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    if request.method == "POST":
        if r.is_locked:
            flash(f"{r.label} 已锁定，不能修改。如需更正请先解锁。", "warning")
            return redirect(url_for("report.edit_bs", report_id=r.id))
        bs = _collect_form("bs_", request.form)
        bs = calc_balance_sheet(bs)
        r.set_bs(bs)
        r.taxpayer_id = request.form.get("taxpayer_id", r.taxpayer_id)
        r.taxpayer_name = request.form.get("taxpayer_name", r.taxpayer_name)
        db.session.commit()
        flash("资产负债表已保存", "success")
        if request.form.get("action") == "next":
            return redirect(url_for("report.edit_is", report_id=r.id))
        return redirect(url_for("report.edit_bs", report_id=r.id))
    return render_template("edit_bs.html", r=r, bs=r.get_bs(), **_nav_ctx(r, 'bs'))


# ---------- Step 2: 利润表 ----------
@report_bp.route("/<int:report_id>/is", methods=["GET", "POST"])
def edit_is(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    if request.method == "POST":
        if r.is_locked:
            flash(f"{r.label} 已锁定，不能修改。如需更正请先解锁。", "warning")
            return redirect(url_for("report.edit_is", report_id=r.id))
        ist = _collect_form("is_", request.form)
        ist = calc_income_stmt(ist)
        r.set_is(ist)
        db.session.commit()
        flash("利润表已保存", "success")
        if request.form.get("action") == "next":
            return redirect(url_for("report.edit_cf", report_id=r.id))
        return redirect(url_for("report.edit_is", report_id=r.id))
    return render_template("edit_is.html", r=r, ist=r.get_is(), **_nav_ctx(r, 'is'))


# ---------- Step 3: 现金流量表 ----------
@report_bp.route("/<int:report_id>/cf", methods=["GET", "POST"])
def edit_cf(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    if request.method == "POST":
        if r.is_locked:
            flash(f"{r.label} 已锁定，不能修改。如需更正请先解锁。", "warning")
            return redirect(url_for("report.edit_cf", report_id=r.id))
        cf = _collect_form("cf_", request.form)
        cf = calc_cashflow(cf)
        r.set_cf(cf)
        db.session.commit()
        flash("现金流量表已保存", "success")
        if request.form.get("action") == "next":
            return redirect(url_for("report.review", report_id=r.id))
        return redirect(url_for("report.edit_cf", report_id=r.id))
    return render_template("edit_cf.html", r=r, cf=r.get_cf(), **_nav_ctx(r, 'cf'))


# ---------- Step 4: 预览 ----------
@report_bp.route("/<int:report_id>/review")
def review(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    return render_template("review.html", r=r, bs=r.get_bs(), ist=r.get_is(), cf=r.get_cf(), **_nav_ctx(r, 'review'))


# ---------- 导出XLS ----------
@report_bp.route("/<int:report_id>/export")
def export(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    buf = export_xls(r)
    fname = f"CWBB_{r.taxpayer_name}_{r.label}.xls"
    return send_file(buf, mimetype="application/vnd.ms-excel",
                     as_attachment=True, download_name=fname)


# ---------- 删除 ----------
@report_bp.route("/<int:report_id>/delete", methods=["POST"])
def delete(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    if r.is_locked:
        flash(f"{r.label} 已锁定（已申报口径），不能删除。如需删除请先解锁。", "warning")
        return redirect(url_for("main.index"))
    db.session.delete(r)
    db.session.commit()
    flash(f"{r.label} 已删除", "info")
    return redirect(url_for("main.index"))


# ---------- 锁定 / 解锁（申报口径冻结）----------
@report_bp.route("/<int:report_id>/lock", methods=["POST"])
def lock(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    if r.is_locked:
        flash(f"{r.label} 已是锁定状态。", "info")
        return redirect(url_for("report.review", report_id=r.id))
    actor = (request.form.get("actor") or "").strip()
    r.is_locked = True
    r.locked_at = datetime.now()
    r.locked_by = actor
    log_audit("report", r.id, "lock", actor,
              {"label": r.label, "period": f"{r.period_start}~{r.period_end}"})
    db.session.commit()
    flash(f"{r.label} 已锁定，可用于申报。锁定后不可修改/覆盖/删除。", "success")
    return redirect(url_for("report.review", report_id=r.id))


@report_bp.route("/<int:report_id>/unlock", methods=["POST"])
def unlock(report_id):
    r = FinancialReport.query.get_or_404(report_id)
    if not r.is_locked:
        flash(f"{r.label} 未锁定。", "info")
        return redirect(url_for("report.review", report_id=r.id))
    actor = (request.form.get("actor") or "").strip()
    r.is_locked = False
    r.locked_at = None
    r.locked_by = ""
    log_audit("report", r.id, "unlock", actor, {"label": r.label})
    db.session.commit()
    flash(f"{r.label} 已解锁，可重新修改或生成。", "info")
    return redirect(url_for("report.review", report_id=r.id))


# ---------- AI 填表助手（面板） ----------
@report_bp.route("/<int:report_id>/assistant", methods=["GET"])
def assistant(report_id):
    """兼容旧链接，重定向到资产负债表页"""
    return redirect(url_for("report.edit_bs", report_id=report_id))


@report_bp.route("/<int:report_id>/assistant_api", methods=["POST"])
def assistant_api(report_id):
    """AI面板：分析请求，保存结果到session后返回来源页"""
    from flask import session as flask_session
    r = FinancialReport.query.get_or_404(report_id)
    query_text = request.form.get("query", "").strip()
    if query_text:
        info = parse_query(query_text)
        suggestion = generate_suggestion(info)
        flask_session[f"ai_{r.id}"] = {"query": query_text, "suggestion": suggestion}
        flask_session[f"ai_open_{r.id}"] = True
    referer = request.referrer or url_for("report.edit_bs", report_id=r.id)
    return redirect(referer)


@report_bp.route("/<int:report_id>/assistant_apply", methods=["POST"])
def assistant_apply(report_id):
    """AI面板：将建议应用到三张报表"""
    from flask import session as flask_session
    r = FinancialReport.query.get_or_404(report_id)
    ai_data = flask_session.get(f"ai_{r.id}")
    if not ai_data or not ai_data.get("suggestion"):
        flash("没有可应用的建议，请先分析", "warning")
        return redirect(request.referrer or url_for("report.edit_bs", report_id=r.id))

    suggestion = ai_data["suggestion"]
    bs = r.get_bs()
    ist = r.get_is()
    cf = r.get_cf()

    # 保存快照用于撤销
    flask_session[f"ai_undo_{r.id}"] = {
        "bs": bs.copy(),
        "is": ist.copy(),
        "cf": cf.copy(),
    }

    for key, item in suggestion["balance_sheet"].items():
        bs[key] = item["value"]
    bs = calc_balance_sheet(bs)
    r.set_bs(bs)

    for key, item in suggestion["income_stmt"].items():
        ist[key] = item["value"]
        ist[key + "_acc"] = item["value"]
    ist = calc_income_stmt(ist)
    r.set_is(ist)

    for key, item in suggestion["cashflow_stmt"].items():
        cf[key] = item["value"]
        cf[key + "_acc"] = item["value"]
    cf = calc_cashflow(cf)
    r.set_cf(cf)

    db.session.commit()
    flash("已将建议数据应用到三张报表！如需撤销，请点击 AI 助手中的「撤销应用」按钮。", "success")
    return redirect(url_for("report.edit_bs", report_id=r.id))


@report_bp.route("/<int:report_id>/assistant_undo", methods=["POST"])
def assistant_undo(report_id):
    """撤销上一次 AI 应用，恢复报表数据"""
    from flask import session as flask_session
    r = FinancialReport.query.get_or_404(report_id)
    snapshot = flask_session.pop(f"ai_undo_{r.id}", None)
    if not snapshot:
        flash("没有可撤销的操作", "warning")
        return redirect(request.referrer or url_for("report.edit_bs", report_id=r.id))

    r.set_bs(snapshot["bs"])
    r.set_is(snapshot["is"])
    r.set_cf(snapshot["cf"])
    db.session.commit()
    flash("已撤销，报表已恢复到应用前的状态。", "info")
    return redirect(url_for("report.edit_bs", report_id=r.id))


@report_bp.route("/<int:report_id>/assistant_create_vouchers", methods=["POST"])
def assistant_create_vouchers(report_id):
    """AI面板：根据工资建议一键生成记账凭证"""
    from flask import session as flask_session
    r = FinancialReport.query.get_or_404(report_id)
    ai_data = flask_session.get(f"ai_{r.id}")
    if not ai_data or not ai_data.get("suggestion") or not ai_data["suggestion"].get("vouchers"):
        flash("没有可生成的凭证建议，请先分析工资记账场景", "warning")
        return redirect(request.referrer or url_for("report.edit_bs", report_id=r.id))

    vouchers_data = ai_data["suggestion"]["vouchers"]

    today = date.today()
    raw_text = (ai_data.get("query") or "").strip()

    created_count = 0
    for v_data in vouchers_data:
        voucher = Voucher(
            voucher_no=next_voucher_no("记"),
            voucher_date=today,
            notes=v_data["notes"],
            preparer="AI助手",
            status=Voucher.STATUS_POSTED,
            posted_at=datetime.now(),
            source=Voucher.SOURCE_AI,
            raw_text=raw_text,
        )
        db.session.add(voucher)
        db.session.flush()  # 获取 voucher.id，并让下一次发号器看到本张

        for j, item_data in enumerate(v_data["entries"]):
            account = Account.query.filter_by(code=item_data["account_code"]).first()
            if not account:
                continue
            vi = VoucherItem(
                voucher_id=voucher.id,
                account_id=account.id,
                summary=item_data["summary"],
                debit_amount=to_money(item_data.get("debit", 0)),
                credit_amount=to_money(item_data.get("credit", 0)),
                sort_order=j,
            )
            db.session.add(vi)
        log_audit("voucher", voucher.id, "ai_generate", "AI助手",
                  {"voucher_no": voucher.voucher_no, "notes": voucher.notes,
                   "raw_text": raw_text})
        created_count += 1

    db.session.commit()
    flash(f"已生成 {created_count} 张记账凭证！请到「记账」页面查看。", "success")
    return redirect(url_for("report.edit_bs", report_id=r.id))
