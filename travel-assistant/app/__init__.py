from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_prefix=1)

    db.init_app(app)

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()
        # Add mode column to existing databases that predate this field
        try:
            db.session.execute(db.text(
                "ALTER TABLE trip_sessions ADD COLUMN mode VARCHAR(20) DEFAULT 'plan'"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

    return app
