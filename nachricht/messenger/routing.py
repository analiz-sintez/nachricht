import re
import logging
import hashlib
from dataclasses import dataclass
from functools import wraps
from inspect import signature, Signature, Parameter
from typing import (
    Optional,
    Callable,
    Union,
    List,
    Dict,
    Any,
    TypeAlias,
    TypeVar,
    ParamSpec,
    Concatenate,
)

from .context import Context, Message, Emoji
from ..auth import get_user, User
from ..i18n import TranslatableString, resolve
from ..bus import check_conditions, Conditions

P = ParamSpec("P")
R = TypeVar("R")

UserInjector: TypeAlias = Callable[
    [Callable[Concatenate[User, P], R]], Callable[Concatenate[Context, P], R]
]


logger = logging.getLogger(__name__)


@dataclass
class Handler:
    """
    A generic peg: a mapping from the messenger event to the reaction (a function)
    that should happen (be invoked) in the bot app in response to that event.
    """

    fn: Callable
    conditions: Optional[Conditions]


@dataclass
class Command(Handler):
    """A generic definition for a command handler."""

    name: str
    args: list[str]
    description: str


@dataclass
class MessageHandler(Handler):
    """A generic definition for a message handler."""

    pattern: Union[str, re.Pattern, Callable]


@dataclass
class ReactionHandler(Handler):
    """A generic definition for a reaction handler."""

    emojis: list[Emoji]


@dataclass
class CallbackHandler(Handler):
    """A generic definition for a callback query handler."""

    pattern: str


class Router:
    """
    This class implements Flask-like routing decorators for a bot.

    It is messenger-agnostic and gathers handlers in a declarative form,
    which can then be attached to a specific messenger implementation.

    Router is a bootstrap-time entity, not the runtime one. After it has
    attached all the handlers to a chat adapter, it leaves the show.
    """

    def __init__(self, config: Optional[object] = None):
        self.config = config
        self.command_handlers: list[Command] = []
        self.callback_query_handlers: list[CallbackHandler] = []
        self.reaction_handlers: list[ReactionHandler] = []
        self.message_handlers: list[MessageHandler] = []

    def command(
        self,
        name: str,
        args: list[str] = [],
        description: Optional[Union[str, TranslatableString]] = None,
        conditions: Optional[Conditions] = None,
    ) -> Callable:
        """
        A decorator to register a command handler.
        """

        def decorator(fn: Callable) -> Callable:
            logger.debug(f"Registering command: /{name}: {description}")
            handler_def = Command(
                fn=fn,
                name=name,
                args=args,
                description=description,
                conditions=conditions,
            )
            self.command_handlers.append(handler_def)
            return fn

        return decorator

    def callback_query(self, pattern: str) -> Callable:
        """
        A decorator to register a callback query handler based on a regex pattern.
        """

        def decorator(fn: Callable) -> Callable:
            logger.debug(f"Registering callback query with pattern: {pattern}")
            handler_def = CallbackHandler(
                fn=fn, pattern=pattern, conditions=None
            )
            self.callback_query_handlers.append(handler_def)
            return fn

        return decorator

    def reaction(
        self,
        emojis: List[Emoji] = [],
        conditions: Optional[Conditions] = None,
    ) -> Callable:
        """
        A decorator to register a reaction handler based on reactions list.
        """

        def decorator(fn: Callable) -> Callable:
            logger.debug(f"Registering reaction handler for emojis: {emojis}")
            handler_def = ReactionHandler(
                fn=fn, emojis=emojis, conditions=conditions
            )
            self.reaction_handlers.append(handler_def)
            return fn

        return decorator

    def message(
        self,
        pattern: Union[str, re.Pattern, Callable],
        conditions: Optional[Conditions] = None,
    ) -> Callable:
        """
        A decorator to register a message handler based on a regex pattern or a filter function.
        """

        def decorator(fn: Callable) -> Callable:
            logger.debug(f"Registering message with pattern: {pattern}")
            handler_def = MessageHandler(
                fn=fn, pattern=pattern, conditions=conditions
            )
            self.message_handlers.append(handler_def)
            logger.info("Message handler added for %s.", fn.__name__)
            return fn

        return decorator

    def help(self, help_text: Union[str, TranslatableString]):
        """
        Add a contextual help message for the haldner.
        Requires the handler to return the message.
        """

        help_text_str = str(help_text)

        def decorator(fn: Callable) -> Callable:
            """
            Mark the message sent by the wrapped fn so that the help system
            knows what to show.
            """
            sig = signature(fn)
            if "ctx" not in sig.parameters:
                logger.error(
                    f"Can't declare a helper for function {fn}: it must have a `ctx: Context` argument."
                )
                return fn

            logger.debug(
                f"Registering help message: '{help_text_str}' for the function {fn}."
            )
            help_hash = hashlib.md5(help_text_str.encode()).hexdigest()

            async def helper_fn(
                ctx, reply_to: Optional[Message] = None, **kwargs
            ):
                return await ctx.send_message(help_text, reply_to=reply_to)

            self.command("help", conditions={"_help": help_hash})(helper_fn)
            # thinking face and exploding head emojis
            # TODO move it somewhere to the config
            self.reaction([Emoji.THINKING], conditions={"_help": help_hash})(
                helper_fn
            )

            @wraps(fn)
            async def patched_fn(**kwargs):
                ctx = kwargs["ctx"]
                if not (message := await fn(**kwargs)):
                    logger.warning(
                        f"The handler %s doesn't return the message, so the helper wouldn't work. Add `return await ctx.send_message(...) to fix that.`",
                        fn,
                    )
                    return
                ctx.context(message)["_help"] = help_hash
                return message

            return patched_fn

        return decorator

    def authorize(self, admin=False) -> UserInjector:
        def decorator(
            fn: Callable[Concatenate[User, P], R],
        ) -> Callable[Concatenate[Context, P], R]:
            """
            Get a user from telegram update object.
            The inner function should have `user: User` as the first argument,
            but it will not be propagated to the wrapped function (e.g. after
            this decorator, the outer fn will not have `user` arg. In other words,
            `authorize` injects this argument.)
            """
            sig = signature(fn)

            # We require update object, take user info from it,
            # and inject it into the decorated function, so that
            # it doesn't need to bother.
            # TODO config-based authentication.
            @wraps(fn)
            async def authorized(ctx: Context, **kwargs):
                if not (user := get_user(ctx.account.login)):
                    raise Exception("Unauthorized.")
                # Authorize the user.
                allowed_logins = self.config.AUTHENTICATION["allowed_logins"]
                if allowed_logins and user.login not in allowed_logins:
                    raise Exception("Not allowed.")
                if user.login in self.config.AUTHENTICATION["blocked_logins"]:
                    raise Exception("Blocked.")
                if admin:
                    admin_logins = self.config.AUTHENTICATION["admin_logins"]
                    if user.login not in admin_logins:
                        raise Exception("Only admins allowed.")
                # Inject a user into function.
                kwargs["ctx"] = ctx
                kwargs["user"] = user
                new_kwargs = {
                    p.name: kwargs[p.name]
                    for p in sig.parameters.values()
                    if p.name in kwargs
                }
                return await fn(**new_kwargs)

            # Assemble a new signature (bus counts on this info to decide
            # which params to inject)
            params = [p for p in sig.parameters.values()]
            if "ctx" not in {p.name for p in params}:
                params.append(
                    Parameter(
                        "ctx",
                        Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Context,
                    )
                )
            new_sig = Signature(params)
            authorized.__signature__ = new_sig

            logger.debug(f"Adding authorization check: {authorized.__name__}")
            return authorized

        return decorator
