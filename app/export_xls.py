"""导出为原始.xls模板格式 - 清爽配色"""
import os
import io
import xlrd
import xlwt
from xlutils.copy import copy as xlcopy

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates_ref", "CWBB_XQYKJZZ")
QUARTERLY_TPL = os.path.join(TEMPLATE_DIR, "财务报表报送与信息采集（小企业会计准则）月季报.xls")
ANNUAL_TPL = os.path.join(TEMPLATE_DIR, "财务报表报送与信息采集（小企业会计准则）年报.xls")

# ---------------------------------------------------------------------------
# 自定义调色板（覆盖索引 56-59，避免冲突）
# ---------------------------------------------------------------------------
xlwt.add_palette_colour("hdr_dark", 56)
xlwt.add_palette_colour("info_bg", 57)
xlwt.add_palette_colour("sec_bg", 58)
xlwt.add_palette_colour("tot_bg", 59)

_B = 'borders: left thin, right thin, top thin, bottom thin;'

# --- 标题 / 副标题 ---
S_TITLE = xlwt.easyxf(
    'font: name 宋体, bold on, height 280, colour hdr_dark;'
    'align: horiz centre, vert centre;')
S_SUB = xlwt.easyxf(
    'font: name 宋体, height 180, colour gray50;'
    'align: horiz right, vert centre;')

# --- 信息栏 ---
S_INFO_L = xlwt.easyxf(
    'font: name 宋体, bold on, height 200;'
    'align: horiz centre, vert centre;'
    'pattern: pattern solid, fore_colour info_bg;' + _B)
S_INFO_V = xlwt.easyxf(
    'font: name 宋体, height 200;'
    'align: horiz centre, vert centre;' + _B)

# --- 表头 ---
S_HDR = xlwt.easyxf(
    'font: name 宋体, bold on, height 200, colour white;'
    'align: horiz centre, vert centre, wrap on;'
    'pattern: pattern solid, fore_colour hdr_dark;' + _B)

# --- 分类行 ---
S_SEC = xlwt.easyxf(
    'font: name 宋体, bold on, height 200, colour hdr_dark;'
    'align: horiz left, vert centre;'
    'pattern: pattern solid, fore_colour sec_bg;' + _B)

# --- 普通标签 / 缩进标签 ---
S_LBL = xlwt.easyxf(
    'font: name 宋体, height 200;'
    'align: horiz left, vert centre;' + _B)
S_LBL_IN = xlwt.easyxf(
    'font: name 宋体, height 200, colour gray50;'
    'align: horiz left, vert centre;' + _B)

# --- 数值 ---
S_NUM = xlwt.easyxf(
    'font: name 宋体, height 200;'
    'align: horiz right, vert centre;' + _B,
    num_format_str='#,##0.00')

# --- 行次 ---
S_RN = xlwt.easyxf(
    'font: name 宋体, height 200, colour gray50;'
    'align: horiz centre, vert centre;' + _B)

# --- 合计 / 重要行 ---
S_TOT_L = xlwt.easyxf(
    'font: name 宋体, bold on, height 200;'
    'align: horiz left, vert centre;'
    'pattern: pattern solid, fore_colour tot_bg;' + _B)
S_TOT_N = xlwt.easyxf(
    'font: name 宋体, bold on, height 200;'
    'align: horiz right, vert centre;'
    'pattern: pattern solid, fore_colour tot_bg;' + _B,
    num_format_str='#,##0.00')
S_TOT_RN = xlwt.easyxf(
    'font: name 宋体, bold on, height 200, colour gray50;'
    'align: horiz centre, vert centre;'
    'pattern: pattern solid, fore_colour tot_bg;' + _B)

# --- 粗体行（一、二、三、四）---
S_BOLD_L = xlwt.easyxf(
    'font: name 宋体, bold on, height 200;'
    'align: horiz left, vert centre;' + _B)
S_BOLD_N = xlwt.easyxf(
    'font: name 宋体, bold on, height 200;'
    'align: horiz right, vert centre;' + _B,
    num_format_str='#,##0.00')
S_BOLD_RN = xlwt.easyxf(
    'font: name 宋体, bold on, height 200, colour gray50;'
    'align: horiz centre, vert centre;' + _B)

