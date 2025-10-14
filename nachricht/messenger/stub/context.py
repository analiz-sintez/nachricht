"""
This is a stub for a new messenger adaptor, the second half of it.

You need to implement the Context class for your messenger:
- getters for the entities: use, account, locale etc;
- send_message method which sends or edits bot messages.

The Context object is called `ctx` in application code, and is passed as
the first argument to both peg handlers and signal handlers (slots).

You may implement things gradually, or if some functionality (e.g. images)
is not supported in your messenger, skip it and log an error.

Don't forget about the other half: the functions which attach an application
(pegs collected by the Router and signals from the Bus) to the messenger.
"""

from datetime import datetime
from typing import Optional, Union, List, Dict
from ...i18n import TranslatableString
from ...bus import Signal
from ..context import (
    Context,
    Account,
    User,
    Locale,
    Message,
    Conversation,
    Chat,
    Keyboard,
    Emoji,
)


class YourMessengerContext(Context):
    """
    TODO:

    Stores all contextual info, preferably in a messenger-independent
    way. Should support Telegram, Whatsapp, Matrix, Slack, Mattermost,
    maybe even IRC.
    """

    def __init__(self, config: Optional[object] = None):
        self.config = config

    def username(self) -> str:
        # ... your code here ...
        pass

    @property
    def account(self) -> Account:
        """The messenger account which initiated an update."""
        # ... your code here ...
        pass

    @property
    def user(self) -> User:
        """The app user which initiated an update."""
        # ... your code here ...
        pass

    @property
    def locale(self) -> Locale:
        """Locale to use for the interface."""
        # ... your code here ...
        pass

    @property
    def message(self) -> Optional[Message]:
        """The message the **user** sent."""
        # ... your code here ...
        pass

    @property
    def bot_message(self) -> Optional[Message]:
        """The last message that the **bot** sent."""
        # ... your code here ...
        pass

    @property
    def conversation(self) -> Optional[Conversation]:
        # ... your code here ...
        pass

    @conversation.setter
    def conversation(self, value: Conversation):
        # ... your code here ...
        pass

    def context(
        self, obj: Union[Message, Chat, Account, Conversation]
    ) -> Dict:
        """Return a context dict for a given object."""
        # ... your code here ...
        pass

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
        # ... your code here ...
        pass
