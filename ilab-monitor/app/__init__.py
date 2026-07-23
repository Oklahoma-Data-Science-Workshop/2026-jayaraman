import os
import logging
from flask import Flask
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)


def create_app():
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config['POLL_INTERVAL_MINUTES'] = int(os.environ.get('POLL_INTERVAL_MINUTES', 15))

    from app.models import init_db
    init_db(app)

    from app.routes import bp
    app.register_blueprint(bp)

    username = os.environ.get('ILAB_USERNAME', '')
    password = os.environ.get('ILAB_PASSWORD', '')

    if username and password and not os.environ.get('TESTING'):
        from ilab_client import ILabClient
        from app.poller import start_poller
        client = ILabClient(username, password)
        try:
            client.login()
        except Exception as e:
            logging.getLogger(__name__).error('Initial login failed: %s', e)
        start_poller(app, client)

    return app
