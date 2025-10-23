import logging
from datetime import datetime
from typing import Union, Dict, List, TypeAlias, Annotated

from sqlalchemy.orm import Query, mapped_column, DeclarativeBase
from sqlalchemy.sql import Select
from sqlalchemy_utc import UtcDateTime
from flask_sqlalchemy import SQLAlchemy


class BaseModel(DeclarativeBase):
    """
    This one is required to calm down pyright.
    see: https://github.com/pallets-eco/flask-sqlalchemy/issues/1327
    """

    pass


# It's thread-safe while it's from flask_sqlalchemy.
# If replacing flask with fastapi etc, refactor this
# to make thread-safe.
db = SQLAlchemy(model_class=BaseModel)
Model: BaseModel = db.Model  # pyright: ignore

logger = logging.getLogger(__name__)


dttm_utc = Annotated[datetime, mapped_column(UtcDateTime)]

JsonValue: TypeAlias = Union[
    Dict[str, "JsonValue"], List["JsonValue"], str, int, float, bool, None
]


def log_sql_query(query: Union[Query, Select]) -> None:
    """
    Log the SQL query statement if available.

    Args:
        query: SQLAlchemy query object.
    """
    if isinstance(query, Query):
        query = query.statement

    query_text = str(query.compile(compile_kwargs={"literal_binds": True}))
    logger.debug("SQL Query: %s", query_text)
