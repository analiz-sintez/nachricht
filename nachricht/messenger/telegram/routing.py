import re
import logging
from functools import wraps
from inspect import getmodule
from typing import (
    Dict,
    Type,
    Callable,
    Optional,
    Any,
    List,
    get_type_hints,
    Optional,
    get_type_hints,
)

from telegram import BotCommand, Message as PTBMessage, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler as PTBCallbackQueryHandler,
    CommandHandler as PTBCommandHandler,
    MessageHandler as PTBMessageHandler,
    MessageReactionHandler as PTBReactionHandler,
    CallbackContext,
    filters,
)

from ...bus import (
    Bus,
    Signal,
    TerminalSignal,
    unoption,
    decode,
    make_regexp,
    get_bus,
)
from ..routing import (
    check_conditions,
    CallbackHandler,
    Command,
    MessageHandler,
    ReactionHandler,
    Router,
    Conditions,
)
from .context import TelegramContext
from .. import Message, Emoji

logger = logging.getLogger(__name__)


def _coerce(arg: str, hint):
    """Coerce a string argument to function type hint."""
    # Get the actual type.
    hint = unoption(hint)
    # Coerce arg to that if we can.
    if hint not in [int, float, str]:
        logger.debug(
            f"type({arg}) is {hint}, can't convert to that. "
            f"Passing as string."
        )
        return arg
    try:
        coerced = hint(arg)
    except (ValueError, TypeError):
        logger.warning(
            f"Could not coerce argument '{arg}' to {hint} "
            f"for command. Passing as string."
        )
        coerced = arg
    return coerced


def _wrap_fn_with_args(fn: Callable, router: Router) -> Callable:
    """
    A helper function to wrap the handler function
    and extract named groups from regex matches for its arguments, coercing types.
    """
    type_hints = get_type_hints(fn)

    @wraps(fn)
    async def wrapped(update: Update, context: TelegramContext, **kwargs):
        if context.matches:
            match = context.matches[0]
            if isinstance(match, re.Match):
                kwargs.update(match.groupdict())
            elif isinstance(match, dict):
                kwargs.update(match)

        for key, value in kwargs.items():
            if key in type_hints:
                kwargs[key] = _coerce(value, type_hints[key])

        logger.info(f"Calling {fn.__name__} with args: {kwargs}")
        ctx = TelegramContext(update, context, config=router.config)
        return await fn(ctx=ctx, **kwargs)

    return wrapped


def _wrap_command_fn(
    fn: Callable, arg_names: list[str], router: Router
) -> Callable:
    """
    A helper function to wrap a command handler, parsing and coercing
    positional arguments from the message.
    """
    type_hints = get_type_hints(fn)

    @wraps(fn)
    async def wrapped(update, context, **outer_kwargs):
        if len(arg_names) == 1:
            args = [update.message.text.split(" ", 1)[1]]
        elif len(arg_names) > 1:
            args = context.args if hasattr(context, "args") else []
        else:
            args = []
        arg_cnt = min(len(args), len(arg_names))
        for value, key in zip(args[:arg_cnt], arg_names[:arg_cnt]):
            if key in type_hints:
                outer_kwargs[key] = _coerce(value, type_hints[key])
        kwargs = {
            key: outer_kwargs[key]
            for key in type_hints.keys()
            if key in outer_kwargs
        }

        logger.debug(f"Calling {fn.__name__} with args: {outer_kwargs}")
        ctx = TelegramContext(update, context, config=router.config)
        return await fn(ctx, **kwargs)

    return wrapped


def _create_command_handler(
    name: str, handlers: List[Command], router: Router
) -> PTBCommandHandler:
    """
    Creates a *single* telegram.CommandHandler for a bunch of
    CommandHandler dataclasses.
    They may have different conditions, e.g. on message context.

    """
    # TODO: this logic is too primitive. Maybe we should have
    # `is_final` property which terminates the search.
    # Or sort handlers based on conditions count, search from the ones with
    # many conditions first, and terminate the search if we found something.
    conditional_handlers = []
    conditionless_handlers = []
    for handler in handlers:
        if handler.conditions:
            conditional_handlers.append(handler)
        else:
            conditionless_handlers.append(handler)

    async def dispatch(update, context):
        ctx = TelegramContext(update, context, config=router.config)
        # Any user action cleans the global on_reply stash,
        # no matter consumed the signal in it or not.
        if signal := ctx.context(ctx.chat).get("_on_reply"):
            ctx.context(ctx.chat)["_on_reply"] = None
        # Get the message replied to.
        parent_ctx = None
        if parent := ctx.message.parent:
            parent_ctx = ctx.context(parent)

            # Check if a message should emit a signal on certain command.
            # (see Context.send_message on_command argument for details).
            if message_handlers := parent_ctx.get("_on_command"):
                if signals := message_handlers.get(name):
                    if bus := get_bus():
                        if isinstance(signals, Signal):
                            signals = [signals]
                        for signal in signals:
                            await bus.emit_and_wait(
                                signal, ctx=ctx, reply_to=parent
                            )
                    else:
                        logger.error(
                            "Can't send message command signals, the bus is not ready."
                        )
                    # Stop processing.
                    return

        found = False
        for handler in conditional_handlers:
            # Check the message context condition.
            if (
                match := check_conditions(handler.conditions, parent_ctx)
            ) is None:
                continue
            logger.info(f"Handler matched for command {name}: {match}.")
            found = True
            await handler.fn(update, context, reply_to=parent, **match)
        if found:
            return
        for handler in conditionless_handlers:
            logger.info(f"Calling conditionless handler for command {name}.")
            await handler.fn(update, context, reply_to=parent)

    return PTBCommandHandler(name, dispatch)


