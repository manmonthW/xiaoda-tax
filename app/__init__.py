from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401
    from app.routes import main_bp, report_bp
    from app.voucher_routes import voucher_bp
    from app.ledger_routes import ledger_bp
    from app.closing_routes import closing_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(report_bp, url_prefix="/report")
    app.register_blueprint(voucher_bp, url_prefix="/voucher")
    app.register_blueprint(ledger_bp, url_prefix="/ledger")
    app.register_blueprint(closing_bp, url_prefix="/closing")

    # Vercel serverless: auto-create tables and seed accounts on cold start
    if os.environ.get("VERCEL", ""):
        with app.app_context():
            db.create_all()
            from app.models import Account
            if not Account.query.first():
                _seed_accounts()

    return app


def _seed_accounts():
    """初始化科目表（Vercel 冷启动时调用）"""
    from app.models import Account

    ACCOUNTS = [
        ("1001", "库存现金", "asset", "debit", None),
        ("1002", "银行存款", "asset", "debit", None),
        ("1122", "应收账款", "asset", "debit", None),
        ("1401", "固定资产", "asset", "debit", None),
        ("1602", "累计折旧", "asset", "credit", None),
        ("2202", "应付账款", "liability", "credit", None),
        ("2211", "应付职工薪酬", "liability", "credit", None),
        ("2221", "应交税费", "liability", "credit", None),
        ("2221.01", "应交税费-应交增值税", "liability", "credit", "2221"),
        ("2221.02", "应交税费-应交个人所得税", "liability", "credit", "2221"),
        ("2221.03", "应交税费-应交企业所得税", "liability", "credit", "2221"),
        ("3001", "实收资本", "equity", "credit", None),
        ("3101", "盈余公积", "equity", "credit", None),
        ("3131", "本年利润", "equity", "credit", None),
        ("3141", "利润分配-未分配利润", "equity", "credit", None),
        ("5001", "主营业务收入", "income", "credit", None),
        ("5401", "主营业务成本", "expense", "debit", None),
        ("5602", "管理费用", "expense", "debit", None),
        ("5602.01", "管理费用-工资", "expense", "debit", "5602"),
        ("5602.02", "管理费用-办公费", "expense", "debit", "5602"),
        ("5602.03", "管理费用-差旅费", "expense", "debit", "5602"),
        ("5602.04", "管理费用-折旧费", "expense", "debit", "5602"),
        ("5603", "财务费用", "expense", "debit", None),
        ("5711", "营业外支出", "expense", "debit", None),
    ]

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
    app.register_blueprint(closing_bp, url_prefix="/closing")

    return app
