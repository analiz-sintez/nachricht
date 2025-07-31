from typing import Optional
from .service import (
    Signal,
    TerminalSignal,
    Bus,
    encode,
    decode,
    make_regexp,
    unoption,
    check_conditions,
    Conditions,
)
from .saving_backends import dump_signal_to_log, dump_signal_to_db

bus: Optional[Bus] = None


def create_bus(config: object):
    global bus
    if config.SIGNALS["logging_backend"] == "db":
        bus = Bus(saving_backend=dump_signal_to_db, config=config)
    elif config.SIGNALS["logging_backend"] == "log":
        bus = Bus(saving_backend=dump_signal_to_log, config=config)
    else:
        raise NotImplementedError(
            "Unknown config option for signals logging: %s"
            % config.SIGNALS["logging_backend"]
        )
    return bus


def get_bus() -> Optional[Bus]:
    return bus
