"""自然语言填表助手 - 规则引擎
解析用户描述的业务场景，生成三张报表的填写建议。
"""
import re


def parse_query(text):
    """从自然语言中提取关键数值"""
    info = {
        "income": 0,           # 含税收入
        "cost": 0,             # 成本
        "capital": 0,          # 注册资本/实收资本
        "cash_begin": 0,       # 期初现金（默认=注册资本）
        "salary": 0,           # 工资
        "rent": 0,             # 房租
        "tax_paid": 0,         # 已缴税费
        "vat_rate": 0.01,      # 征收率默认1%
        "income_tax_rate": 0.05,  # 所得税率默认5%
        "receivable": 0,       # 应收未收
        "payable": 0,          # 应付未付
        "fixed_asset": 0,      # 固定资产
        "depreciation": 0,     # 累计折旧
        "loan": 0,             # 借款
        "mgmt_expense": 0,     # 管理费用
        "sell_expense": 0,     # 销售费用
        "finance_expense": 0,  # 财务费用
        "cash_received": None, # 收到的现金（默认=收入）
        "cash_paid_material": 0,  # 购买材料支付
        "has_invoice": True,   # 是否开票
        "invoice_type": "normal",  # 发票类型
    }

    # 收入/合同/开票金额
    for pat in [
        r'(?:收入|营业收入|开票|开了.*发票|合同|签.*合同|合同金额|发票金额|营收)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?',
        r'([\d,.]+)\s*(?:万|w)?(?:元)?(?:的)?(?:收入|合同|发票|营收)',
    ]:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2] or 'w' in text[m.start():m.end()+2].lower():
                v *= 10000
            info["income"] = v
            break

    # 成本
    for pat in [r'(?:成本|营业成本|进货|采购)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?']:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["cost"] = v
            info["cash_paid_material"] = v

    # 注册资本
    for pat in [r'(?:注册资本|注册资金|实收资本|资本金)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?']:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["capital"] = v
            info["cash_begin"] = v

    # 工资
    for pat in [r'(?:工资|薪酬|人工|员工工资)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?']:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["salary"] = v

    # 房租
    for pat in [r'(?:房租|租金|办公室租金)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?']:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["rent"] = v

    # 管理费用
    for pat in [r'(?:管理费用|管理费)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?']:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["mgmt_expense"] = v

    # 固定资产
    for pat in [r'(?:固定资产|设备|电脑)[^\d]*?([\d,.]+)\s*(?:万|w)?(?:元)?']:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["fixed_asset"] = v

    # 征收率
    if '3%' in text or '3％' in text or '征收率3' in text:
        info["vat_rate"] = 0.03
    elif '5%' in text or '5％' in text:
        info["vat_rate"] = 0.05

    # 应收未收
    if '没收到' in text or '未收到' in text or '还没收' in text or '欠款' in text:
        info["cash_received"] = 0
        info["receivable"] = info["income"]
    elif '收到' in text or '已收' in text or '款已到' in text:
        info["cash_received"] = info["income"]

    return info


