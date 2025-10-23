import logging

from sqlalchemy import Integer, String
from sqlalchemy.orm import mapped_column

from ..db import Model
from ..options import OptionsMixin


logger = logging.getLogger(__name__)


class User(Model, OptionsMixin):
    __tablename__ = "users"

    id = mapped_column(Integer, primary_key=True)
    login = mapped_column(String, unique=True)

    def to_dict(self):
        return {"id": self.id, "login": self.login}

    def __repr__(self):
        return f"<User(login='{self.login}')>"
