import re
from datetime import datetime
from typing import Optional, List, Dict, Union
import logging

from babel import Locale
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram import (
    Update,
    InputMediaPhoto,
    Message as PTBMessage,
    Chat as PTBChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from ...auth import User, get_user
from ...bus import Signal, encode
from .. import (
    Context,
    Button,
    Keyboard,
    Account,
    Message,
    Chat,
    Emoji,
    Conversation,
)
from ...i18n import TranslatableString, resolve


logger = logging.getLogger(__name__)


to_escape = r"[]()#+-={}.!]"
escape_chars = re.compile(rf"""(\[.*?\]\(.*?\))|([{re.escape(to_escape)}])""")


def _escape_markdown_v2(text):
    def replacer(match):
        if match.group(1):  # markdown link
            return match.group(1)
        else:  # special char outside link
            return f"\\{match.group(2)}"

    return escape_chars.sub(replacer, text)


class TelegramContext(Context):
    parse_mode = ParseMode.MARKDOWN_V2

    def __init__(
        self,
        update: Update,
        context: CallbackContext,
        config: Optional[object] = None,
    ):
        self._update = update
        self._context = context
        return super().__init__(config)

    @property
    def account(self) -> Account:
        """The messenger account which initiated an update."""
        if not hasattr(self, "_account"):
            tg_user = self._update.effective_user
            try:
                locale = Locale.parse(tg_user.language_code)
            except Exception as e:
                logger.error("Wrong locale: account %s, error %s", tg_user, e)
                locale = Locale("en")
            self._account = Account(
                id=tg_user.id,
                login=tg_user.username,
                locale=locale,
                _=tg_user,
            )
        return self._account

    @property
    def user(self) -> User:
        """The app user which initiated an update."""
        if not hasattr(self, "_user"):
            self._user = get_user(login=self.account.login)
        return self._user

    @property
    def locale(self) -> Locale:
        """Locale to use for the interface."""
        if user_language_code := self.user.get_option("locale"):
            return Locale.parse(user_language_code)
        elif account_locale := self.account.locale:
            return account_locale
        else:
            return Locale("en")

    @property
    def chat(self) -> Optional[Chat]:
        if hasattr(self, "_chat"):
            return self._chat
        logger.debug("Populating context chat.")
        tg_chat = self._update.effective_chat
        self._chat = Chat(id=tg_chat.id, _=tg_chat)
        return self._chat

    @property
    def message(self) -> Optional[Message]:
        """The message the **user** sent."""
        if hasattr(self, "_message"):
            return self._message

        logger.debug("Populating context message.")
        # ... user sent a message
        if hasattr(self._update, "message") and (
            tg_message := self._update.message
        ):
            logger.debug("Using the user message.")
        # ... user reacted to their own message
        elif (
            hasattr(self._update, "message_reaction")
            and (tg_message := self._update.message_reaction)
            and (tg_message.from_user.id == self.account.id)
        ):
            logger.debug("Using the message the user reacted on.")
        else:
            tg_message = None

        if tg_message:
            self._message = Message(
                id=tg_message.message_id,
                chat_id=tg_message.chat.id,
                user_id=tg_message.from_user.id,
                text=tg_message.text,
                _=tg_message,
            )
            # Looking for parent message
            self._message.parent = self.bot_message
        else:
            logger.debug("Couldn't find the message.")
            self._message = None

        return self._message

    @property
    def bot_message(self) -> Optional[Message]:
        """The last message that the **bot** sent."""
        if hasattr(self, "_bot_message"):
            return self._bot_message

        logger.debug("Populating bot message.")
        # Looking for parent message
        message = None
        # ... global on-reply is active
        if self.context(self.chat).get("_on_reply") and (
            message := self.context(self.chat).get("_on_reply_message")
        ):
            logger.debug("Using global reply-to message.")
        else:
            # ... user replies directly to some message
            if (
                hasattr(self._update, "message")
                and hasattr(self._update.message, "reply_to_message")
                and (tg_message := self._update.message.reply_to_message)
            ):
                logger.debug(
                    "Found the reply-to message, "
                    "populating the parent from it."
                )
            # ... user presses a button on an inline keyboard
            elif (
                hasattr(self._update, "callback_query")
                and hasattr(self._update.callback_query, "message")
                and (tg_message := self._update.callback_query.message)
            ):
                logger.debug("Using the callback message.")
            # ... user reacts on a bot's message
            elif (
                hasattr(self._update, "message_reaction")
                and (tg_message := self._update.message_reaction)
                and (tg_message.from_user.id != self.account.id)
            ):
                logger.debug("Using the message the user reacted on.")
            else:
                tg_message = None

            if tg_message:
                message = Message(
                    id=tg_message.message_id,
                    chat_id=tg_message.chat.id,
                    user_id=tg_message.from_user.id,
                    text=tg_message.text,
                    _=tg_message,
                )
        self._bot_message = message
        return self._bot_message

    @property
    def conversation(self) -> Optional[Conversation]:
        if hasattr(self, "_conversation"):
            return self._conversation

        conv = None
        # If the message is ascribed to a conversation, return it.
        if self.message and (
            id := self.context(self.message).get("_conversation")
        ):
            conv = Conversation(id)
        # Otherwise, check its parent message.
        elif self.bot_message and (
            id := self.context(self.bot_message).get("_conversation")
        ):
            conv = Conversation(id)

        self._conversation = conv
        return self._conversation

    @conversation.setter
    def conversation(self, value):
        self._conversation = value

    def context(
        self, obj: Union[Message, Chat, Account, Conversation]
    ) -> Dict:
        """
        All this is from current user perspective. Multiple users
        can have different contexts on the same messages, chats and
        other users.

        Message: message context;
        Chat: chat context;
        User: user context, including a context of one user on another one.
        """
        if isinstance(obj, Message):
            # Message context is stored in chats telegram context
            store = self._context.chat_data
            key = "_messages"
        elif isinstance(obj, Conversation):
            # Conversations reside in chats
            store = self._context.chat_data
            key = "_conversations"
        elif isinstance(obj, Chat):
            # Message context is stored in users telegram context
            store = self._context.user_data
            key = "_chats"
        elif isinstance(obj, Account):
            # Users context is stored in users telegram context
            store = self._context.user_data
            key = "_users"
        else:
            raise TypeError(f"Unsupported type: {type(obj)}.")

        # ... create the context storage if missing
        if key not in store:
            store[key]: Dict[int, Dict] = {}
        ctx = store[key]

        # ... create the dict for the given object if missing
        if obj.id not in ctx:
            ctx[obj.id]: Dict = {}

        return ctx[obj.id]

    async def _send_message(
        self,
        update: Update,
        context: CallbackContext,
        text: str,
        markup=None,
        image: Optional[str] = None,
        new: bool = False,
        reply_to: Optional[Union[PTBMessage, bool]] = None,
    ):
        """Send or update a message, with or without an image."""
        if self.parse_mode == ParseMode.MARKDOWN_V2:
            text = _escape_markdown_v2(text)

        if image and not self.config.IMAGE["enable"]:
            logger.info(
                "Images are disabled in config, sending message without image."
            )
            image = None  # Force no image if disabled

        can_edit = update.callback_query is not None and not new

        if can_edit:
            # Editing an existing message
            message = update.callback_query.message
            if image:
                try:
                    await message.edit_media(
                        media=InputMediaPhoto(
                            media=open(image, "rb"),
                            caption=text,
                            parse_mode=self.parse_mode,
                        ),
                        reply_markup=markup,
                    )
                except (
                    Exception
                ) as e:  # If image is the same, telegram might raise an error.
                    # Try editing caption instead.
                    logger.warning(
                        f"Failed to edit media (possibly same image): {e}. Trying to edit caption."
                    )
                    await message.edit_caption(
                        caption=text,
                        parse_mode=self.parse_mode,
                        reply_markup=markup,
                    )
            else:
                # If there was an image before, and now we send without an image,
                # we must edit_message_text, not edit_caption.
                # However, if there was no image, edit_caption would fail.
                # The safest is to try edit_message_text, and if it fails (e.g. was photo),
                # then try to edit_caption (to remove image, we'd need to send new message).
                # For simplicity, if no image now, assume we're editing text part or sending text only.
                # This might require deleting the old message and sending a new one if media type changes from photo to text.
                # For now, let's assume we can edit the text or caption.
                try:
                    await message.edit_text(  # Handles case where previous message was text
                        text=text,
                        reply_markup=markup,
                        parse_mode=self.parse_mode,
                    )
                except (
                    Exception
                ):  # Fallback to edit_caption if edit_text fails (e.g. previous was photo)
                    await message.edit_caption(
                        caption=text,
                        parse_mode=self.parse_mode,
                        reply_markup=markup,
                    )
        else:
            # Sending a new message
            effective_reply_to_message_id = None
            if isinstance(reply_to, PTBMessage):
                effective_reply_to_message_id = reply_to.message_id
            elif type(reply_to) is bool and reply_to and update.message:
                effective_reply_to_message_id = update.message.message_id

            if image:
                message = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=open(image, "rb"),
                    caption=text,
                    reply_markup=markup,
                    parse_mode=self.parse_mode,
                    reply_to_message_id=effective_reply_to_message_id,
                )
            else:
                message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    reply_markup=markup,
                    parse_mode=self.parse_mode,
                    reply_to_message_id=effective_reply_to_message_id,
                )
        return message

    async def _make_button(self, button: Button) -> InlineKeyboardButton:
        if isinstance(button.text, TranslatableString):
            text = await resolve(button.text, self.locale)
        else:
            text = str(button.text)
        return InlineKeyboardButton(
            text, callback_data=encode(button.callback)
        )

    async def _make_keyboard(self, keyboard: Keyboard) -> InlineKeyboardMarkup:
        buttons = [
            [await self._make_button(b) for b in row]
            for row in keyboard.buttons
        ]
        return InlineKeyboardMarkup(buttons)

    async def send_message(
        self,
        text: Union[str, TranslatableString],
        markup: Optional[Keyboard] = None,
        image: Optional[str] = None,
        new: bool = False,
        reply_to: Optional[Union[Message, bool]] = None,
        on_reply: Optional[Signal] = None,
        on_reaction: Optional[Dict[Emoji, Union[Signal, List[Signal]]]] = None,
        on_command: Optional[Dict[str, Union[Signal, List[Signal]]]] = None,
        context: Optional[Dict] = None,
    ):
        if on_reply:
            # set global on-reply flag — it will trigger from the next message
            # ?? Why here and not when the message is sent?
            self.context(self.chat)["_on_reply"] = on_reply
        else:
            # remove the global flag as quick as possible
            self.context(self.chat)["_on_reply"] = None
        if isinstance(text, TranslatableString):
            text = await resolve(text, self.locale)
        tg_message = await self._send_message(
            self._update,
            self._context,
            text,
            image=image,
            markup=await self._make_keyboard(markup) if markup else None,
            new=new,
            reply_to=reply_to._ if isinstance(reply_to, Message) else reply_to,
        )
        message = Message(
            id=tg_message.message_id,
            chat_id=tg_message.chat.id,
            user_id=None,
            text=tg_message.text,
            parent=tg_message.reply_to_message,
            _=tg_message,
        )
        if self.conversation:
            logger.info(
                "Conversation found: %s, context: %s",
                self.conversation,
                self.context(self.conversation),
            )
            self.context(message)["_conversation"] = self.conversation.id
        if context:
            self.context(message).update(context)
        if on_reply:
            logger.info("Setting on reply event for message id=%s", message.id)
            self.context(message)["_on_reply"] = on_reply
            self.context(self.chat)["_on_reply_message"] = message
        if on_reaction:
            logger.debug(
                "Setting reaction handlers for message id=%s", message.id
            )
            if "_on_reaction" not in self.context(message):
                self.context(message)["_on_reaction"] = {}
            self.context(message)["_on_reaction"].update(on_reaction)
        if on_command:
            logger.debug(
                "Setting command handlers for message id=%s", message.id
            )
            self.context(message)["_on_command"] = on_command
        return message
