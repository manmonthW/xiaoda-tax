"""AI 记账规则引擎（无需 API key）。
把一句自然语言业务描述解析为「借贷平衡的记账凭证草稿」。
设计原则：先求准确稳定 —— 命中明确场景才生成；拿不准就降低置信度并给出提示，
交由人工在草稿状态下确认/修改后才记账。
"""
import re
from datetime import date

from app.assistant import calc_monthly_tax

# ─── 科目代码常量（与 seed_accounts 一致）───
CASH = ("1001", "库存现金")
BANK = ("1002", "银行存款")
AR = ("1122", "应收账款")
FIXED_ASSET = ("1401", "固定资产")
AP = ("2202", "应付账款")
SALARY_PAYABLE = ("2211", "应付职工薪酬")
TAX_VAT = ("2221.01", "应交税费-应交增值税")
TAX_IIT = ("2221.02", "应交税费-应交个人所得税")
TAX_CIT = ("2221.03", "应交税费-应交企业所得税")
CAPITAL = ("3001", "实收资本")
REVENUE = ("5001", "主营业务收入")
COST = ("5401", "主营业务成本")
ADMIN = ("5602", "管理费用")
ADMIN_SALARY = ("5602.01", "管理费用-工资")
ADMIN_OFFICE = ("5602.02", "管理费用-办公费")
ADMIN_TRAVEL = ("5602.03", "管理费用-差旅费")
FINANCE_EXP = ("5603", "财务费用")


def _entry(account, summary, debit=0, credit=0):
    code, name = account
    return {
        "account_code": code,
        "account_name": name,
        "summary": summary,
        "debit": round(float(debit), 2),
        "credit": round(float(credit), 2),
    }


def _extract_amounts(text):
    """提取文本中所有金额（处理「万」单位与千分位逗号），按出现顺序返回 float 列表。"""
    amounts = []
    for m in re.finditer(r'([\d][\d,]*(?:\.\d+)?)\s*(万|w|W|元|块)?', text):
        raw = m.group(1).replace(',', '')
        if raw in ('', '.'):
            continue
        try:
            v = float(raw)
        except ValueError:
            continue
        unit = m.group(2) or ''
        if unit in ('万', 'w', 'W'):
            v *= 10000
        # 过滤明显是年份/月份的纯数字（如 2026、12 月里的 12 已由上下文排除）
        amounts.append((v, m.start()))
    return amounts


def _primary_amount(text, near_keywords=None):
    """取主要金额：若指定关键字，则优先取关键字附近的金额；否则取最大的非年份金额。"""
    cands = _extract_amounts(text)
    if not cands:
        return None
    # 去掉明显的年份（1900-2100 且后面紧跟「年」）
    filtered = []
    for v, pos in cands:
        seg = text[pos:pos + 8]
        if 1900 <= v <= 2100 and ('年' in seg):
            continue
        # 排除「N月」「第N个月」等月份数字
        if v <= 12 and re.match(r'\s*(月|个月)', text[pos + len(str(int(v))):pos + len(str(int(v))) + 3] if v == int(v) else ''):
            continue
        filtered.append((v, pos))
    if not filtered:
        filtered = cands
    if near_keywords:
        for kw in near_keywords:
            ki = text.find(kw)
            if ki >= 0:
                # 取离关键字最近的金额
                best = min(filtered, key=lambda c: abs(c[1] - ki))
                return best[0]
    # 默认取最大金额（通常是主交易额）
    return max(filtered, key=lambda c: c[0])[0]


def _detect_payment_account(text):
    """识别收/付款账户：现金 vs 银行存款（默认银行存款）。"""
    if re.search(r'现金|付现|收现|现钞', text):
        return CASH
    return BANK


def _parse_date(text, default_date):
    """从文本中解析日期；解析不到用 default_date。"""
    y = default_date.year
    m = None
    d = None
    ym = re.search(r'(\d{4})\s*年', text)
    if ym:
        y = int(ym.group(1))
    mm = re.search(r'(\d{1,2})\s*月', text)
    if mm:
        m = int(mm.group(1))
    dd = re.search(r'(\d{1,2})\s*[日号]', text)
    if dd:
        d = int(dd.group(1))
    if m is None:
        return default_date, None
    try:
        return date(y, m, d or 28), m
    except ValueError:
        return date(y, m, 28), m


# ─── 各业务场景处理器 ───
# 每个处理器返回 voucher dict 列表；不命中返回 []

