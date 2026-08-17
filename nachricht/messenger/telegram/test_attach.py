"""Regression tests for per-message `on_reaction` dispatch.

The cases below reproduce the flow documented in docs/hacking.md, "How to
handle message reactions?", which attaches behaviour to a single message and
explicitly recommends doing that *instead* of registering global reaction
handlers. Before the accompanying fix, that documented flow could not work:

  1. `attach_router` registered the MessageReactionHandler only when the router
     had global reaction pegs, so an app following the documentation -- which
     has none -- never received reaction updates at all.
  2. `Emoji` is a plain `Enum`, so the documented raw-symbol keys
     (``{"👎": signal}``) hashed differently from the `Emoji` member the
     dispatcher looks up, and never matched.
"""

from unittest.mock import Mock

from telegram.ext import MessageReactionHandler

from .attach import attach_router
from ..context import Emoji
from ..routing import Router


class TestReactionHandlerRegistration:
    """attach_router must wire up reaction dispatch for per-message bindings."""

    def _handlers(self, router) -> list:
        application = Mock()
        added = []
        application.add_handler.side_effect = lambda h, *a, **kw: added.append(h)
        attach_router(router, application)
        return added

    def test_registers_reaction_handler_without_global_pegs(self):
        """The documented per-message flow registers no global peg.

        This is the regression: with no `@router.reaction`, the handler used to
        be skipped entirely, so `on_reaction=` bindings silently never fired.
        """
        router = Router()
        assert not router.reaction_pegs

        handlers = self._handlers(router)

        assert any(isinstance(h, MessageReactionHandler) for h in handlers), (
            "no MessageReactionHandler was registered, so per-message "
            "on_reaction bindings can never dispatch"
        )

    def test_registers_reaction_handler_with_global_pegs(self):
        """The pre-existing global-peg path keeps working."""
        router = Router()

        @router.reaction([Emoji.THUMBSDOWN])
        async def _downvoted(**kwargs):
            pass

        assert router.reaction_pegs

        handlers = self._handlers(router)

        assert any(isinstance(h, MessageReactionHandler) for h in handlers)