# --- 空白边距 ---
S_EMPTY = xlwt.easyxf('')


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _classify(text):
    """根据标签文本判断行类型：section / total / bold / indent / normal"""
    if not isinstance(text, str) or not text.strip():
        return 'normal'
    t = text.strip()
    if t.endswith('：') or t.endswith(':'):
        return 'section'
    if '合计' in t or '总计' in t:
        return 'total'
    if t.startswith(('一、', '二、', '三、', '四、', '五、')):
        return 'bold'
    if text.startswith((' ', '\t', '　')) or text.lstrip().startswith('其中'):
        return 'indent'
    return 'normal'


def _merged_skip(merged_cells):
    """返回合并区域中非左上角的单元格集合"""
    skip = set()
    for rlo, rhi, clo, chi in merged_cells:
        for r in range(rlo, rhi):
            for c in range(clo, chi):
                if (r, c) != (rlo, clo):
                    skip.add((r, c))
    return skip


def _pick_style(r, c, val, rs, layout):
    """为单个单元格选择样式"""
    if r == 0:
        return S_TITLE
    if r == 1:
        return S_SUB
    if r in (2, 3):
        if isinstance(val, str) and ('纳税' in val or '所属' in val):
            return S_INFO_L
        return S_INFO_V
    if r == 4:
        return S_HDR

    margin_cols = layout['margin']
    if c in margin_cols:
        return S_EMPTY

    # 确定该单元格所属侧的标签列
    if layout['type'] == 'bs':
        label_col = 1 if c <= 4 else 5
    else:
        label_col = 1
    label_text = str(rs.cell_value(r, label_col))
    cat = _classify(label_text)

    num_cols = layout['num']
    rn_cols = layout['rn']

    if cat == 'section':
        return S_SEC
    if cat == 'total':
        if c in num_cols:
            return S_TOT_N
        if c in rn_cols:
            return S_TOT_RN
        return S_TOT_L
    if cat == 'bold':
        if c in num_cols:
            return S_BOLD_N
        if c in rn_cols:
            return S_BOLD_RN
        return S_BOLD_L
    if cat == 'indent':
        if c in num_cols:
            return S_NUM
        if c in rn_cols:
            return S_RN
        return S_LBL_IN
    # normal
    if c in num_cols:
        return S_NUM
    if c in rn_cols:
        return S_RN
    return S_LBL


def _restyle(rb, idx, ws, layout):
    """重写整张工作表的样式"""
    rs = rb.sheet_by_index(idx)
    skip = _merged_skip(rs.merged_cells)
    for r in range(rs.nrows):
        for c in range(rs.ncols):
            if (r, c) in skip:
                continue
            val = rs.cell_value(r, c)
            sty = _pick_style(r, c, val, rs, layout)
            ws.write(r, c, val, sty)


def _num_style(rs, row, label_col):
    """根据行标签返回数值样式"""
    cat = _classify(str(rs.cell_value(row, label_col)))
    if cat == 'total':
        return S_TOT_N
    if cat == 'bold':
        return S_BOLD_N
    return S_NUM


# ---------------------------------------------------------------------------
# Sheet 布局定义
# ---------------------------------------------------------------------------
_BS = {'type': 'bs', 'margin': {0, 9}, 'num': {3, 4, 7, 8}, 'rn': {2, 6}}
_IS = {'type': 'is', 'margin': {0}, 'num': {3, 4}, 'rn': {2}}
_CF = {'type': 'cf', 'margin': {0, 6}, 'num': {3, 4}, 'rn': {2}}


