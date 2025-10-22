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

from nachricht.messenger.context import Context

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
    CallbackPeg,
    CommandPeg,
    MessagePeg,
    ReactionPeg,
    Router,
    Conditions,
)
from .context import TelegramContext
from .. import Message, Emoji

logger = logging.getLogger(__name__)


def _coerce(arg: str, hint):
    """
    Coerce a string argument to a function type hint.
    """
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


def _wrap_function(fn: Callable, router: Router) -> Callable:
    """
    Isolate the function from the PTB update and context objects:
    - fetch all the matched regexp named groups from the update object
      into the kwargs;
    - coerce the kwargs according to the function signature.
    """
    type_hints = get_type_hints(fn)

    @wraps(fn)
    async def wrapped(update: Update, context: CallbackContext, **kwargs):
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
        ctx = TelegramContext(
            router.app.bot, update, context, config=router.config
        )
        return await fn(ctx=ctx, **kwargs)

    return wrapped


def _wrap_command(
    fn: Callable, arg_names: list[str], router: Router
) -> Callable:
    """
    Isolate the function from the PTB update and context objects:
    - fetch the command positional arguments, if any, and append them
      to the kwargs;
    - coerce the kwargs according to the function signature.
    """
    type_hints = get_type_hints(fn)

    @wraps(fn)
    async def wrapped(
        update: Update, context: CallbackContext, **outer_kwargs
    ):
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
        ctx = TelegramContext(
            router.app.bot, update, context, config=router.config
        )
        return await fn(ctx, **kwargs)

    return wrapped


def _handle_global_on_reply(ctx: TelegramContext):
    """
    Global on-reply is a mode which allows to connect a user input message
    to a bot message, e.g. for editing items. It's a replacement for input
    fields which are missing in messengers.

    The state is global and thus should be cleared after any user action
    not connected to the current message.

    !! Hey, not every callback should clear this flag! Only the callback
    bound to a button on the message to which the reply goes! If I have two
    "widgets", and the latter asks me to input smth, I want to be able to
    freely check smth on the former one.
    """
    if signal := ctx.context(ctx.chat).get("_on_reply"):
        logging.critical(
            "Clearing the _on_reply state from chat %i",
            ctx.chat.id,
        )
        ctx.context(ctx.chat)["_on_reply"] = None
        return signal


def _create_command_handler(
    name: str, pegs: List[CommandPeg], router: Router
) -> PTBCommandHandler:
    """
    Create a *single* telegram.CommandHandler for a bunch of
    CommandHandler dataclasses. They may have different conditions,
    e.g. depend on message context.
    """
    # TODO: this logic is too primitive. Maybe we should have
    # `is_final` property which terminates the search.
    # Or sort handlers based on conditions count, search from the ones with
    # many conditions first, and terminate the search if we found something.
    conditional_pegs = []
    conditionless_pegs = []
    for peg in pegs:
        if peg.conditions:
            conditional_pegs.append(peg)
        else:
            conditionless_pegs.append(peg)

    async def dispatch(update: Update, context: CallbackContext):
        ctx = TelegramContext(
            router.app.bot, update, context, config=router.config
        )
        # Any user action cleans the global on_reply stash,
        # no matter consumed the signal in it or not.
        signal = _handle_global_on_reply(ctx)
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
        for peg in conditional_pegs:
            # Check the message context condition.
            if (match := check_conditions(peg.conditions, parent_ctx)) is None:
                continue
            logger.info(f"Handler matched for command {name}: {match}.")
            found = True
            await peg.fn(update, context, reply_to=parent, **match)
        if found:
            return
        for peg in conditionless_pegs:
            logger.info(f"Calling conditionless handler for command {name}.")
            await peg.fn(update, context, reply_to=parent)

    return PTBCommandHandler(name, dispatch)


