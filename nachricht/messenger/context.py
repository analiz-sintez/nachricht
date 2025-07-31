import logging
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Union
from dataclasses import dataclass
from typing import (
    List,
    Optional,
)
from babel import Locale

from core.auth import User

from ..bus import Signal
from ..i18n import TranslatableString

logger = logging.getLogger(__name__)


@dataclass
class Account:
    """Messenger account. Not to be confused with a bot User."""

    id: int
    login: str
    locale: Locale
    _: Optional[object] = None  # raw object


@dataclass
class Chat:
    id: int
    _: Optional[object]


@dataclass
class Message:
    id: int
    chat_id: int
    user_id: Optional[int] = None
    text: Optional[str] = None
    parent: Optional[object] = None  # another Message object
    # context: Dict
    # messenger: str
    # conversation: Conversation
    _: Optional[object] = None  # raw object


@dataclass
class Conversation:
    """
    Messages are grouped into conversations.
    Messages within a single conversation most probably share the same
    context.

    If a message leads to an emittance of a signal, this signal may be
    processed differently whether it belongs to a conversation or not.

    E.g. when a user selects the studying language, the signal is emitted.
    If the user is in the middle of the onboarding, this signal should lead
    to the next step of it, otherwise the signal should be ignored.

    For now, a new conversation is started:
    - if it is directly said by a send_message parameter
    - if no parent message with a conversation is found

    The message is not necessarily ascribed to a conversation.
    """

    id: int


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


class Context:
    """
    TODO:

    Stores all contextual info, preferably in a messenger-independent
    way. Should support Telegram, Whatsapp, Matrix, Slack, Mattermost,
    maybe even IRC.
    """

    def __init__(self, config: Optional[object] = None):
        self.config = config

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
    def message(self) -> Optional[Message]:
        raise NotImplementedError()

    @property
    def conversation(self) -> Optional[Conversation]:
        raise NotImplementedError()

    @conversation.setter
    def conversation(self, value: Conversation):
        raise NotImplementedError()

    def start_conversation(self, **context):
        """Start a new conversation."""
        id = int(1000 * datetime.now().timestamp())
        conv = Conversation(id)
        self.conversation = conv
        for key, value in context.items():
            self.context(conv)[key] = value

    def context(
        self, obj: Union[Message, Chat, Account, Conversation]
    ) -> Dict:
        """Return a context dict for a given object."""
        # TODO bad naming?
        raise NotImplementedError()

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
