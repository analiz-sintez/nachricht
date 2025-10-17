import logging
from abc import ABC, abstractmethod
from typing import Callable, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Integer, JSON
from sqlalchemy.ext.mutable import MutableDict

from ..db import db, Model, dttm_utc

logger = logging.getLogger(__name__)


class PegTrigger(Model):
    __tablename__ = "peg_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dttm_utc]
    peg_type: Mapped[str]
    peg_identifier: Mapped[str]
    handler_function: Mapped[str]
    context_info = mapped_column(MutableDict.as_mutable(JSON))


class AbstractPegTracer(ABC):
    @abstractmethod
    def trace_peg_trigger(
        self,
        peg_type: str,
        peg_identifier: str,
        handler: Callable,
        context_info: Dict,
    ) -> None:
        pass


class NoOpPegTracer(AbstractPegTracer):
    def trace_peg_trigger(self, *args, **kwargs) -> None:
        pass


class DatabasePegTracer(AbstractPegTracer):
    def trace_peg_trigger(
        self,
        peg_type: str,
        peg_identifier: str,
        handler: Callable,
        context_info: Dict,
    ) -> Any:
        trigger = PegTrigger(
            ts=datetime.now(timezone.utc),
            peg_type=peg_type,
            peg_identifier=str(peg_identifier),
            handler_function=handler.__name__,
            context_info=context_info,
        )
        try:
            db.session.add(trigger)
            db.session.flush()
            db.session.commit()
            return trigger.id
        except Exception:
            db.session.rollback()
            logger.error("Failed to log peg trigger.", exc_info=True)