def _create_reaction_handler(
    pegs: List[ReactionPeg],
    router: Router,
) -> PTBReactionHandler:
    """
    Creates a *single* telegram.ext.MessageReactionHandler for a bunch of
    ReactionHandler dataclasses.

    For now, only new reactions are handled. Telegram reports on reaction
    deletions but for simplicity we don't process them.
    """
    # Build a mapping of emojis to handlers
    emoji_map: Dict[Emoji, List[ReactionPeg]] = {}
    for peg in pegs:
        peg.fn = _wrap_function(peg.fn, router=router)
        for emoji in peg.emojis:
            if emoji not in emoji_map:
                emoji_map[emoji] = []
            emoji_map[emoji].append(peg)

    async def dispatch(update: Update, context: CallbackContext):
        ctx = TelegramContext(
            router.app.bot, update, context, config=router.config
        )
        # Any user action cleans the global on_reply stash,
        # no matter consumed the signal in it or not.
        signal = _handle_global_on_reply(ctx)
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
        for peg in emoji_map.get(emoji, []):
            # Check the message context condition.
            if (match := check_conditions(peg.conditions, parent_ctx)) is None:
                continue
            # TODO this should not await, just shoot and forget
            logger.info(f"Handler matched for emoji {emoji}: {match}.")
            await peg.fn(
                update, context, emoji=emoji, reply_to=parent, **match
            )

    return PTBReactionHandler(dispatch)


def _create_message_handler(
    pegs: List[MessagePeg],
    router: Router,
) -> PTBMessageHandler:
    """
    Combile all MessagePegs and register them as a single MessageHandler.
    """

    def find_named_groups(pat: re.Pattern, string: str) -> Optional[Dict]:
        """Return all named groups found in a string, or None if it doesn't match."""
        logger.debug("Matching string %s against regexp %s", string, pat)
        if not (match := pat.search(string)):
            return None
        return {key: match.group(key) for key in pat.groupindex.keys()}

    # Preprocess message pegs:
    for peg in pegs:
        # ... wrap the function
        peg.fn = _wrap_function(peg.fn, router)
        # ... prepare the pattern
        if isinstance(peg.pattern, str):
            peg.pattern = re.compile(peg.pattern)
        if not (callable(peg.pattern) or isinstance(peg.pattern, re.Pattern)):
            raise ValueError("Pattern must be a regexp or a callable.")

    async def dispatch(update: Update, context: CallbackContext):
        ctx = TelegramContext(
            router.app.bot, update, context, config=router.config
        )
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
        # For each peg, check conditions and call if they are met.
        for peg in pegs:
            pattern_match = None
            if isinstance(peg.pattern, re.Pattern):
                pattern_match = find_named_groups(peg.pattern, message.text)
            elif callable(peg.pattern):
                pattern_match = peg.pattern(message.text)
            if pattern_match is None:
                continue
            if (
                cond_match := check_conditions(
                    peg.conditions, ctx.context(ctx.bot_message)
                )
            ) is None:
                continue
            logger.info(f"Message handler matched: %s", peg.fn.__name__)
            result = await peg.fn(
                update, context, **pattern_match, **cond_match
            )
            ctx.context(ctx.chat)["_on_reply"] = None
            return result

    combined_filters = filters.TEXT & ~filters.COMMAND
    return PTBMessageHandler(combined_filters, dispatch)


def _create_callback_query_handler(
    peg: CallbackPeg,
    router: Router,
) -> PTBCallbackQueryHandler:
    """Creates a CallbackQueryHandler from a CallbackPeg dataclass."""
    fn = _wrap_function(peg.fn, router)

    @wraps(fn)
    async def wrapped(
        update: Update, context: CallbackContext, *args, **kwargs
    ):
        ctx = TelegramContext(
            router.app.bot, update, context, config=router.config
        )
        # Any user action cleans the global on_reply stash,
        # no matter consumed the signal in it or not.
        _handle_global_on_reply(ctx)
        return await fn(update, context, *args, **kwargs)

    return PTBCallbackQueryHandler(wrapped, pattern=peg.pattern)