def generate_suggestion(info):
    """根据解析结果生成三张表的填写建议"""
    income = info["income"]
    cost = info["cost"]
    capital = info["capital"]
    vat_rate = info["vat_rate"]
    it_rate = info["income_tax_rate"]

    # 计算
    income_ex_tax = round(income / (1 + vat_rate), 2) if income else 0
    vat = round(income_ex_tax * vat_rate, 2)
    vat_exempt = income_ex_tax <= 300000

    # 管理费用 = 明确费用 + 工资 + 房租
    mgmt = info["mgmt_expense"] + info["salary"] + info["rent"]

    # 营业利润
    operating_profit = round(income_ex_tax - cost - mgmt - info["sell_expense"] - info["finance_expense"], 2)

    # 免征增值税转营业外收入
    extra_income = vat if vat_exempt else 0

    # 利润总额
    total_profit = round(operating_profit + extra_income, 2)

    # 所得税
    income_tax = round(max(total_profit, 0) * it_rate, 2) if total_profit > 0 else 0
    net_profit = round(total_profit - income_tax, 2)

    # 现金流
    cash_received = info["cash_received"] if info["cash_received"] is not None else income
    cash_begin = info["cash_begin"]
    cash_paid_salary = info["salary"]
    cash_paid_material = info["cash_paid_material"]
    cash_paid_tax = info["tax_paid"]
    # 支付其他经营活动现金 = 房租 + 管理费用（独立部分，不含已单独计的工资和房租）+ 销售费用 + 财务费用
    cash_paid_other = round(info["rent"] + info["mgmt_expense"] + info["sell_expense"] + info["finance_expense"], 2)

    cash_op_net = round(cash_received - cash_paid_material - cash_paid_salary - cash_paid_tax - cash_paid_other, 2)
    cash_end = round(cash_begin + cash_op_net, 2)

    # 资产负债表
    cash_balance = cash_end
    receivable = info["receivable"]
    tax_payable = income_tax  # 应交所得税
    if not vat_exempt:
        tax_payable += vat

    total_assets = round(cash_balance + receivable + info["fixed_asset"], 2)
    undistributed = net_profit
    total_equity = round(capital + undistributed, 2)
    total_liab = round(total_assets - total_equity, 2)

    # 构建建议
    result = {
        "summary": [],
        "balance_sheet": {},
        "income_stmt": {},
        "cashflow_stmt": {},
        "notes": [],
    }

    # 摘要
    result["summary"].append(f"含税收入：¥{income:,.2f}")
    result["summary"].append(f"不含税收入：¥{income_ex_tax:,.2f}（征收率 {vat_rate*100:.0f}%）")
    result["summary"].append(f"增值税：¥{vat:,.2f}" + ("  ← 季度≤30万，免征！" if vat_exempt else ""))
    if extra_income:
        result["summary"].append(f"免征增值税转营业外收入：¥{extra_income:,.2f}")
    result["summary"].append(f"利润总额：¥{total_profit:,.2f}")
    result["summary"].append(f"所得税（{it_rate*100:.0f}%）：¥{income_tax:,.2f}")
    result["summary"].append(f"净利润：¥{net_profit:,.2f}")

    # 资产负债表建议
    bs = result["balance_sheet"]
    bs["a1"] = {"label": "货币资金", "value": cash_balance, "row": 1}
    if receivable:
        bs["a4"] = {"label": "应收账款", "value": receivable, "row": 4}
    if info["fixed_asset"]:
        bs["a18"] = {"label": "固定资产原价", "value": info["fixed_asset"], "row": 18}
    bs["a1_y"] = {"label": "货币资金（年初）", "value": cash_begin, "row": 1}

    if tax_payable > 0:
        bs["l36"] = {"label": "应交税费", "value": round(tax_payable, 2), "row": 36}
    bs["e48"] = {"label": "实收资本", "value": capital, "row": 48}
    bs["e48_y"] = {"label": "实收资本（年初）", "value": capital, "row": 48}
    bs["e51"] = {"label": "未分配利润", "value": undistributed, "row": 51}

    # 利润表建议
    ist = result["income_stmt"]
    ist["r1"] = {"label": "营业收入", "value": income_ex_tax, "row": 1}
    if cost:
        ist["r2"] = {"label": "营业成本", "value": cost, "row": 2}
    if info["salary"]:
        ist["r14"] = {"label": "管理费用", "value": mgmt, "row": 14, "note": f"含工资{info['salary']:,.0f}" + (f"+房租{info['rent']:,.0f}" if info['rent'] else "")}
    elif mgmt:
        ist["r14"] = {"label": "管理费用", "value": mgmt, "row": 14}
    if info["sell_expense"]:
        ist["r11"] = {"label": "销售费用", "value": info["sell_expense"], "row": 11}
    if extra_income:
        ist["r22"] = {"label": "营业外收入", "value": extra_income, "row": 22, "note": "免征增值税转入"}
    if income_tax:
        ist["r31"] = {"label": "所得税费用", "value": income_tax, "row": 31}

    # 现金流量表建议
    cf = result["cashflow_stmt"]
    if cash_received:
        cf["c1"] = {"label": "销售收到的现金", "value": cash_received, "row": 1}
    if cash_paid_material:
        cf["c3"] = {"label": "购买原材料支付的现金", "value": cash_paid_material, "row": 3}
    if cash_paid_salary:
        cf["c4"] = {"label": "支付的职工薪酬", "value": cash_paid_salary, "row": 4}
    if cash_paid_tax:
        cf["c5"] = {"label": "支付的税费", "value": cash_paid_tax, "row": 5}
    if cash_paid_other:
        cf["c6"] = {"label": "支付其他经营活动现金", "value": cash_paid_other, "row": 6}
    cf["c21"] = {"label": "期初现金余额", "value": cash_begin, "row": 21}

    # 提示
    if vat_exempt:
        result["notes"].append("季度不含税收入≤30万，增值税免征。免征的增值税计入营业外收入。")
    if receivable:
        result["notes"].append("款项未收到，因此资产负债表中有应收账款，现金流量表中销售收到的现金为0。")
    if not cost and income:
        result["notes"].append("未提及成本，营业成本按0处理。如有实际成本请补充。")
    result["notes"].append("第一季度：本期金额 = 本年累计金额，利润表和现金流量表两列填一样的数。")

    return result
