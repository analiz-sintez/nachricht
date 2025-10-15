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
    trace_id_var,
)
from .backends import (
    AbstractSavingBackend,
    LogFileBackend,
    DatabaseBackend,
    EmittedSignal,
    SlotCall,
)

from typing import Optional, Any

bus: Optional[Bus] = None


def _create_saving_backend(config: object) -> Optional[AbstractSavingBackend]:
    """Creates a saving backend instance based on configuration."""
    backend_name = config.SIGNALS.get("logging_backend")
    if backend_name == "db":
        return DatabaseBackend()
    elif backend_name == "log":
        return LogFileBackend()
    elif backend_name is None or backend_name in ("none", "noop"):
        return None
    else:
        raise NotImplementedError(
            "Unknown config option for signals logging: %s" % backend_name
        )


def create_bus(config: object):
    global bus
    bus = Bus(config=config, saving_backend=_create_saving_backend(config))
    return bus


def get_bus() -> Optional[Bus]:
    return bus