def _h_salary(text, amount, pay_acct, on_date, month):
    """工资：计提 + 发放 (+ 缴个税)，复用累计预扣个税算法。"""
    if not re.search(r'工资|薪酬|薪资|月薪|发了.*给.*员工|计提.*工资|发.*工资', text):
        return []
    if amount is None:
        return []
    # 工作月数（用于累计预扣）
    month_idx = 1
    mi = re.search(r'第\s*(\d+)\s*个月', text)
    if mi:
        month_idx = int(mi.group(1))
    elif month:
        month_idx = month  # 用月份近似累计月数

    # 模拟前几个月累计
    cum_income = 0
    cum_tax = 0
    for mm in range(1, month_idx):
        t, _, _ = calc_monthly_tax(amount, mm, cum_income, cum_tax)
        cum_income += amount
        cum_tax += t
    tax, _, _ = calc_monthly_tax(amount, month_idx, cum_income, cum_tax)
    net = round(amount - tax, 2)
    mtag = f"{month}月" if month else "本月"

    vouchers = []
    accrue = [_entry(ADMIN_SALARY, f"计提{mtag}工资", debit=amount),
              _entry(SALARY_PAYABLE, f"应付{mtag}工资", credit=net)]
    if tax > 0:
        accrue.append(_entry(TAX_IIT, "代扣个税", credit=tax))
    vouchers.append({
        "scenario": "计提工资",
        "summary": f"计提{mtag}工资",
        "date": on_date,
        "entries": accrue,
        "confidence": 0.85,
        "warnings": [] if tax == 0 else [f"已按累计预扣法代扣个税 ¥{tax:,.2f}（按第{month_idx}个月估算，请核对累计数）"],
    })
    vouchers.append({
        "scenario": "发放工资",
        "summary": f"发放{mtag}工资",
        "date": on_date,
        "entries": [_entry(SALARY_PAYABLE, f"发放{mtag}工资", debit=net),
                    _entry(pay_acct, f"发放{mtag}工资", credit=net)],
        "confidence": 0.85,
        "warnings": [],
    })
    if tax > 0:
        vouchers.append({
            "scenario": "缴纳个税",
            "summary": f"缴纳{mtag}代扣个人所得税",
            "date": on_date,
            "entries": [_entry(TAX_IIT, f"缴纳{mtag}个税", debit=tax),
                        _entry(pay_acct, f"缴纳{mtag}个税", credit=tax)],
            "confidence": 0.8,
            "warnings": ["个税通常次月申报缴纳，请按实际缴纳日期调整凭证日期"],
        })
    return vouchers


def _h_income(text, amount, pay_acct, on_date, month):
    """收入：开票/收到服务费咨询费货款。"""
    if not re.search(r'收入|开票|开.*发票|服务费|咨询费|顾问费|货款|营业额|营收', text):
        return []
    if amount is None:
        return []
    received = bool(re.search(r'收到|已收|到账|入账|打款|转账过来', text)) and \
        not re.search(r'未收|没收|还没收|欠|挂账', text)
    debit_acct = pay_acct if received else AR
    warn = []
    if not received:
        warn.append("未收到款项，已记应收账款；实际收款时再做收款凭证")
    warn.append("小规模纳税人：季度不含税收入≤30万免征增值税；如需价税分离请人工调整")
    return [{
        "scenario": "确认收入",
        "summary": "确认主营业务收入",
        "date": on_date,
        "entries": [_entry(debit_acct, "确认收入", debit=amount),
                    _entry(REVENUE, "确认收入", credit=amount)],
        "confidence": 0.75,
        "warnings": warn,
    }]


def _h_capital(text, amount, pay_acct, on_date, month):
    """收到投资款 / 注册资本到位。"""
    if not re.search(r'注册资本|实收资本|投资款|股东投资|出资|注资|增资', text):
        return []
    if amount is None:
        return []
    return [{
        "scenario": "实收资本",
        "summary": "收到投资款（实收资本）",
        "date": on_date,
        "entries": [_entry(pay_acct, "收到投资款", debit=amount),
                    _entry(CAPITAL, "实收资本", credit=amount)],
        "confidence": 0.85,
        "warnings": [],
    }]


def _h_pay_tax(text, amount, pay_acct, on_date, month):
    """缴纳税费。"""
    if not re.search(r'缴纳?税|交税|缴.*增值税|缴.*所得税|缴.*个税|完税|交.*税费', text):
        return []
    if amount is None:
        return []
    if re.search(r'个税|个人所得税', text):
        tax_acct = TAX_IIT
    elif re.search(r'企业所得税', text):
        tax_acct = TAX_CIT
    elif re.search(r'增值税', text):
        tax_acct = TAX_VAT
    else:
        tax_acct = ("2221", "应交税费")
    return [{
        "scenario": "缴纳税费",
        "summary": f"缴纳{tax_acct[1].replace('应交税费-应交', '')}",
        "date": on_date,
        "entries": [_entry(tax_acct, "缴纳税费", debit=amount),
                    _entry(pay_acct, "缴纳税费", credit=amount)],
        "confidence": 0.8,
        "warnings": [],
    }]


