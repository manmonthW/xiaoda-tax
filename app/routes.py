from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from app import db
from app.models import FinancialReport
from app.calc import calc_balance_sheet, calc_income_stmt, calc_cashflow
from app.export_xls import export_xls
from app.assistant import parse_query, generate_suggestion

main_bp = Blueprint("main", __name__)
report_bp = Blueprint("report", __name__)


def _nav_ctx(report=None, active_page="home"):
    """生成侧边栏导航上下文"""
    from flask import session as flask_session
    ctx = {"active_page": active_page, "report_id": None, "report_label": "",
           "ai_suggestion": None, "ai_query": "", "ai_just_analyzed": False}
    if report:
        ctx["report_id"] = report.id
        ctx["report_label"] = report.label
        # 恢复AI面板的上次结果
        ai_data = flask_session.get(f"ai_{report.id}")
        if ai_data:
            ctx["ai_query"] = ai_data.get("query", "")
            ctx["ai_suggestion"] = ai_data.get("suggestion")
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
    return render_template("index.html", reports=reports, **_nav_ctx(active_page='home'))


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
    db.session.delete(r)
    db.session.commit()
    flash(f"{r.label} 已删除", "info")
    return redirect(url_for("main.index"))


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
    # 保留 session 中的 AI 分析记录，方便用户重新打开抽屉查看历史
    flash("已将建议数据应用到三张报表！请逐一检查确认。", "success")
    return redirect(url_for("report.edit_bs", report_id=r.id))