def _create_callback_query_handler(
    handler: CallbackHandler,
    router: Router,
) -> PTBCallbackQueryHandler:
    """Creates a telegram.ext.CallbackQueryHandler from a CallbackHandler dataclass."""
    wrapped_handler = _wrap_fn_with_args(handler.fn, router)

    @wraps(wrapped_handler)
    async def wrapped(
        update: Update, context: TelegramContext, *args, **kwargs
    ):
        ctx = TelegramContext(update, context, config=router.config)
        # Any user action cleans the global on_reply stash,
        # no matter consumed the signal in it or not.
        # BUG: This doesn't work for some reason. Maybe callbacks have different
        # contexts?
        if signal := ctx.context(ctx.chat).get("_on_reply"):
            logger.info(
                "Callback handler found global _on_reply, removing it."
            )
            ctx.context(ctx.chat)["_on_reply"] = None
        return await wrapped_handler(update, context, *args, **kwargs)

    return PTBCallbackQueryHandler(wrapped_handler, pattern=handler.pattern)


def _create_reaction_handlers(
    handlers: List[ReactionHandler],
    router: Router,
) -> PTBReactionHandler:
    """
    Creates a *single* telegram.ext.MessageReactionHandler for a bunch of
    ReactionHandler dataclasses.

    For now, only new reactions are handled. Telegram reports on reaction
    deletions but for simplicity we don't process them.
    """
    # Build a mapping of emojis to handlers
    emoji_map: Dict[Emoji, List[ReactionHandler]] = {}
    for handler in handlers:
        handler.fn = _wrap_fn_with_args(handler.fn, router=router)
        for emoji in handler.emojis:
            if emoji not in emoji_map:
                emoji_map[emoji] = []
            emoji_map[emoji].append(handler)

    async def dispatch(update: Update, context: TelegramContext):
        ctx = TelegramContext(update, context, config=router.config)
        # Any user action cleans the global on_reply stash,
        # no matter consumed the signal in it or not.
        if signal := ctx.context(ctx.chat).get("_on_reply"):
            ctx.context(ctx.chat)["_on_reply"] = None
        # Get the reply to message.
        tg_parent = update.message_reaction
        parent = Message(
            id=tg_parent.message_id,
            chat_id=tg_parent.chat.id,
            _=tg_parent,
        )
        # Check for new reactions.
        parent_ctx = ctx.context(parent)
        emoji: Optional[Emoji] = None
        if hasattr(tg_parent, "new_reaction"):
            reactions = tg_parent.new_reaction
            if len(reactions) == 1 and hasattr(reactions[0], "emoji"):
                emoji = Emoji.get(reactions[0].emoji)
            logger.info(f"Got emoji: {emoji}")
        # If no new reaction found, stop dispatching.
        if not emoji:
            return
        # Check if a message should emit a signal on certain reaction.
        # (see Context.send_message on_reaction argument for details).
        if message_handlers := parent_ctx.get("_on_reaction"):
            if bus := get_bus():
                signals = message_handlers.get(emoji, [])
                if isinstance(signals, Signal):
                    signals = [signals]
                for signal in signals:
                    await bus.emit_and_wait(signal, ctx=ctx, reply_to=parent)
            else:
                logger.error(
                    "Can't send message reaction signals, the bus is not ready."
                )
        # Check common handlers registered directly.
        for handler in emoji_map.get(emoji, []):
            # Check the message context condition.
            if (
                match := check_conditions(handler.conditions, parent_ctx)
            ) is None:
                continue
            # TODO this should not await, just shoot and forget
            logger.info(f"Handler matched for emoji {emoji}: {match}.")
            await handler.fn(
                update, context, emoji=emoji, reply_to=parent, **match
            )

    return PTBReactionHandler(dispatch)


