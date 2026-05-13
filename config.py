import os

basedir = os.path.abspath(os.path.dirname(__file__))

# Vercel serverless: filesystem is read-only except /tmp
IS_VERCEL = os.environ.get("VERCEL", "")

if IS_VERCEL:
    db_path = "/tmp/xiaoda.db"
else:
    db_path = os.path.join(basedir, "instance", "xiaoda.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "xiaoda-tax-dev-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{db_path}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
