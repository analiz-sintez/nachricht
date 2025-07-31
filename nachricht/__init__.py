import os
from datetime import datetime
import logging
from flask import Flask
from flask_migrate import Migrate

from .db import db


def setup_logging():
    # Set up logging:
    # ... ensure the directory for logs exists
    log_dir = "./logs"
    os.makedirs(log_dir, exist_ok=True)
    log_filename = (
        f"telegram-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.log"
    )
    # ... set handlers and their levels
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    file_handler = logging.FileHandler(f"{log_dir}/{log_filename}")
    file_handler.setLevel(logging.DEBUG)
    # ... install handlers and set common settings
    log_format = "%(asctime)s\t%(name)s\t%(levelname)s\t%(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=log_format,
        handlers=[console_handler, file_handler],
    )


def create_app(config: object):
    # setup_logging()
    logger = logging.getLogger(__name__)

    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        logger.info("Database tables created.")

    migrate = Migrate(app, db)
    logger.info("Migrations set up.")

    logger.info("Application setup complete.")

    return app
