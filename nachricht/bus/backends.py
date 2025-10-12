import uuid
import json
import logging
from enum import Enum
from dataclasses import asdict
from abc import ABC, abstractmethod
from typing import List, Callable, Optional, Any
from datetime import datetime, timezone

from .signal import Signal
from ..db import db, Model

# Move DB Models here from the old saving_backends.py
# as they are specific to the DatabaseBackend implementation.
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Integer, JSON
from sqlalchemy.ext.mutable import MutableDict, MutableList
from ..db import dttm_utc

logger = logging.getLogger(__name__)


def encode_field(value):
    """
    Ensure all fields are serialized properly.
    """
    if isinstance(value, Enum):
        return value.name
    else:
        return value


class EmittedSignal(Model):
    __tablename__ = "emitted_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dttm_utc]
    signal_type: Mapped[str]
    signal_fields = mapped_column(MutableDict.as_mutable(JSON))
    slots = mapped_column(MutableList.as_mutable(JSON))


class SlotCall(Model):
    __tablename__ = "slot_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emitted_signal_id: Mapped[int]
    slot_name: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[dttm_utc]
    duration_ms: Mapped[int]
    error_message: Mapped[Optional[str]]


class AbstractSavingBackend(ABC):
    """
    Defines the interface for logging signal and slot activity.
    """

    @abstractmethod
    def log_signal_emitted(self, signal: Signal, slots: List[Callable]) -> Any:
        """
        Logs that a signal has been emitted.

        Returns:
            A correlation ID to link subsequent slot executions back to this
            specific emission event. Can be any type (int, str, UUID) or None.
        """
        pass

    @abstractmethod
    def log_slot_execution(
        self,
        emitted_signal_id: Any,
        slot: Callable,
        status: str,
        duration_ms: float,
        error_message: Optional[str] = None,
    ):
        """
        Logs the result of a single slot execution.
        """
        pass


class NoOpBackend(AbstractSavingBackend):
    """A backend that does nothing. The default."""

    def log_signal_emitted(
        self, signal: Signal, slots: List[Callable]
    ) -> None:
        return None

    def log_slot_execution(
        self,
        emitted_signal_id: Any,
        slot: Callable,
        status: str,
        duration_ms: float,
        error_message: Optional[str] = None,
    ):
        pass


class LogFileBackend(AbstractSavingBackend):
    """A backend that writes structured logs to the standard logger."""

    def log_signal_emitted(
        self, signal: Signal, slots: List[Callable]
    ) -> uuid.UUID:
        emitted_signal_id = uuid.uuid4()
        signal_dump = {
            "event": "signal_emitted",
            "emitted_signal_id": str(emitted_signal_id),
            "signal_type": type(signal).__name__,
            "signal_fields": {
                k: encode_field(v) for k, v in asdict(signal).items()
            },
            "triggered_slots": [slot.__name__ for slot in slots],
        }
        logger.info(json.dumps(signal_dump))
        return emitted_signal_id

    def log_slot_execution(
        self,
        emitted_signal_id: Any,
        slot: Callable,
        status: str,
        duration_ms: float,
        error_message: Optional[str] = None,
    ):
        log_entry = {
            "event": "slot_executed",
            "emitted_signal_id": str(emitted_signal_id),
            "slot_name": slot.__name__,
            "status": status,
            "duration_ms": round(duration_ms, 2),
        }
        if error_message:
            log_entry["error"] = error_message
        logger.info(json.dumps(log_entry))


class DatabaseBackend(AbstractSavingBackend):
    """A backend that saves signals and slot executions to the database."""

    def log_signal_emitted(
        self, signal: Signal, slots: List[Callable]
    ) -> Optional[int]:
        emitted_signal = EmittedSignal(
            ts=datetime.now(timezone.utc),
            signal_type=type(signal).__name__,
            signal_fields={
                k: encode_field(v) for k, v in asdict(signal).items()
            },
            slots=[slot.__name__ for slot in slots],
        )
        try:
            db.session.add(emitted_signal)
            db.session.flush()  # Flush to get the ID
            emitted_signal_id = emitted_signal.id
            db.session.commit()
            return emitted_signal_id
        except Exception:
            db.session.rollback()
            logger.error(
                "Failed to log emitted signal to database.", exc_info=True
            )
            return None

    def log_slot_execution(
        self,
        emitted_signal_id: Any,
        slot: Callable,
        status: str,
        duration_ms: float,
        error_message: Optional[str] = None,
    ):
        if emitted_signal_id is None:
            return  # Can't log without a parent signal ID

        log_entry = SlotCall(
            emitted_signal_id=emitted_signal_id,
            slot_name=slot.__name__,
            status=status,
            started_at=datetime.now(timezone.utc),
            duration_ms=int(duration_ms),
            error_message=error_message,
        )
        try:
            db.session.add(log_entry)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error(
                "Failed to log slot execution to database.", exc_info=True
            )
