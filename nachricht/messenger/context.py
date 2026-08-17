import logging
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Union, List
from dataclasses import dataclass
from babel import Locale

from nachricht.auth import User

from ..bus import Signal
from ..i18n import TranslatableString

from .models import Account, Chat, Message, Conversation
from .backends import (
    ContextAwareObject,
    AbstractContextStore,
    MemoryContextStore,
)

logger = logging.getLogger(__name__)


@dataclass
class Button:
    text: Union[str, TranslatableString]
    callback: Signal


@dataclass
class Keyboard:
    buttons: List[List[Button]]


class Emoji(Enum):
    """
    Popular emojis.
    """

    @classmethod
    def exists(cls, symbol: str) -> bool:
        return symbol in cls._value2member_map_

    @classmethod
    def get(
        cls, symbol: str, default: Optional["Emoji"] = None
    ) -> Optional["Emoji"]:
        """
        Get an Emoji by the emoji symbol or return `default` if the symbol
        is not found.

        Example:
        > Emoji.get("😀", default=Emoji.SMILE)
        or even shorter,
        > Emoji.get("😀", Emoji.SMILE)
        """
        if not cls.exists(symbol):
            return default
        return cls(symbol)

    GRINNING = "😀"
    SMILEY = "😃"
    SMILE = "😄"
    GRIN = "😁"
    JOY = "😂"
    ROFL = "🤣"
    SWEAT_SMILE = "😅"
    HEART_EYES = "😍"
    FACE_WITH_HAND_OVER_MOUTH = "🤭"
    THINKING = "🤔"
    RELIEVED = "😌"
    SMIRK = "😏"
    UNAMUSED = "😒"
    SOB = "😭"
    CRY = "😢"
    PLEADING_FACE = "🥺"
    INNOCENT = "😇"
    ANGRY = "😠"
    RAGE = "😡"
    THUMBSUP = "👍"
    THUMBSDOWN = "👎"
    CLAP = "👏"
    PRAY = "🙏"
    OK_HAND = "👌"
    WAVE = "👋"
    EYES = "👀"
    SEE_NO_EVIL = "🙈"
    FIRE = "🔥"
    HUNDRED = "💯"
    HEART = "❤️"
    POOP = "💩"


def normalise_reaction_map(on_reaction: Dict, message_id=None) -> Dict:
    """Coerce the keys of an `on_reaction` map to `Emoji` members.

    A messenger backend resolves an incoming reaction to an `Emoji` (via
    `Emoji.get`) and then looks it up in this map.
    `Emoji` is a plain `Enum`, not a `str`-Enum, so a raw-symbol key such as
    ``{"👎": signal}`` hashes differently from ``Emoji.THUMBSDOWN`` and could
    never match -- yet that raw-symbol form is what docs/hacking.md documents.

    Accept both spellings, and warn about a symbol `Emoji` does not know rather
    than dropping it silently: a binding that never fires is otherwise
    indistinguishable from a bot that is not running.
    """
    normalised = {}
    for key, signals in on_reaction.items():
        emoji = key if isinstance(key, Emoji) else Emoji.get(key)
        if emoji is None:
            logger.warning(
                "Unknown reaction emoji %r for message id=%s: not a member of "
                "Emoji, so this binding would never dispatch; ignoring it.",
                key,
                message_id,
            )
            continue
        normalised[emoji] = signals
    return normalised


class Context:
    """
    TODO:

    Stores all contextual info, preferably in a messenger-independent
    way. Should support Telegram, Whatsapp, Matrix, Slack, Mattermost,
    maybe even IRC.
    """

    def __init__(
        self,
        config: Optional[object] = None,
        store: Optional[AbstractContextStore] = None,
    ):
        self.config = config
        if not store:
            store = MemoryContextStore()
        self._store = store

    def username(self) -> str:
        raise NotImplementedError()

    @property
    def account(self) -> Account:
        """The messenger account which initiated an update."""
        raise NotImplementedError()

    @property
    def user(self) -> User:
        """The app user which initiated an update."""
        raise NotImplementedError()

    @property
    def locale(self) -> Locale:
        """Locale to use for the interface."""
        raise NotImplementedError()

    @property
    def chat(self) -> Chat:
        """The chat where messages are sent."""
        raise NotImplementedError()

    @property
    def message(self) -> Optional[Message]:
        """The message the **user** sent."""
        raise NotImplementedError()

    @property
    def bot_message(self) -> Optional[Message]:
        """The last message that the **bot** sent."""
        raise NotImplementedError()

    @property
    def conversation(self) -> Optional[Conversation]:
        if hasattr(self, "_conversation"):
            return self._conversation

        conv = None
        # If the message is ascribed to a conversation, return it.
        if self.message and (
            id := self.context(self.message).get("_conversation")
        ):
            conv = Conversation(
                id=id, chat_id=self.chat.id, account_id=self.account.id
            )
        # Otherwise, check its parent message.
        elif self.bot_message and (
            id := self.context(self.bot_message).get("_conversation")
        ):
            conv = Conversation(
                id=id, chat_id=self.chat.id, account_id=self.account.id
            )

        self._conversation = conv
        return self._conversation

    @conversation.setter
    def conversation(self, value: Conversation):
        if not isinstance(value, Conversation):
            raise TypeError()
        self._conversation = value

    def start_conversation(self, **context):
        """Start a new conversation."""
        id = int(1000 * datetime.now().timestamp())
        conv = Conversation(
            id=id, chat_id=self.chat.id, account_id=self.account.id
        )
        self.conversation = conv
        for key, value in context.items():
            self.context(conv)[key] = value

    def context(self, obj: ContextAwareObject) -> Dict:
        """Return a context dict for a given object."""
        return self._store[obj]

    async def send_message(
        self,
        text: Union[str, TranslatableString],
        markup: Optional[Keyboard] = None,
        image: Optional[str] = None,
        new: bool = False,
        reply_to: Optional[Message] = None,
        on_reply: Optional[Signal] = None,
        on_reaction: Optional[Dict[Emoji, Union[Signal, List[Signal]]]] = None,
        on_command: Optional[Dict[str, Union[Signal, List[Signal]]]] = None,
        context: Optional[Dict] = None,
        account: Optional[Account] = None,
        user: Optional[User] = None,
        chat: Optional[Chat] = None,
    ):
        """
        Arguments:
        new:
          Don't edit the message even if it's possible.
        reply_to:
          A message which to reply.
        on_reply:
          A signal to be emitted if a user replies to this message.
          What counts as reply is determined by each messenger's adaptor.
          Recommended options are:
          - For telegram-like messengers: direct reply with a "reply" mechanics.
          - Also, a message right after the current one, without intermittance by
            a command, and possibly within a given time frame, should count as
            reply.
          - For slack-like messengers: a message in the same thread.
        on_reaction:
          Signals to be emitted if a reaction is sent to the message.
          Reaction emojis are dict keys, values are Signals that should be emitted
          if such a reaction is recieved.
          If a list of signals is provided, they are called one after one (not
          simultaneously), each next Signal awaits for the previous to be processed.
        on_command:
          The same as `on_reaction` but for commands. The command must be a reply to
          the message, otherwise it will be processed in the geenral flow.

        """
        raise NotImplementedError()
