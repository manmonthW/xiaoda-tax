from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import QuarterlyReport, Invoice
from app.tax_calc import calculate_taxes
from app.report_pdf import generate_pdf
from flask import send_file

main_bp = Blueprint("main", __name__)
tax_bp = Blueprint("tax", __name__)


# ---------- 首页 ----------
@main_bp.route("/")
def index():
    reports = QuarterlyReport.query.order_by(
        QuarterlyReport.year.desc(), QuarterlyReport.quarter.desc()
    ).all()
    return render_template("index.html", reports=reports)


# ---------- 新建季度报税 ----------
@tax_bp.route("/new", methods=["GET", "POST"])
def new_report():
    if request.method == "POST":
        year = int(request.form["year"])
        quarter = int(request.form["quarter"])

        existing = QuarterlyReport.query.filter_by(year=year, quarter=quarter).first()
        if existing:
            flash(f"{year}年第{quarter}季度记录已存在", "warning")
            return redirect(url_for("tax.edit_report", report_id=existing.id))

        report = QuarterlyReport(year=year, quarter=quarter)
        db.session.add(report)
        db.session.commit()
        return redirect(url_for("tax.edit_report", report_id=report.id))

    from datetime import date

    today = date.today()
    current_quarter = (today.month - 1) // 3 + 1
    return render_template(
        "new_report.html", default_year=today.year, default_quarter=current_quarter
    )


# ---------- 编辑季度报税 ----------
@tax_bp.route("/<int:report_id>/edit", methods=["GET", "POST"])
def edit_report(report_id):
    report = QuarterlyReport.query.get_or_404(report_id)

    if request.method == "POST":
        report.income_total = float(request.form.get("income_total", 0))
        report.income_tax_free = float(request.form.get("income_tax_free", 0))
        report.vat_rate = float(request.form.get("vat_rate", 0.01))
        report.total_profit = float(request.form.get("total_profit", 0))
        report.income_tax_rate = float(request.form.get("income_tax_rate", 0.05))
        report.income_tax_prepaid = float(request.form.get("income_tax_prepaid", 0))
        report.stamp_tax = float(request.form.get("stamp_tax", 0))
        report.notes = request.form.get("notes", "")

        calculate_taxes(report)

        db.session.commit()
        flash("保存成功", "success")
        return redirect(url_for("tax.edit_report", report_id=report.id))

    return render_template("edit_report.html", report=report)


# ---------- 发票管理 ----------
@tax_bp.route("/<int:report_id>/invoice/add", methods=["POST"])
def add_invoice(report_id):
    report = QuarterlyReport.query.get_or_404(report_id)
    from datetime import date

    invoice = Invoice(
        report_id=report.id,
        date=date.fromisoformat(request.form["date"]),
        invoice_no=request.form.get("invoice_no", ""),
        buyer=request.form.get("buyer", ""),
        amount=float(request.form["amount"]),
        tax_amount=float(request.form.get("tax_amount", 0)),
        invoice_type=request.form.get("invoice_type", "normal"),
        notes=request.form.get("invoice_notes", ""),
    )
    db.session.add(invoice)
    db.session.commit()
    flash("发票已添加", "success")
    return redirect(url_for("tax.edit_report", report_id=report.id))


@tax_bp.route("/invoice/<int:invoice_id>/delete", methods=["POST"])
def delete_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    report_id = invoice.report_id
    db.session.delete(invoice)
    db.session.commit()
    flash("发票已删除", "info")
    return redirect(url_for("tax.edit_report", report_id=report_id))


# ---------- 生成PDF报表 ----------
@tax_bp.route("/<int:report_id>/pdf")
def download_pdf(report_id):
    report = QuarterlyReport.query.get_or_404(report_id)
    pdf_buffer = generate_pdf(report)
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"xiaoda_{report.year}Q{report.quarter}_report.pdf",
    )


# ---------- 删除季度记录 ----------
@tax_bp.route("/<int:report_id>/delete", methods=["POST"])
def delete_report(report_id):
    report = QuarterlyReport.query.get_or_404(report_id)
    Invoice.query.filter_by(report_id=report.id).delete()
    db.session.delete(report)
    db.session.commit()
    flash(f"{report.year}Q{report.quarter} 已删除", "info")
    return redirect(url_for("main.index"))