def _h_fixed_asset(text, amount, pay_acct, on_date, month):
    """购买固定资产。"""
    if not re.search(r'固定资产|购买设备|买.*设备|购入.*设备|采购.*设备', text):
        return []
    if amount is None:
        return []
    return [{
        "scenario": "购买固定资产",
        "summary": "购买固定资产",
        "date": on_date,
        "entries": [_entry(FIXED_ASSET, "购买固定资产", debit=amount),
                    _entry(pay_acct, "购买固定资产", credit=amount)],
        "confidence": 0.75,
        "warnings": ["金额≥单位标准方可计入固定资产并分期折旧；小额可直接计入费用"],
    }]


def _h_cost(text, amount, pay_acct, on_date, month):
    """采购/营业成本。"""
    if not re.search(r'采购|进货|原材料|营业成本|主营业务成本|进了一批货', text):
        return []
    if amount is None:
        return []
    credited = AP if re.search(r'未付|没付|赊|挂账|欠', text) else pay_acct
    warn = []
    if credited is AP:
        warn.append("款项未付，已记应付账款；实际付款时再做付款凭证")
    return [{
        "scenario": "采购成本",
        "summary": "结转营业成本/采购",
        "date": on_date,
        "entries": [_entry(COST, "采购/成本", debit=amount),
                    _entry(credited, "采购/成本", credit=amount)],
        "confidence": 0.7,
        "warnings": warn,
    }]


def _h_expense(text, amount, pay_acct, on_date, month):
    """费用支出：房租 / 办公费 / 差旅 / 报销 / 一般管理费用。"""
    if amount is None:
        return []
    if re.search(r'房租|租金|办公室租', text):
        exp_acct = ADMIN
        label = "房租"
    elif re.search(r'办公费|办公用品|打印|耗材|文具', text):
        exp_acct = ADMIN_OFFICE
        label = "办公费"
    elif re.search(r'差旅|出差|车票|机票|高铁|住宿|路费', text):
        exp_acct = ADMIN_TRAVEL
        label = "差旅费"
    elif re.search(r'利息|手续费|银行费用|财务费用', text):
        exp_acct = FINANCE_EXP
        label = "财务费用"
    elif re.search(r'报销|支付|付了|花了|缴.*费(?!税)|费用', text):
        exp_acct = ADMIN
        label = "管理费用"
    else:
        return []
    return [{
        "scenario": f"{label}支出",
        "summary": f"支付{label}",
        "date": on_date,
        "entries": [_entry(exp_acct, f"支付{label}", debit=amount),
                    _entry(pay_acct, f"支付{label}", credit=amount)],
        "confidence": 0.7,
        "warnings": [],
    }]


# 处理器优先级顺序（越靠前越优先匹配）
_HANDLERS = [
    _h_salary,
    _h_capital,
    _h_pay_tax,
    _h_fixed_asset,
    _h_income,
    _h_cost,
    _h_expense,
]


def parse_bookkeeping(text, default_date=None):
    """主入口：解析一句业务描述 → 凭证草稿提案。
    返回 {ok, vouchers:[...], message}。每张 voucher 已校验借贷平衡。"""
    text = (text or "").strip()
    default_date = default_date or date.today()
    if not text:
        return {"ok": False, "vouchers": [], "message": "请输入业务描述"}

    on_date, month = _parse_date(text, default_date)
    pay_acct = _detect_payment_account(text)
    amount = _primary_amount(text)

    vouchers = []
    for handler in _HANDLERS:
        result = handler(text, amount, pay_acct, on_date, month)
        if result:
            vouchers = result
            break

    if not vouchers:
        return {
            "ok": False,
            "vouchers": [],
            "message": "未能识别业务类型。请尝试更明确的描述，例如："
                       "「6月发放员工工资9000元」「收到咨询费5万元已到账」"
                       "「支付办公室房租3000元」「缴纳增值税1200元」",
        }

    # 校验每张凭证借贷平衡，计算合计
    for v in vouchers:
        td = round(sum(e["debit"] for e in v["entries"]), 2)
        tc = round(sum(e["credit"] for e in v["entries"]), 2)
        v["total_debit"] = td
        v["total_credit"] = tc
        v["balanced"] = abs(td - tc) < 0.005
        if not v["balanced"]:
            v["warnings"] = v.get("warnings", []) + [
                f"借贷不平衡（借{td:,.2f}/贷{tc:,.2f}），请人工调整后再记账"]
            v["confidence"] = min(v.get("confidence", 0.5), 0.3)

    return {"ok": True, "vouchers": vouchers, "message": ""}
