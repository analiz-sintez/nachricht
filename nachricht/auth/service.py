import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError

from ..db import db
from .models import User

# Set up logging

logger = logging.getLogger(__name__)


def get_user(login):
    logger.info("Retrieving user with login: %s", login)
    user = User.query.filter_by(login=login).first()
    if not user:
        logger.info("User not found, creating new user with login: %s", login)
        user = User(login=login)
        try:
            db.session.add(user)
            db.session.commit()
            logger.info("User created successfully: %s", user)
        except IntegrityError as e:
            db.session.rollback()
            logger.error(
                "Integrity error occurred while creating a user: %s", e
            )
            raise ValueError("Integrity error occurred while creating a user.")
    return user