def export_xls(report):
    """将报表数据填入模板，返回BytesIO"""
    tpl_path = QUARTERLY_TPL if report.report_type == "quarterly" else ANNUAL_TPL
    rb = xlrd.open_workbook(tpl_path, formatting_info=True)
    wb = xlcopy(rb)

    # 设置自定义调色板 RGB
    wb.set_colour_RGB(56, 44, 62, 80)      # hdr_dark  深蓝灰
    wb.set_colour_RGB(57, 214, 234, 248)    # info_bg   浅蓝
    wb.set_colour_RGB(58, 218, 227, 243)    # sec_bg    淡蓝
    wb.set_colour_RGB(59, 226, 239, 218)    # tot_bg    淡绿

    bs = report.get_bs()
    ist = report.get_is()
    cf = report.get_cf()

    # ===== Sheet 0: 资产负债表 =====
    ws0 = wb.get_sheet(0)
    _restyle(rb, 0, ws0, _BS)

    ws0.write(2, 3, report.taxpayer_id, S_INFO_V)
    ws0.write(2, 7, report.taxpayer_name, S_INFO_V)
    ws0.write(3, 3, report.period_start, S_INFO_V)
    ws0.write(3, 7, report.period_end, S_INFO_V)

    rs0 = rb.sheet_by_index(0)
    asset_rows = {
        6: "a1", 7: "a2", 8: "a3", 9: "a4", 10: "a5",
        11: "a6", 12: "a7", 13: "a8", 14: "a9",
        15: "a10", 16: "a11", 17: "a12", 18: "a13",
        19: "a14", 20: "a15",
        22: "a16", 23: "a17", 24: "a18", 25: "a19", 26: "a20",
        27: "a21", 28: "a22", 29: "a23", 30: "a24",
        31: "a25", 32: "a26", 33: "a27", 34: "a28",
        35: "a29", 36: "a30",
    }
    for row, key in asset_rows.items():
        s = _num_style(rs0, row, 1)
        ws0.write(row, 3, float(bs.get(key, 0) or 0), s)
        ws0.write(row, 4, float(bs.get(f"{key}_y", 0) or 0), s)

    liability_rows = {
        6: "l31", 7: "l32", 8: "l33", 9: "l34", 10: "l35",
        11: "l36", 12: "l37", 13: "l38", 14: "l39", 15: "l40",
        16: "l41",
        18: "l42", 19: "l43", 20: "l44", 21: "l45", 22: "l46",
        23: "l47",
    }
    for row, key in liability_rows.items():
        s = _num_style(rs0, row, 5)
        ws0.write(row, 7, float(bs.get(key, 0) or 0), s)
        ws0.write(row, 8, float(bs.get(f"{key}_y", 0) or 0), s)

    equity_rows = {
        31: "e48", 32: "e49", 33: "e50", 34: "e51", 35: "e52",
    }
    for row, key in equity_rows.items():
        s = _num_style(rs0, row, 5)
        ws0.write(row, 7, float(bs.get(key, 0) or 0), s)
        ws0.write(row, 8, float(bs.get(f"{key}_y", 0) or 0), s)

    ws0.write(36, 7, float(bs.get("le53", 0) or 0), S_TOT_N)
    ws0.write(36, 8, float(bs.get("le53_y", 0) or 0), S_TOT_N)

    # ===== Sheet 1: 利润表 =====
    ws1 = wb.get_sheet(1)
    _restyle(rb, 1, ws1, _IS)

    ws1.write(2, 3, report.taxpayer_id, S_INFO_V)
    ws1.write(2, 5, report.taxpayer_name, S_INFO_V)
    ws1.write(3, 3, report.period_start, S_INFO_V)
    ws1.write(3, 5, report.period_end, S_INFO_V)

    rs1 = rb.sheet_by_index(1)
    income_rows = {
        5: "r1", 6: "r2", 7: "r3", 8: "r4", 9: "r5",
        10: "r6", 11: "r7", 12: "r8", 13: "r9", 14: "r10",
        15: "r11", 16: "r12", 17: "r13",
        18: "r14", 19: "r15", 20: "r16", 21: "r17",
        22: "r18", 23: "r19",
        24: "r20", 25: "r21",
        26: "r22", 27: "r23",
        28: "r24", 29: "r25", 30: "r26", 31: "r27", 32: "r28", 33: "r29",
        34: "r30", 35: "r31", 36: "r32",
    }
    for row, key in income_rows.items():
        s = _num_style(rs1, row, 1)
        ws1.write(row, 3, float(ist.get(key, 0) or 0), s)
        ws1.write(row, 4, float(ist.get(f"{key}_acc", 0) or 0), s)

    # ===== Sheet 2: 现金流量表 =====
    ws2 = wb.get_sheet(2)
    _restyle(rb, 2, ws2, _CF)

    ws2.write(2, 3, report.taxpayer_id, S_INFO_V)
    ws2.write(2, 5, report.taxpayer_name, S_INFO_V)
    ws2.write(3, 3, report.period_start, S_INFO_V)
    ws2.write(3, 5, report.period_end, S_INFO_V)

    rs2 = rb.sheet_by_index(2)
    cf_rows = {
        6: "c1", 7: "c2", 8: "c3", 9: "c4", 10: "c5", 11: "c6", 12: "c7",
        14: "c8", 15: "c9", 16: "c10", 17: "c11", 18: "c12", 19: "c13",
        21: "c14", 22: "c15", 23: "c16", 24: "c17", 25: "c18", 26: "c19",
        27: "c20", 28: "c21", 29: "c22",
    }
    for row, key in cf_rows.items():
        s = _num_style(rs2, row, 1)
        ws2.write(row, 3, float(cf.get(key, 0) or 0), s)
        ws2.write(row, 4, float(cf.get(f"{key}_acc", 0) or 0), s)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
