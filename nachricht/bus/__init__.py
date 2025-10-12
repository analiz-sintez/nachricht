from typing import Optional
from .signal import (
    Signal,
    TerminalSignal,
)
from .service import (
    Bus,
    encode,
    decode,
    make_regexp,
    unoption,
    check_conditions,
    Conditions,
)
from .backends import LogFileBackend, DatabaseBackend

bus: Optional[Bus] = None


def create_bus(config: object):
    global bus
    if config.SIGNALS["logging_backend"] == "db":
        bus = Bus(saving_backend=DatabaseBackend(), config=config)
    elif config.SIGNALS["logging_backend"] == "log":
        bus = Bus(saving_backend=LogFileBackend(), config=config)
    else:
        raise NotImplementedError(
            "Unknown config option for signals logging: %s"
            % config.SIGNALS["logging_backend"]
        )
    return bus


def get_bus() -> Optional[Bus]:
    return bus
