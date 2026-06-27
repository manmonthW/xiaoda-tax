"""自然语言填表助手 - 规则引擎
解析用户描述的业务场景，生成三张报表的填写建议。
支持工资记账场景：自动生成计提/发放/缴税凭证建议。
"""
import re


# ─── 个税累进税率表 ─────────────────────────────────
TAX_BRACKETS = [
    (36000,  0.03, 0),
    (144000, 0.10, 2520),
    (300000, 0.20, 16920),
    (420000, 0.25, 31920),
    (660000, 0.30, 52920),
    (960000, 0.35, 85920),
    (float('inf'), 0.45, 181920),
]


def calc_monthly_tax(monthly_salary, month_index, cumulative_income=0, cumulative_tax=0):
    """计算累计预扣法下当月应扣个税
    monthly_salary: 当月税前工资
    month_index: 第几个月（从1开始）
    cumulative_income: 之前累计收入
    cumulative_tax: 之前累计已扣税
    """
    cum_income = cumulative_income + monthly_salary
    cum_deduction = 5000 * month_index
    taxable = max(cum_income - cum_deduction, 0)
    cum_tax = 0
    for threshold, rate, quick_deduction in TAX_BRACKETS:
        if taxable <= threshold:
            cum_tax = round(taxable * rate - quick_deduction, 2)
            break
    current_tax = max(round(cum_tax - cumulative_tax, 2), 0)
    return current_tax, taxable, rate


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
        # ── 工资记账场景 ──
        "is_salary_scenario": False,  # 是否为纯工资记账问题
        "salary_month": 0,           # 工资所属月份
        "salary_year": 0,            # 工资所属年份
        "employee_name": "",         # 员工姓名
        "salary_months_worked": 1,   # 已工作月数（用于累计预扣）
        "is_retired_rehire": False,   # 是否退休返聘
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

    # 工资（优先匹配"数字+工资"模式，避免误匹配远处的数字）
    for pat in [
        r'([\d,.]+)\s*(?:万|w)?(?:元)?\s*(?:的)?(?:工资|薪酬|月薪|薪资)',
        r'(?:发[了放]|开了?|支付)\s*(?:了)?\s*([\d,.]+)\s*(?:万|w)?(?:元)?(?:的)?(?:工资|薪酬)',
        r'(?:工资|薪酬|人工|员工工资|月薪|薪资)\s{0,3}([\d,.]+)\s*(?:万|w)?(?:元)?',
    ]:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if '万' in text[m.start():m.end()+2]:
                v *= 10000
            info["salary"] = v
            break

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

    # ── 工资记账场景检测 ──
    salary_keywords = ['发工资', '发放工资', '开工资', '工资记账', '怎么记账',
                       '如何记账', '工资入账', '计提工资', '雇员', '员工',
                       '退休返聘', '返聘', '月薪', '薪资', '发了', '发放']
    if info["salary"] > 0 and (
        any(kw in text for kw in salary_keywords)
        or (info["income"] == 0)  # 只提工资没提收入，默认是工资场景
    ):
        info["is_salary_scenario"] = True

    # 退休返聘
    if '退休' in text or '返聘' in text or '离退休' in text:
        info["is_retired_rehire"] = True
        info["is_salary_scenario"] = True

    # 月份检测
    m = re.search(r'(\d{1,2})\s*月', text)
    if m:
        info["salary_month"] = int(m.group(1))
    m = re.search(r'(\d{4})\s*年', text)
    if m:
        info["salary_year"] = int(m.group(1))

    # 工作月数
    m = re.search(r'第\s*(\d+)\s*个月', text)
    if m:
        info["salary_months_worked"] = int(m.group(1))
    elif re.search(r'入职|第一个月|首月|刚入职', text):
        info["salary_months_worked"] = 1

    return info


