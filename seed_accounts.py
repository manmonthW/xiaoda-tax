"""初始化会计科目表 - 小规模纳税人咨询公司最小科目集"""
from app import create_app, db
from app.models import Account

ACCOUNTS = [
    # (code, name, category, balance_dir, parent_code)
    # ── 资产类 ──
    ("1001",    "库存现金",                "asset",     "debit",  None),
    ("1002",    "银行存款",                "asset",     "debit",  None),
    ("1122",    "应收账款",                "asset",     "debit",  None),
    ("1401",    "固定资产",                "asset",     "debit",  None),
    ("1602",    "累计折旧",                "asset",     "credit", None),
    # ── 负债类 ──
    ("2202",    "应付账款",                "liability", "credit", None),
    ("2211",    "应付职工薪酬",            "liability", "credit", None),
    ("2221",    "应交税费",                "liability", "credit", None),
    ("2221.01", "应交税费-应交增值税",     "liability", "credit", "2221"),
    ("2221.02", "应交税费-应交个人所得税",  "liability", "credit", "2221"),
    ("2221.03", "应交税费-应交企业所得税",  "liability", "credit", "2221"),
    # ── 所有者权益类 ──
    ("3001",    "实收资本",                "equity",    "credit", None),
    ("3101",    "盈余公积",                "equity",    "credit", None),
    ("3131",    "本年利润",                "equity",    "credit", None),
    ("3141",    "利润分配-未分配利润",      "equity",    "credit", None),
    # ── 收入类 ──
    ("5001",    "主营业务收入",            "income",    "credit", None),
    # ── 费用类 ──
    ("5401",    "主营业务成本",            "expense",   "debit",  None),
    ("5602",    "管理费用",                "expense",   "debit",  None),
    ("5602.01", "管理费用-工资",           "expense",   "debit",  "5602"),
    ("5602.02", "管理费用-办公费",         "expense",   "debit",  "5602"),
    ("5602.03", "管理费用-差旅费",         "expense",   "debit",  "5602"),
    ("5602.04", "管理费用-折旧费",         "expense",   "debit",  "5602"),
    ("5603",    "财务费用",                "expense",   "debit",  None),
    ("5711",    "营业外支出",              "expense",   "debit",  None),
]


def seed():
    app = create_app()
    with app.app_context():
        if Account.query.first():
            print("科目表已存在，跳过初始化。如需重置请先清空 account 表。")
            return

        # 两轮插入：先插入一级科目，再插入二级科目（需要 parent_id）
        code_to_id = {}
        for code, name, cat, bdir, parent_code in ACCOUNTS:
            if parent_code is None:
                acct = Account(code=code, name=name, category=cat, balance_dir=bdir)
                db.session.add(acct)
                db.session.flush()
                code_to_id[code] = acct.id

        for code, name, cat, bdir, parent_code in ACCOUNTS:
            if parent_code is not None:
                acct = Account(code=code, name=name, category=cat, balance_dir=bdir,
                               parent_id=code_to_id[parent_code])
                db.session.add(acct)
                db.session.flush()
                code_to_id[code] = acct.id

        db.session.commit()
        print(f"已初始化 {len(ACCOUNTS)} 个会计科目。")


if __name__ == "__main__":
    seed()
