"""小规模纳税人税额计算逻辑"""


def calculate_taxes(report):
    """根据录入数据自动计算各项税额"""

    # 1. 增值税
    # 应税收入 = 含税收入总额 - 免税收入
    taxable_income_with_tax = report.income_total - report.income_tax_free
    # 不含税收入 = 含税收入 / (1 + 征收率)
    report.income_taxable = round(taxable_income_with_tax / (1 + report.vat_rate), 2)
    # 应纳增值税 = 不含税收入 × 征收率
    report.vat_amount = round(report.income_taxable * report.vat_rate, 2)

    # 小规模季度≤30万免征增值税
    report.vat_exempt = report.income_taxable <= 300000

    actual_vat = 0 if report.vat_exempt else report.vat_amount

    # 2. 附加税（以实缴增值税为基数）
    # 城市维护建设税：7%（市区）/ 5%（县城）/ 1%（其他）
    report.urban_maintenance_tax = round(actual_vat * 0.07, 2)
    # 教育费附加：3%
    report.education_surcharge = round(actual_vat * 0.03, 2)
    # 地方教育附加：2%
    report.local_education_surcharge = round(actual_vat * 0.02, 2)

    # 附加税减半征收（小规模纳税人优惠）
    report.urban_maintenance_tax = round(report.urban_maintenance_tax * 0.5, 2)
    report.education_surcharge = round(report.education_surcharge * 0.5, 2)
    report.local_education_surcharge = round(report.local_education_surcharge * 0.5, 2)

    # 月销售额≤10万（季度≤30万）免征教育费附加和地方教育附加
    if report.income_taxable <= 300000:
        report.education_surcharge = 0
        report.local_education_surcharge = 0

    # 3. 企业所得税（季度预缴）
    report.taxable_income = report.total_profit  # 简化：利润≈应纳税所得额
    report.income_tax_amount = round(report.taxable_income * report.income_tax_rate, 2)
    report.income_tax_due = round(
        report.income_tax_amount - report.income_tax_prepaid, 2
    )
