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
    from app.routes import main_bp, tax_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(tax_bp, url_prefix="/tax")

    return app
