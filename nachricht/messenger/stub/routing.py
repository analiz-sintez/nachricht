"""
This is a stub for a new messenger adaptor, the first half of it.

You need to implement two things here:

1. how the handlers collected by the router is attached to the bot application;
2. how the callbacks are passed to the bus and how signals are fetched from them.

Don't forget about the other half: the Context object (see the other file in
this dir).
"""

import logging
from typing import Type
from inspect import getmodule

from .. import Router
from ...bus import Bus, Signal, decode, make_regexp

logger = logging.getLogger(__name__)


class Application:
    """
    This class should be provided by your messenger framework.
    """

    def add_handler(self, fn):
        pass


def _create_command_handler(peg, router):
    return None


def _create_message_handler(peg, router):
    return None


def _create_reaction_handler(peg, router):
    return None


def _create_callback_handler(peg, router):
    return None


def attach_router(router: Router, application: Application):
    """
    Attach the stored handlers from a generic Router to the Telegram application.
    """
    logger.info("Attaching handlers to the application:")

    # ... here your logic goes ...
    # ... those lines are just examples, your logic may be more complex ...
    logger.info("... attaching command pegs")
    for peg in router.command_pegs:
        # ... build a command handler for the messenger here
        handler = _create_command_handler(peg, router)
        # ...
        application.add_handler(handler)

    logger.info("... attaching message pegs")
    for peg in router.message_pegs:
        # ... build a message handler for the messenger here
        handler = _create_message_handler(peg, router)
        # ...
        application.add_handler(handler)

    logger.info("... attaching reaction pegs")
    for peg in router.reaction_pegs:
        # ... build a reaction handler for the messenger here
        handler = _create_reaction_handler(peg, router)
        # ...
        application.add_handler(handler)

    logger.info("... attaching callback pegs")
    for peg in router.callback_pegs:
        # ... build a callback handler for the messenger here
        handler = _create_callback_handler(peg, router)
        # ...
        application.add_handler(handler)


class CallbackHandler:
    """
    This class should be provided by your messenger framework.
    """

    def __init__(self, fn, pattern):
        pass


def attach_bus(bus: Bus, application: Application):
    def make_handler(signal_type: Type[Signal]) -> CallbackHandler:
        signal_name = signal_type.__name__

        # Make a signal emitter.
        async def decode_and_emit():
            # ... get callback query data
            data = ""
            logger.debug(f"Got callback: {data}, decoding as {signal_name}.")
            # ... create a signal from the name and the data
            signal = decode(signal_type, data)
            if not signal:
                logger.warning(f"Decoding {signal_name} failed.")
                return
            # ... get the signal context for your messenger
            #     (which you'll implement in ./context.py)
            ctx = None
            # ... emit the signal via the bus
            await bus.emit_and_wait(signal, ctx=ctx)

        # Register a handler for the signal type.
        pattern = make_regexp(signal_type)
        logger.debug(f"Registering handler: {pattern} -> {signal_name}")
        handler = CallbackHandler(decode_and_emit, pattern=pattern)
        return handler

    bus.setup()

    logging.info("Bus: registering signal handlers.")
    for signal_type in bus.signals():
        module_name = getmodule(signal_type).__name__
        signal_name = signal_type.__name__
        logging.debug(
            f"Bus: registering a handler for {module_name}.{signal_name}."
        )
        application.add_handler(make_handler(signal_type))

    logging.info("Bus: all signals registered.")