def attach_bus(bus: Bus, router: Router):
    """
    Attach the signals from a Bus to the Telegram application.
    """

    bus.setup()

    logging.info("Bus: registering signal handlers.")

    # def make_handler(signal_type: Type[Signal]) -> PTBCallbackQueryHandler:
    #     signal_name = signal_type.__name__

    #     async def decode_and_emit(update: Update, context: CallbackContext):
    #         data = update.callback_query.data
    #         logger.debug(f"Got callback: {data}, decoding as {signal_name}.")
    #         signal = decode(signal_type, data)
    #         if not signal:
    #             logger.warning(f"Decoding {signal_name} failed.")
    #             return
    #         await bus.emit_and_wait(signal, ctx=ctx)

    #     pattern = make_regexp(signal_type)
    #     logger.debug(f"Registering handler: {pattern} -> {signal_name}")
    #     handler = PTBCallbackQueryHandler(decode_and_emit, pattern=pattern)
    # return handler

    def add_peg(signal_type: Type[Signal]) -> None:
        module_name = getmodule(signal_type).__name__
        signal_name = signal_type.__name__
        logging.debug(
            f"Bus: registering a handler for {module_name}.{signal_name}."
        )

        pattern = make_regexp(signal_type)

        @router.callback_query(pattern)
        async def decode_emit_and_wait(ctx: Context, **callback_data):
            data = ctx._update.callback_query.data
            logger.debug(f"Got callback: {data}, decoding as {signal_name}.")
            signal = decode(signal_type, data)
            if not signal:
                logger.warning(f"Decoding {signal_name} failed.")
                return
            await bus.emit_and_wait(signal, ctx=ctx)

    for signal_type in bus.signals():
        add_peg(signal_type)

    logging.info("Bus: all signals pegged to the messenger via router.")


def attach_router(router: Router, application: Application):
    """
    Attach the stored handlers from a generic Router to the Telegram application.
    """
    logger.info("Attaching handlers to the application.")
    router.app = application

    # Process and add handlers

    # Commands:
    # ... for each command gather all registered handlers.
    command_map = {}
    for peg in router.command_pegs:
        if peg.name not in command_map:
            command_map[peg.name] = []
        peg.fn = _wrap_command(peg.fn, peg.args, router)
        command_map[peg.name].append(peg)
    # ... and register them as a single Telegram handler
    for command_name, pegs in command_map.items():
        handler = _create_command_handler(command_name, pegs, router)
        application.add_handler(handler)
        logger.debug(f"Command handler added for '/{command_name}'")

    # ... set all commands with their descriptions for the bot menu
    # ... TODO resolve translatable strings
    bot_commands = [
        BotCommand(cmd.name, str(cmd.description or cmd.name))
        for cmd in router.command_pegs
    ]

    async def set_commands(application: Application):
        await application.bot.set_my_commands(bot_commands)

    if bot_commands:
        application.post_init = set_commands
        logger.debug("Bot command descriptions set: %s", bot_commands)

    # Messages:
    # ... register them all at once to avoid "only first matched is called" rule
    handler = _create_message_handler(router.message_pegs, router)
    application.add_handler(handler)
    logger.debug(f"Message handlers added.")

    # Reactions:
    # ... this is a special case. PTB doesn't support dispatching on emoji types,
    #     so we register a single handler which does this dispatch.
    if router.reaction_pegs:
        application.add_handler(
            _create_reaction_handler(router.reaction_pegs, router)
        )

    # Callbacks:
    # ... TODO This is RUDIMENTARY as ALL callbacks should be processed by the bus!
    #     Maybe the router doesn't need callback_query_handlers property at all?
    for peg in router.callback_pegs:
        handler = _create_callback_query_handler(peg, router)
        application.add_handler(handler)
        logger.debug(
            f"Callback query handler added for pattern: {peg.pattern}"
        )
