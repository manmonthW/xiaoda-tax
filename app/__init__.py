from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

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

    return app
