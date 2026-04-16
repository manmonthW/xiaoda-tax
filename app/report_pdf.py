"""生成季度报税PDF报表"""
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 尝试注册中文字体
_chinese_font = "Helvetica"
_font_paths = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
for fp in _font_paths:
    try:
        pdfmetrics.registerFont(TTFont("Chinese", fp))
        _chinese_font = "Chinese"
        break
    except Exception:
        continue


def generate_pdf(report):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=15 * mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CNTitle", parent=styles["Title"], fontName=_chinese_font, fontSize=18
    )
    normal_style = ParagraphStyle(
        "CNNormal", parent=styles["Normal"], fontName=_chinese_font, fontSize=10
    )

    elements = []

    # 标题
    elements.append(Paragraph(f"xiaoda {report.year}年第{report.quarter}季度报税汇总", title_style))
    elements.append(Spacer(1, 10 * mm))

    # 基本信息
    elements.append(Paragraph(f"状态: {report.status}", normal_style))
    elements.append(Spacer(1, 5 * mm))

    # 税费明细表
    vat_display = "免征" if report.vat_exempt else f"¥{report.vat_amount:,.2f}"
    data = [
        ["项目", "金额 (元)"],
        ["营业收入合计（含税）", f"¥{report.income_total:,.2f}"],
        ["免税收入", f"¥{report.income_tax_free:,.2f}"],
        ["应税收入（不含税）", f"¥{report.income_taxable:,.2f}"],
        [f"增值税（征收率{report.vat_rate*100:.0f}%）", vat_display],
        ["城市维护建设税", f"¥{report.urban_maintenance_tax:,.2f}"],
        ["教育费附加", f"¥{report.education_surcharge:,.2f}"],
        ["地方教育附加", f"¥{report.local_education_surcharge:,.2f}"],
        ["利润总额", f"¥{report.total_profit:,.2f}"],
        [f"企业所得税（税率{report.income_tax_rate*100:.0f}%）", f"¥{report.income_tax_amount:,.2f}"],
        ["已预缴所得税", f"¥{report.income_tax_prepaid:,.2f}"],
        ["本期应补(退)所得税", f"¥{report.income_tax_due:,.2f}"],
        ["印花税", f"¥{report.stamp_tax:,.2f}"],
        ["本季度应缴税费合计", f"¥{report.tax_total:,.2f}"],
    ]

    table = Table(data, colWidths=[120 * mm, 50 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _chinese_font),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2EFDA")),
                ("FONTSIZE", (0, -1), (-1, -1), 11),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F2F2")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(table)

    # 发票明细
    if report.invoices:
        elements.append(Spacer(1, 10 * mm))
        elements.append(Paragraph("发票明细", title_style))
        elements.append(Spacer(1, 5 * mm))

        inv_data = [["日期", "发票号", "购买方", "金额", "税额", "类型"]]
        for inv in report.invoices:
            inv_data.append(
                [
                    str(inv.date),
                    inv.invoice_no,
                    inv.buyer[:10],
                    f"¥{inv.amount:,.2f}",
                    f"¥{inv.tax_amount:,.2f}",
                    "专票" if inv.invoice_type == "special" else "普票",
                ]
            )

        inv_table = Table(inv_data, colWidths=[25 * mm, 30 * mm, 35 * mm, 30 * mm, 25 * mm, 20 * mm])
        inv_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), _chinese_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (3, 0), (4, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        elements.append(inv_table)

    # 备注
    if report.notes:
        elements.append(Spacer(1, 8 * mm))
        elements.append(Paragraph(f"备注: {report.notes}", normal_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
