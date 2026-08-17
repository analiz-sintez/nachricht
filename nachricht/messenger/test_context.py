"""Tests for the messenger-agnostic reaction helpers."""

from .context import Emoji, normalise_reaction_map


class TestNormaliseReactionMap:
    """`on_reaction` keys reach the dispatcher as Emoji members.

    `Emoji` is a plain `Enum`, not a `str`-Enum, so a raw-symbol key hashes
    differently from the member a dispatcher looks up. Both spellings are
    documented in docs/hacking.md, so both must work.
    """

    def test_accepts_raw_emoji_symbols(self):
        """The spelling used throughout docs/hacking.md."""
        signal = object()

        result = normalise_reaction_map({"👎": signal})

        assert result == {Emoji.THUMBSDOWN: signal}

    def test_accepts_emoji_members(self):
        signal = object()

        result = normalise_reaction_map({Emoji.THUMBSDOWN: signal})

        assert result == {Emoji.THUMBSDOWN: signal}

    def test_drops_unknown_symbols_with_a_warning(self, caplog):
        """An emoji outside the enum can never dispatch, so say so."""
        with caplog.at_level("WARNING"):
            result = normalise_reaction_map({"🥑": object()})

        assert result == {}
        assert caplog.records, (
            "an undispatchable binding must be reported, not dropped silently"
        )
        assert "🥑" in caplog.records[0].getMessage()

    def test_mixed_spellings_coexist(self):
        thumbs, eyes = object(), object()

        result = normalise_reaction_map({"👎": thumbs, Emoji.EYES: eyes})

        assert result == {Emoji.THUMBSDOWN: thumbs, Emoji.EYES: eyes}