def _create_message_handlers(
    message_handlers: List[MessageHandler],
    router: Router,
) -> PTBMessageHandler:
    """
    Combile all MessageHandlers and register them
    as onr telegram.ext.MessageHandler.
    """

    def find_named_groups(pat: re.Pattern, string: str) -> Optional[Dict]:
        """Return all named groups found in a string, or None if it doesn't match."""
        logger.debug("Matching string %s against regexp %s", string, pat)
        if not (match := pat.search(string)):
            return None
        return {key: match.group(key) for key in pat.groupindex.keys()}

    # Preprocess message handelrs:
    for handler in message_handlers:
        # ... wrap the function
        handler.fn = _wrap_fn_with_args(handler.fn, router)
        # ... prepare the pattern
        if isinstance(handler.pattern, str):
            handler.pattern = re.compile(handler.pattern)
        if not (
            callable(handler.pattern)
            or isinstance(handler.pattern, re.Pattern)
        ):
            raise ValueError("Pattern must be a regexp or a callable.")

    async def dispatch(update: Update, context: TelegramContext):
        ctx = TelegramContext(update, context, config=router.config)
        message = ctx.message
        logging.info("Dispatching message: id=%s", message.id)
        # Here we can do the trick: get the one-time reply-to message id
        # for the user and clear this id right after that.
        if signal := ctx.context(ctx.chat).get("_on_reply"):
            await get_bus().emit_and_wait(signal, ctx=ctx)
            if isinstance(signal, TerminalSignal):
                ctx.context(ctx.chat)["_on_reply"] = None
                return
        elif (parent_ctx := ctx.context(ctx.bot_message)) and (
            signal := parent_ctx.get("_on_reply")
        ):
            # Check if a message should emit a signal on reply.
            # (see Context.send_message on_reply argument for details).
            await get_bus().emit_and_wait(signal, ctx=ctx)
            if isinstance(signal, TerminalSignal):
                parent_ctx["_on_reply"] = None
                return
        # For each handler, check conditions and call if they are met.
        for handler in message_handlers:
            pattern_match = None
            if isinstance(handler.pattern, re.Pattern):
                pattern_match = find_named_groups(
                    handler.pattern, message.text
                )
            elif callable(handler.pattern):
                pattern_match = handler.pattern(message.text)
            if pattern_match is None:
                continue
            if (
                cond_match := check_conditions(
                    handler.conditions, ctx.context(ctx.bot_message)
                )
            ) is None:
                continue
            logger.info(f"Message handler matched: %s", handler.fn.__name__)
            result = await handler.fn(
                update, context, **pattern_match, **cond_match
            )
            ctx.context(ctx.chat)["_on_reply"] = None
            return result

    combined_filters = filters.TEXT & ~filters.COMMAND
    return PTBMessageHandler(combined_filters, dispatch)


def attach_router(router: Router, application: Application):
    """
    Attach the stored handlers from a generic Router to the Telegram application.
    """
    logger.info("Attaching handlers to the application.")

    # Process and add command handlers
    # For each command gather all registered handlers.
    command_map = {}
    for handler in router.command_handlers:
        if handler.name not in command_map:
            command_map[handler.name] = []
        handler.fn = _wrap_command_fn(handler.fn, handler.args, router)
        command_map[handler.name].append(handler)

    for command_name, handlers in command_map.items():
        handler = _create_command_handler(command_name, handlers, router)
        application.add_handler(handler)
        logger.debug(f"Command handler added for '/{command_name}'")

    # Process and add callback query handlers
    for callback_handler in router.callback_query_handlers:
        handler = _create_callback_query_handler(callback_handler, router)
        application.add_handler(handler)
        logger.debug(
            f"Callback query handler added for pattern: {callback_handler.pattern}"
        )

    # Process and add message handlers
    # register them all at once to avoid "only first matched is called" rule
    handler = _create_message_handlers(router.message_handlers, router)
    application.add_handler(handler)
    logger.debug(f"Message handlers added.")

    # Set all commands with their descriptions for the bot menu
    # TODO resolve translatable strings
    bot_commands = [
        BotCommand(cmd.name, str(cmd.description or cmd.name))
        for cmd in router.command_handlers
    ]

    async def set_commands(application: Application):
        await application.bot.set_my_commands(bot_commands)

    if bot_commands:
        application.post_init = set_commands
        logger.debug("Bot command descriptions set: %s", bot_commands)

    # Set up a reactions handler.
    # This is a special case. PTB doesn't support dispatching on emoji types,
    # so we register a single handler which does this dispatch.
    if router.reaction_handlers:
        application.add_handler(
            _create_reaction_handlers(router.reaction_handlers, router)
        )


def attach_bus(bus: Bus, application: Application):
    """
    Attach the signals from a Bus to the Telegram application.
    """

    def make_handler(signal_type: Type[Signal]) -> PTBCallbackQueryHandler:
        signal_name = signal_type.__name__

        async def decode_and_emit(update: Update, context: CallbackContext):
            data = update.callback_query.data
            logger.debug(f"Got callback: {data}, decoding as {signal_name}.")
            signal = decode(signal_type, data)
            if not signal:
                logger.warning(f"Decoding {signal_name} failed.")
                return
            ctx = TelegramContext(update, context, config=bus.config)
            await bus.emit_and_wait(signal, ctx=ctx)

        pattern = make_regexp(signal_type)
        logger.debug(f"Registering handler: {pattern} -> {signal_name}")
        handler = PTBCallbackQueryHandler(decode_and_emit, pattern=pattern)
        return handler

    bus.setup()

    logging.info("Bus: registering signal handlers.")
    for signal_type in bus.signals():
        module_name = getmodule(signal_type).__name__
        signal_name = signal_type.__name__
        logging.debug(
            f"Bus: registering a handler for {module_name}.{signal_name}."
        )
        application.add_handler(make_handler(signal_type))

    logging.info("Bus: all signals registered.")
