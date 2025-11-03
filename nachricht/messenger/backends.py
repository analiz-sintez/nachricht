import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Union, Tuple

# Import your core objects
from .models import Message, Chat, Account, Conversation

ContextAwareObject = Union[Message, Chat, Account, Conversation]

logger = logging.getLogger(__name__)


class AbstractContextStore(ABC):
    @abstractmethod
    def __getitem__(self, obj: ContextAwareObject) -> Dict[str, Any]:
        """Returns the content dictionary."""
        pass


class MemoryContextStore(AbstractContextStore):
    _messages: Dict[Tuple[int, int], Dict[str, Any]] = {}
    _conversations: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
    _chats: Dict[int, Dict[str, Any]] = {}
    _accounts: Dict[int, Dict[str, Any]] = {}

    @classmethod
    def __getitem__(cls, obj: ContextAwareObject) -> Dict[str, Any]:
        """Returns the content dictionary."""
        if obj is None:
            return None
        elif isinstance(obj, Message):
            # Message context is stored in chats telegram context
            store = cls._messages
            key = (obj.id, obj.chat_id)
        elif isinstance(obj, Conversation):
            # Conversations reside in chats
            store = cls._conversations
            key = (obj.id, obj.chat_id, obj.account_id)
        elif isinstance(obj, Chat):
            # Message context is stored in users telegram context
            store = cls._chats
            key = obj.id
        elif isinstance(obj, Account):
            # Users context is stored in users telegram context
            store = cls._accounts
            key = obj.id
        else:
            logger.error(f"Unsupported context type: {type(obj)}.")
            return None

        # ... create the dict for the given object if missing
        if key not in store:
            store[key] = {}

        return store[key]
