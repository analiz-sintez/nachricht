from typing import Optional
from .tracing import NoOpPegTracer, DatabasePegTracer, AbstractPegTracer
from .routing import Router
from .context import (
    Context,
    Button,
    Keyboard,
    Message,
    Account,
    Chat,
    Emoji,
    Conversation,
)

router: Optional[Router] = None


def _create_peg_tracer(config: object) -> Optional[AbstractPegTracer]:
    """Creates a peg tracer instance based on configuration."""
    backend_name = config.SIGNALS.get("logging_backend")
    if backend_name == "db":
        return DatabasePegTracer()
    # elif backend_name == "log":
    #     return LogFileBackend()
    elif backend_name is None or backend_name in ("none", "noop"):
        return NoOpPegTracer()
    else:
        raise NotImplementedError(
            "Unknown config option for signals logging: %s" % backend_name
        )


def create_router(config: object):
    global router
    router = Router(config=config, peg_tracer=_create_peg_tracer(config))
    return router


def get_router() -> Optional[Router]:
    return router
