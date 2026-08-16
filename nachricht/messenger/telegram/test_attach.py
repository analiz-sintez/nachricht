"""Regression tests for per-message `on_reaction` dispatch.

Both cases below reproduce the flow documented in docs/hacking.md, "How to
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

# Imported inside the tests that need it, not at module scope: the two fixes are
# independent, and a module-level import of the newer helper would turn a
# missing-helper failure into a COLLECTION error that also hides the
# registration results.


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


class TestNormaliseReactionMap:
    """`on_reaction` keys reach the dispatcher as Emoji members."""

    @staticmethod
    def _normalise():
        from .context import normalise_reaction_map

        return normalise_reaction_map

    def test_accepts_raw_emoji_symbols(self):
        """The spelling used throughout docs/hacking.md."""
        signal = object()

        result = self._normalise()({"👎": signal})

        assert result == {Emoji.THUMBSDOWN: signal}

    def test_accepts_emoji_members(self):
        signal = object()

        result = self._normalise()({Emoji.THUMBSDOWN: signal})

        assert result == {Emoji.THUMBSDOWN: signal}

    def test_drops_unknown_symbols_with_a_warning(self, caplog):
        """An emoji outside the enum can never dispatch, so say so."""
        normalise = self._normalise()

        with caplog.at_level("WARNING"):
            result = normalise({"🥑": object()})

        assert result == {}
        assert caplog.records, (
            "an undispatchable binding must be reported, not dropped silently"
        )
        assert "🥑" in caplog.records[0].getMessage()

    def test_mixed_spellings_coexist(self):
        thumbs, eyes = object(), object()

        result = self._normalise()({"👎": thumbs, Emoji.EYES: eyes})

        assert result == {Emoji.THUMBSDOWN: thumbs, Emoji.EYES: eyes}
