"""Tests for the messenger-agnostic reaction helpers."""

from dataclasses import dataclass

from ..bus import Signal
from .context import Emoji, normalise_reaction_map


@dataclass
class _Ping(Signal):
    """A distinguishable signal: a bare `Signal()` equals any other."""

    tag: str


class TestNormaliseReactionMap:
    """`on_reaction` keys reach a backend's dispatcher in a matchable form.

    `Emoji` is a plain `Enum`, not a `str`-Enum, so a raw-symbol key hashes
    differently from the member a dispatcher looks up. Both spellings are
    documented in docs/hacking.md, so both must work.
    """

    def test_accepts_raw_emoji_symbols(self):
        """The spelling used throughout docs/hacking.md."""
        signal = _Ping("thumbs")

        result = normalise_reaction_map({"👎": signal})

        assert result == {Emoji.THUMBSDOWN: signal}

    def test_accepts_emoji_members(self):
        signal = _Ping("thumbs")

        result = normalise_reaction_map({Emoji.THUMBSDOWN: signal})

        assert result == {Emoji.THUMBSDOWN: signal}

    def test_mixed_spellings_coexist(self):
        thumbs, eyes = _Ping("thumbs"), _Ping("eyes")

        result = normalise_reaction_map({"👎": thumbs, Emoji.EYES: eyes})

        assert result == {Emoji.THUMBSDOWN: thumbs, Emoji.EYES: eyes}

    def test_keeps_undeclared_symbols(self):
        """`Emoji` declares a fraction of what a messenger may deliver.

        Telegram alone allows ~70 reaction emojis against this enum's ~30, so
        dropping the undeclared ones would disable most bindings an app author
        could plausibly write. Keep the symbol; the backend resolves an
        incoming one the same way.
        """
        signal = _Ping("avocado")

        result = normalise_reaction_map({"🥑": signal})

        assert result == {"🥑": signal}

    def test_warns_about_undeclared_symbols(self, caplog):
        """Kept, but not silently: an exact-match binding is worth flagging."""
        with caplog.at_level("WARNING"):
            normalise_reaction_map({"🥑": _Ping("avocado")}, message_id=42)

        assert caplog.records, "an undeclared reaction must be reported"
        message = caplog.records[0].getMessage()
        assert "🥑" in message
        assert "42" in message

    def test_declared_symbols_do_not_warn(self, caplog):
        with caplog.at_level("WARNING"):
            normalise_reaction_map(
                {"👎": _Ping("thumbs"), Emoji.EYES: _Ping("eyes")}
            )

        assert not caplog.records