def _generate_salary_vouchers(info):
    """生成工资记账的凭证建议"""
    salary = info["salary"]
    month_idx = info["salary_months_worked"]

    # 模拟前几个月的累计（假设每月同薪）
    cumulative_income = 0
    cumulative_tax = 0
    for m in range(1, month_idx):
        t, _, _ = calc_monthly_tax(salary, m, cumulative_income, cumulative_tax)
        cumulative_income += salary
        cumulative_tax += t

    # 计算当月个税
    tax, taxable, rate = calc_monthly_tax(salary, month_idx, cumulative_income, cumulative_tax)
    net_pay = round(salary - tax, 2)

    vouchers = []

    # 凭证1：计提工资
    v1_items = [
        {"account_code": "5602.01", "account_name": "管理费用-工资",
         "summary": f"计提{info['salary_month'] or 'X'}月顾问工资",
         "debit": salary, "credit": 0},
        {"account_code": "2211", "account_name": "应付职工薪酬",
         "summary": f"应付工资",
         "debit": 0, "credit": net_pay},
    ]
    if tax > 0:
        v1_items.append({
            "account_code": "2221.02", "account_name": "应交税费-应交个人所得税",
            "summary": "代扣个税",
            "debit": 0, "credit": tax,
        })
    vouchers.append({
        "title": "计提工资",
        "notes": f"计提{info['salary_month'] or 'X'}月工资",
        "entries": v1_items,
    })

    # 凭证2：发放工资
    vouchers.append({
        "title": "发放工资",
        "notes": f"发放{info['salary_month'] or 'X'}月工资",
        "entries": [
            {"account_code": "2211", "account_name": "应付职工薪酬",
             "summary": f"发放{info['salary_month'] or 'X'}月工资",
             "debit": net_pay, "credit": 0},
            {"account_code": "1002", "account_name": "银行存款",
             "summary": f"发放{info['salary_month'] or 'X'}月工资",
             "debit": 0, "credit": net_pay},
        ],
    })

    # 凭证3：缴纳个税
    if tax > 0:
        vouchers.append({
            "title": "缴纳个税",
            "notes": f"缴纳{info['salary_month'] or 'X'}月代扣个人所得税",
            "entries": [
                {"account_code": "2221.02", "account_name": "应交税费-应交个人所得税",
                 "summary": f"缴纳{info['salary_month'] or 'X'}月个税",
                 "debit": tax, "credit": 0},
                {"account_code": "1002", "account_name": "银行存款",
                 "summary": f"缴纳{info['salary_month'] or 'X'}月个税",
                 "debit": 0, "credit": tax},
            ],
        })

    return {
        "salary": salary,
        "tax": tax,
        "tax_rate": rate,
        "taxable_income": taxable,
        "net_pay": net_pay,
        "vouchers": vouchers,
        "month_index": month_idx,
        "is_retired_rehire": info["is_retired_rehire"],
    }


def generate_suggestion(info):
    """根据解析结果生成三张表的填写建议"""
    # 如果是工资记账场景，生成凭证建议
    salary_detail = None
    if info["is_salary_scenario"] and info["salary"] > 0:
        salary_detail = _generate_salary_vouchers(info)

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
    if income:
        result["notes"].append("第一季度：本期金额 = 本年累计金额，利润表和现金流量表两列填一样的数。")

    # ── 工资记账场景：追加凭证建议和工资明细 ──
    if salary_detail:
        sd = salary_detail
        result["salary_detail"] = sd
        result["vouchers"] = sd["vouchers"]

        # 追加工资专项摘要
        result["summary"].insert(0, "── 工资记账分析 ──")
        result["summary"].insert(1, f"税前工资：¥{sd['salary']:,.2f}")
        result["summary"].insert(2, f"累计应纳税所得额：¥{sd['taxable_income']:,.2f}（适用税率 {sd['tax_rate']*100:.0f}%）")
        result["summary"].insert(3, f"当月应扣个税：¥{sd['tax']:,.2f}")
        result["summary"].insert(4, f"实发工资：¥{sd['net_pay']:,.2f}")
        if sd["is_retired_rehire"]:
            result["summary"].insert(5, "⚠ 退休返聘人员，按劳务报酬或工资薪金申报（建议咨询税务局确认）")

        # 追加工资相关提示
        result["notes"].append(
            f"工资记账需要做{len(sd['vouchers'])}张凭证：计提工资、发放工资" +
            ("、缴纳个税。" if sd["tax"] > 0 else "。（本月无需代扣个税）")
        )
        result["notes"].append("个税采用累计预扣法，每月可扣减5,000元费用。年度累计应纳税所得额≤36,000适用3%税率。")
        if sd["is_retired_rehire"]:
            result["notes"].append("退休返聘人员不缴社保，但个税照常代扣代缴。用工关系按劳务合同或返聘协议处理。")

    return result
