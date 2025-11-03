import logging
from typing import Optional
from dataclasses import dataclass
from babel import Locale


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
    _: Optional[object] = None


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
    chat_id: int
    account_id: int
    _: Optional[object] = None  # raw object
