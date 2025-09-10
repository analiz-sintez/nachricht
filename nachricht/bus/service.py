import re
import asyncio
import logging
from inspect import signature, getmodule
from dataclasses import dataclass, asdict, astuple, fields
from enum import Enum
from typing import (
    Callable,
    Type,
    List,
    Dict,
    TypeAlias,
    Any,
    get_type_hints,
    Optional,
    get_origin,
    get_args,
    Union,
)
from inspect import signature

logger = logging.getLogger(__name__)


def is_optional(hint: type) -> bool:
    origin = get_origin(hint)
    args = get_args(hint)
    if (
        origin == Union
        and len(args) == 2
        and any([typ == type(None) for typ in args])
    ):
        return True
    else:
        return False


def unoption(hint: type) -> type:
    """Remove type hint modifiers as Unions and Optionals."""
    if is_optional(hint):
        types = [typ for typ in get_args(hint) if typ != type(None)]
        hint = types[0]
    return hint


Conditions: TypeAlias = Dict[str, Union[str, int]]


def check_conditions(
    conditions: Optional[Conditions],
    *contexts: Dict,
) -> Optional[Dict]:
    """
    Check handler conditions against given message context.

    Conditions list is a list of exact values which are matched against the
    values found in the message context. If any of the conditions is missing
    in the message context, the match has failed.

    All the condition values are passed to the handler as keyword arguments.

    TODO examples
    """
    # If no conditins are set, consider they met.
    if not conditions:
        return {}
    # If there are conditions but no context, consider them failed.
    if len(contexts) == 0 or contexts[-1] is None:
        return None
    # Add extra contexts if provided, with the descending priority
    # (the first context gets the highest priority, the last one gets the lowest).
    context = dict(contexts[-1])
    # ... traverse contexts in the reversed order,
    #     but skip the last one as we've already took it
    for more_context in contexts[:-1][::-1]:
        context.update(more_context)
    match = {}
    for condition, value in conditions.items():
        if condition not in context:
            return None
        if value is not Any and context[condition] != value:
            return None
        match[condition] = context[condition]
    return match


@dataclass
class Signal:
    pass


@dataclass
class TerminalSignal(Signal):
    pass


@dataclass
class DeferredConnection:
    signal_name: str
    slot: Callable
    conditions: Conditions


@dataclass
class Plug:
    slot: Callable
    conditions: Conditions


