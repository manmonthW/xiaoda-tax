"""自动计算财报中的合计行"""


def calc_balance_sheet(bs):
    """计算资产负债表合计行"""
    def s(*keys):
        return round(sum(float(bs.get(k, 0) or 0) for k in keys), 2)

    # 流动资产合计 (行15) = 行1~14
    bs["a15"] = s("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9", "a14")
    bs["a15_y"] = s("a1_y", "a2_y", "a3_y", "a4_y", "a5_y", "a6_y", "a7_y", "a8_y", "a9_y", "a14_y")

    # 固定资产账面价值 (行20) = 行18 - 行19
    bs["a20"] = round(float(bs.get("a18", 0) or 0) - float(bs.get("a19", 0) or 0), 2)
    bs["a20_y"] = round(float(bs.get("a18_y", 0) or 0) - float(bs.get("a19_y", 0) or 0), 2)

    # 非流动资产合计 (行29) = 行16~28 (excluding subtotals, using 16,17,20,21,22,23,24,25,26,27,28)
    bs["a29"] = s("a16", "a17", "a20", "a21", "a22", "a23", "a24", "a25", "a26", "a27", "a28")
    bs["a29_y"] = s("a16_y", "a17_y", "a20_y", "a21_y", "a22_y", "a23_y", "a24_y", "a25_y", "a26_y", "a27_y", "a28_y")

    # 资产合计 (行30) = 行15 + 行29
    bs["a30"] = round(float(bs.get("a15", 0) or 0) + float(bs.get("a29", 0) or 0), 2)
    bs["a30_y"] = round(float(bs.get("a15_y", 0) or 0) + float(bs.get("a29_y", 0) or 0), 2)

    # 流动负债合计 (行41) = 行31~40
    bs["l41"] = s("l31", "l32", "l33", "l34", "l35", "l36", "l37", "l38", "l39", "l40")
    bs["l41_y"] = s("l31_y", "l32_y", "l33_y", "l34_y", "l35_y", "l36_y", "l37_y", "l38_y", "l39_y", "l40_y")

    # 非流动负债合计 (行46) = 行42~45
    bs["l46"] = s("l42", "l43", "l44", "l45")
    bs["l46_y"] = s("l42_y", "l43_y", "l44_y", "l45_y")

    # 负债合计 (行47) = 行41 + 行46
    bs["l47"] = round(float(bs.get("l41", 0) or 0) + float(bs.get("l46", 0) or 0), 2)
    bs["l47_y"] = round(float(bs.get("l41_y", 0) or 0) + float(bs.get("l46_y", 0) or 0), 2)

    # 所有者权益合计 (行52) = 行48~51
    bs["e52"] = s("e48", "e49", "e50", "e51")
    bs["e52_y"] = s("e48_y", "e49_y", "e50_y", "e51_y")

    # 负债和所有者权益总计 (行53) = 行47 + 行52
    bs["le53"] = round(float(bs.get("l47", 0) or 0) + float(bs.get("e52", 0) or 0), 2)
    bs["le53_y"] = round(float(bs.get("l47_y", 0) or 0) + float(bs.get("e52_y", 0) or 0), 2)

    return bs


def calc_income_stmt(ist):
    """计算利润表合计行"""
    def g(k):
        return float(ist.get(k, 0) or 0)

    # 营业利润 (行21) = 行1-2-3-11-14-18+20
    ist["r21"] = round(g("r1") - g("r2") - g("r3") - g("r11") - g("r14") - g("r18") + g("r20"), 2)
    ist["r21_acc"] = round(g("r1_acc") - g("r2_acc") - g("r3_acc") - g("r11_acc") - g("r14_acc") - g("r18_acc") + g("r20_acc"), 2)

    # 利润总额 (行30) = 行21+22-24
    ist["r30"] = round(g("r21") + g("r22") - g("r24"), 2)
    ist["r30_acc"] = round(g("r21_acc") + g("r22_acc") - g("r24_acc"), 2)

    # 净利润 (行32) = 行30-31
    ist["r32"] = round(g("r30") - g("r31"), 2)
    ist["r32_acc"] = round(g("r30_acc") - g("r31_acc"), 2)

    return ist


def calc_cashflow(cf):
    """计算现金流量表合计行"""
    def g(k):
        return float(cf.get(k, 0) or 0)

    # 经营活动净额 (行7) = 行1+2-3-4-5-6
    cf["c7"] = round(g("c1") + g("c2") - g("c3") - g("c4") - g("c5") - g("c6"), 2)
    cf["c7_acc"] = round(g("c1_acc") + g("c2_acc") - g("c3_acc") - g("c4_acc") - g("c5_acc") - g("c6_acc"), 2)

    # 投资活动净额 (行13) = 行8+9+10-11-12
    cf["c13"] = round(g("c8") + g("c9") + g("c10") - g("c11") - g("c12"), 2)
    cf["c13_acc"] = round(g("c8_acc") + g("c9_acc") + g("c10_acc") - g("c11_acc") - g("c12_acc"), 2)

    # 筹资活动净额 (行19) = 行14+15-16-17-18
    cf["c19"] = round(g("c14") + g("c15") - g("c16") - g("c17") - g("c18"), 2)
    cf["c19_acc"] = round(g("c14_acc") + g("c15_acc") - g("c16_acc") - g("c17_acc") - g("c18_acc"), 2)

    # 现金净增加额 (行20) = 行7+13+19
    cf["c20"] = round(g("c7") + g("c13") + g("c19"), 2)
    cf["c20_acc"] = round(g("c7_acc") + g("c13_acc") + g("c19_acc"), 2)

    # 期末现金余额 (行22) = 行20+21
    cf["c22"] = round(g("c20") + g("c21"), 2)
    cf["c22_acc"] = round(g("c20_acc") + g("c21_acc"), 2)

    return cf
