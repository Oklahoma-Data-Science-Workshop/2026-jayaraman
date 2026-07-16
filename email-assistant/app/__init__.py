from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config

db = SQLAlchemy()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Honor reverse-proxy headers so url_for() includes the /email-assistant prefix
    # (nginx strips the prefix but sends X-Forwarded-Prefix)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Initialize extensions
    db.init_app(app)
    
    # Register blueprints
    from app.routes import main, emails, api
    
    app.register_blueprint(main.bp)
    app.register_blueprint(emails.bp)
    app.register_blueprint(api.bp)
    
    # Create tables
    with app.app_context():
        import os
        os.makedirs(app.config['BASE_DIR'] / 'instance', exist_ok=True)
        db.create_all()
        
        # Initialize default tags
        from app.models import Tag
        from config import Config
        for topic_data in Config.TOPICS:
            tag = Tag.query.filter_by(name=topic_data['name']).first()
            if not tag:
                tag = Tag(
                    name=topic_data['name'],
                    category='topic',
                    color=topic_data['color'],
                    icon=topic_data['icon']
                )
                db.session.add(tag)
        db.session.commit()
    
    return app