class Bus:
    def __init__(
        self,
        config: Optional[object] = None,
        saving_backend: Optional[
            Callable[[Signal, list[Callable]], None]
        ] = None,
    ):
        self._plugs: Dict[Type[Signal], List[Plug]] = dict()
        self._signal_types: Dict[str, Type[Signal]] = {}
        self._deferred_connections: List[DeferredConnection] = []
        self._save_signal = saving_backend
        self.config = config

    def save_signal(self, signal):
        if not self._save_signal:
            return
        plugs = self._plugs.get(type(signal), [])
        self._save_signal(signal, [p.slot for p in plugs])

    @classmethod
    def signals(cls, signal_type: Type[Signal] = Signal):
        """Recursively find all descendant classes."""
        descendants = set()
        subclasses = signal_type.__subclasses__()
        for sub in subclasses:
            descendants.add(sub)
            descendants.update(cls.signals(sub))
        return descendants

    def discover_signals(self):
        """
        Finds all defined Signal subclasses and registers them.
        This is necessary to be able to create signals by name
        even if they don't have any handlers connected yet.
        """
        logger.debug("Discovering all signal types...")
        for signal_type in self.signals():
            self.register(signal_type)
        logger.debug("Signal discovery complete.")

    def resolve_deferred_connections(self):
        """Connect all slots that were deferred."""
        if not self._deferred_connections:
            return

        logger.debug(
            f"Resolving {len(self._deferred_connections)} deferred connections..."
        )
        for conn in self._deferred_connections:
            signal_type = self.get_signal_type(conn.signal_name)
            if not signal_type:
                logger.error(
                    f"Cannot resolve deferred connection for slot '{conn.slot.__name__}' "
                    f"to signal '{conn.signal_name}': signal type not found."
                )
                continue
            self.connect(signal_type, conn.slot, conn.conditions)

        resolved_count = len(self._deferred_connections)
        self._deferred_connections = []
        logger.debug(f"Resolved {resolved_count} connections.")

    def setup(self):
        """
        Should be called once at application startup after all modules
        containing signals and handlers have been imported.

        This method discovers all signal types and connects handlers
        that were declared using a string name (deferred connections).
        """
        logger.info(
            "Setting up Bus: discovering signals and resolving connections."
        )
        self.discover_signals()
        self.resolve_deferred_connections()
        logger.info("Bus setup complete.")

    def register(self, signal_type: Type[Signal]):
        """Register a signal type so it can be referenced by name."""
        if not issubclass(signal_type, Signal):
            raise TypeError(
                "You should inherit your signals from Signal class."
                " It allows to track all the signals tree of the application."
            )

        name = signal_type.__name__
        if (
            name in self._signal_types
            and self._signal_types[name] is not signal_type
        ):
            existing = self._signal_types[name]
            logger.warning(
                f"Duplicate signal name '{name}'. "
                f"Existing: {getmodule(existing).__name__}.{existing.__name__}, "
                f"New: {getmodule(signal_type).__name__}.{name}. Overwriting."
            )
        self._signal_types[name] = signal_type

        if signal_type not in self._plugs:
            self._plugs[signal_type] = []
            logger.info(f"Registered signal type: {name}")

    def get_signal_type(self, name: str) -> Optional[Type[Signal]]:
        """Find a registered signal type by name."""
        return self._signal_types.get(name)

    def signal(self, name: str, *args, **kwargs) -> Signal:
        """
        Create a signal instance by its name and arguments.
        This allows emitting signals without direct import of the signal class,
        preventing circular dependencies.
        """
        signal_type = self.get_signal_type(name)
        if not signal_type:
            all_known = ", ".join(sorted(self._signal_types.keys()))
            raise ValueError(
                f"Unknown signal type: '{name}'. Known signals: {all_known or 'None'}"
            )
        try:
            return signal_type(*args, **kwargs)
        except TypeError as e:
            raise TypeError(
                f"Error creating signal '{name}' with args={args} kwargs={kwargs}: {e}"
            ) from e

    def on(
        self,
        signal_type_or_name: Union[Type[Signal], str],
        conditions: Conditions = {},
    ):
        """Make a decorator which connects a signal to any slot."""

        def _wrapper(slot: Callable) -> Callable:
            if isinstance(signal_type_or_name, str):
                deferred = DeferredConnection(
                    signal_type_or_name, slot, conditions
                )
                self._deferred_connections.append(deferred)
                logger.debug(
                    f"Deferred connection of {slot.__name__} to signal '{signal_type_or_name}'"
                )
            else:
                self.connect(signal_type_or_name, slot, conditions)
            return slot

        return _wrapper

    def connect(
        self,
        signal_type: Type[Signal],
        slot: Callable,
        conditions: Conditions = {},
    ):
        """
        Connect a signal to a slot: the slot will be called each time
        the signal is emitted, with signal parameters.
        """
        self._ensure_slot_parameter_types(signal_type, slot)
        # Remember the connection
        self.register(signal_type)
        plug = Plug(slot, conditions)
        if plug not in self._plugs[signal_type]:
            self._plugs[signal_type].append(plug)

    def _ensure_slot_parameter_types(
        self, signal_type: Type[Signal], slot: Callable
    ):
        """Check if the slot's parameter types match the signal's attribute types."""
        slot_sig = signature(slot)
        signal_hints = get_type_hints(signal_type)

        for param in slot_sig.parameters.values():
            if param.name in signal_hints:
                slot_param_type = unoption(param.annotation)
                signal_param_type = unoption(signal_hints[param.name])
                if slot_param_type != signal_param_type:
                    logger.warning(
                        f"Slot parameter '{param.name}' "
                        f"expects type {slot_param_type}, "
                        f"but found {signal_param_type} "
                        f"in signal '{signal_type.__name__}'"
                    )

    def _handle_task_result(self, task: asyncio.Task) -> None:
        """Callback to log exceptions from fire-and-forget tasks."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass  # Not an error
        except Exception as e:
            logging.error(f"Exception in background task: {e}", exc_info=True)

    def _dispatch_signal_to_slots(self, signal, **kwargs):
        signal_type = type(signal)
        signal_dict = asdict(signal)

        tasks = []
        if signal_type not in self._plugs:
            return tasks

        for plug in self._plugs[signal_type]:
            # No conditions means conditions are passed.
            # Otherwise check them agains the query context.
            if conditions := plug.conditions:
                logger.debug("Checking plug conditions: %s", conditions)
                # ??? get all the contexts from the args provided
                # TERRIBLE LEAK FROM THE CONTEXT LAYER
                if not (ctx := kwargs.get("ctx")):
                    continue
                contexts = []
                if ctx.message:
                    c = ctx.context(ctx.message)
                    logger.debug("Adding message context: %s", c)
                    contexts.append(c)
                if ctx.conversation:
                    c = ctx.context(ctx.conversation)
                    logger.debug("Adding conversation context: %s", c)
                    contexts.append(c)
                if ctx.chat:
                    c = ctx.context(ctx.chat)
                    logger.debug("Adding chat context: %s", c)
                    contexts.append(c)
                if ctx.account:
                    c = ctx.context(ctx.account)
                    logger.debug("Adding account context: %s", c)
                    contexts.append(c)
                if (match := check_conditions(conditions, *contexts)) is None:
                    continue
            else:
                match = {}

            slot = plug.slot
            slot_signature = signature(slot)
            relevant_args = {}

            relevant_args.update(match)
            for param in slot_signature.parameters.values():
                if param.name in signal_dict:
                    relevant_args[param.name] = signal_dict[param.name]
                elif param.name in kwargs:
                    relevant_args[param.name] = kwargs[param.name]

            tasks.append(asyncio.create_task(slot(**relevant_args)))

        return tasks

    def emit(self, signal: Signal, **kwargs) -> List[asyncio.Task]:
        """
        Fire-and-forget: Schedules slots and returns immediately.
        Exceptions in slots will be logged, not raised.
        """
        self.save_signal(signal)
        module_name = getmodule(signal).__name__
        logger.info(f"SIGNAL (fire-and-forget): {module_name}.{signal}")
        tasks = self._dispatch_signal_to_slots(signal, **kwargs)
        for task in tasks:
            task.add_done_callback(self._handle_task_result)
        return tasks

    async def emit_and_wait(self, signal: Signal, **kwargs) -> List:
        """
        Schedules slots and waits for them all to complete.
        Raises the first exception encountered in a slot.
        """
        self.save_signal(signal)
        module_name = getmodule(signal).__name__
        logger.info(f"SIGNAL (with waiting): {module_name}.{signal}")
        tasks = self._dispatch_signal_to_slots(signal, **kwargs)
        return await asyncio.gather(*tasks)


def encode(signal: Signal) -> str:
    """
    Make a string encoding a signal and all its parameters,
    for insertion into a callback field.
    The format is SignalName:value1:value2...
    """
    str_values = [type(signal).__name__]
    for field, value in zip(fields(signal), astuple(signal)):
        field_base_type = unoption(field.type)
        if field_base_type != type(value):
            logger.warning(
                f"Signal attribute value is {value} has type '{type(value)}', but the declared attr type is '{field_base_type}'. This will cause problems when the encoded siglal will be decoded."
            )
        if isinstance(value, Enum):
            str_values.append(value.name)
        elif isinstance(value, bool):
            str_values.append(str(value).lower())
        elif value is None:
            str_values.append("")
        elif isinstance(value, str):
            if ":" in value:
                value = f'"{value}"'
            str_values.append(value)
        elif isinstance(value, (int, float)):
            str_values.append(str(value))
        else:
            raise TypeError(f"Unsupported attribute type: {type(value)}")

    result = ":".join(str_values)

    # Telegram's callback_data is limited to 64 bytes.
    if len(result.encode("utf-8")) >= 64:
        logger.warning(
            f"Encoded signal '{result}' is {len(result.encode('utf-8'))} bytes and may "
            "be truncated by messaging platforms (e.g. telegram limit is 64 bytes)."
        )

    return result


def make_regexp(signal_type: Type[Signal]) -> str:
    """
    Make a regexp to parse a signal from its string encoding.
    The format is `SignalName` or `SignalName:value1:value2...`.

    E.g.:
    "CardAnswerShown:1"
    becomes "^CardAnswerShown:(?P<card_id>\d+)$"
    "CardAnswerGraded:1:good"
    becomes "^CardAnswerGraded:(?P<card_id>\d+):(?P<answer>again|hard|good|easy)$"

    Attribute types are taken from signal class definition.
    Supported are: all scalars, enums.
    """
    name = re.escape(signal_type.__name__)
    signal_fields = fields(signal_type)

    if not signal_fields:
        return f"^{name}$"

    parts = []
    for field in signal_fields:
        field_name = field.name
        base_type = unoption(field.type)

        if issubclass(base_type, Enum):
            enum_keys = "|".join([re.escape(e.name) for e in base_type])
            pattern_part = f"({enum_keys})"
        elif base_type is bool:
            pattern_part = "(true|false)"
        elif base_type is int:
            pattern_part = f"(-?\\d+)"
        elif base_type is float:
            pattern_part = f"(-?\\d+\\.\\d*)"
        elif base_type is str:
            pattern_part = f'([^:]+|".+")'
        else:
            raise TypeError(f"Unsupported attribute type: {base_type}")

        quantifier = "?" if is_optional(field.type) else ""
        parts.append(f"(?P<{field_name}>{pattern_part}{quantifier})")

    return f"^{name}:" + ":".join(parts) + "$"


def decode(signal_type: Type[Signal], string: str) -> Optional[Signal]:
    """
    Parse a string (SignalName:value1:value2...) and return a signal
    of the given type, or None if the format is not matching or payload is invalid.
    """
    pattern = make_regexp(signal_type)
    match = re.match(pattern, string)

    if not match:
        logger.warning(
            f"decode: {signal_type.__name__} regex didn't match against '{string}'"
        )
        return None

    data = match.groupdict()
    kwargs: Dict[str, Any] = {}
    try:
        for field in fields(signal_type):
            str_val = data[field.name]
            target_type = field.type
            base_type = unoption(target_type)

            if str_val == "" and is_optional(target_type):
                kwargs[field.name] = None
                continue

            if issubclass(base_type, Enum):
                value = base_type[str_val]
            elif base_type is bool:
                value = str_val == "true"
            elif base_type is int:
                value = int(str_val)
            elif base_type is float:
                value = float(str_val)
            elif base_type is str:
                if str_val.startswith('"') and str_val.endswith('"'):
                    value = str_val[1:-1]
                else:
                    value = str_val
            else:
                raise TypeError(f"Unsupported attribute type: {base_type}")

            kwargs[field.name] = value

        return signal_type(**kwargs)

    except (ValueError, KeyError) as e:
        logger.error(
            f"Failed to coerce field for signal {signal_type.__name__} from data {data}: {e}"
        )
        return None
    except TypeError as e:
        logger.error(
            f"Error instantiating signal {signal_type.__name__} from payload {kwargs}: {e}"
        )
        return None
