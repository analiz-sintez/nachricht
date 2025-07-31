import json
import logging
from enum import Enum
from typing import Callable
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Integer, JSON
from sqlalchemy.ext.mutable import MutableDict, MutableList

from .service import Signal
from ..db import db, Model, dttm_utc


logger = logging.getLogger(__name__)


def encode_field(value):
    """
    Ensure all fields are serialized properly.
    """
    if isinstance(value, Enum):
        return value.name
    else:
        return value


def dump_signal_to_log(signal: Signal, slots: list[Callable]) -> None:
    """
    Write emitted signal into application log.
    """
    signal_dump = {
        "signal_type": type(signal).__name__,
        "signal_fields": {
            k: encode_field(v) for k, v in asdict(signal).items()
        },
        "slots": [slot.__name__ for slot in slots],
    }
    logger.debug(json.dumps(signal_dump))


class EmittedSignal(Model):
    __tablename__ = "emitted_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dttm_utc]
    signal_type: Mapped[str]
    signal_fields = mapped_column(MutableDict.as_mutable(JSON))
    slots = mapped_column(MutableList.as_mutable(JSON))


def dump_signal_to_db(signal: Signal, slots: list[Callable]) -> None:
    """
    Write emitted signal into the database for further analysis.
    """
    emitted_signal = EmittedSignal(
        ts=datetime.now(timezone.utc),
        signal_type=type(signal).__name__,
        signal_fields={k: encode_field(v) for k, v in asdict(signal).items()},
        slots=[slot.__name__ for slot in slots],
    )
    try:
        db.session.add(emitted_signal)
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        logger.error("Integrity error occurred while logging a signal: %s", e)
        raise ValueError("Integrity error occurred while logging a signal.")
