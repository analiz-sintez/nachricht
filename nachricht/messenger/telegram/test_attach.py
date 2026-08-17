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

The dispatch tests additionally pin the two halves of reaction resolution
together: `normalise_reaction_map` keeps a symbol `Emoji` doesn't declare, so
this dispatcher has to resolve an incoming one the same way, or those bindings
are dropped a second time.
"""

from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from telegram.ext import MessageReactionHandler

from . import attach
from .attach import attach_router
from ..context import Emoji, normalise_reaction_map
from ..routing import Router
from ...bus import Signal


@dataclass
class _Ping(Signal):
    """A distinguishable signal: a bare `Signal()` equals any other."""

    tag: str


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


class _FakeContext:
    """A stand-in for TelegramContext over the reaction dispatch path."""

    def __init__(self, message_context: dict):
        self.chat = object()
        self._chat_context: dict = {}
        self._message_context = message_context

    def context(self, obj) -> dict:
        if obj is self.chat:
            return self._chat_context
        return self._message_context


class TestReactionDispatch:
    """An incoming reaction must reach the binding stored on the message."""

    async def _emitted_by(self, monkeypatch, symbol: str, on_reaction: dict):
        """Deliver `symbol` to a message carrying `on_reaction`."""
        emitted = []

        class _FakeBus:
            async def emit_and_wait(self, signal, **kwargs):
                emitted.append(signal)

        monkeypatch.setattr(
            attach,
            "TelegramContext",
            lambda *args, **kwargs: _FakeContext(
                {"_on_reaction": on_reaction}
            ),
        )
        monkeypatch.setattr(attach, "get_bus", lambda: _FakeBus())

        handler = attach._create_reaction_handler([], Mock())

        update = Mock()
        update.message_reaction.message_id = 1
        update.message_reaction.chat.id = 2
        update.message_reaction.new_reaction = [Mock(emoji=symbol)]

        await handler.callback(update, Mock())
        return emitted

    @pytest.mark.asyncio
    async def test_dispatches_a_declared_emoji(self, monkeypatch):
        """Bound by raw symbol, delivered by symbol, matched as an Emoji."""
        signal = _Ping("thumbs")

        emitted = await self._emitted_by(
            monkeypatch, "👎", normalise_reaction_map({"👎": [signal]})
        )

        assert emitted == [signal]

    @pytest.mark.asyncio
    async def test_dispatches_an_undeclared_emoji(self, monkeypatch):
        """The half `normalise_reaction_map` cannot deliver on its own.

        Keeping "🥑" in the map is inert unless the dispatcher also falls back
        to the raw symbol -- `Emoji.get` would otherwise resolve it to None and
        dispatch would stop before reaching the binding.
        """
        signal = _Ping("avocado")

        emitted = await self._emitted_by(
            monkeypatch, "🥑", normalise_reaction_map({"🥑": [signal]})
        )

        assert emitted == [signal]

    @pytest.mark.asyncio
    async def test_ignores_an_unbound_reaction(self, monkeypatch):
        """A reaction nothing is bound to emits nothing."""
        emitted = await self._emitted_by(
            monkeypatch,
            "🔥",
            normalise_reaction_map({"👎": [_Ping("thumbs")]}),
        )

        assert emitted == []
