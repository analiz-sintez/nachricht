import re
import json
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

    def register(self, signal_type: Type[Signal]):
        """Register a signal."""
        if not issubclass(signal_type, Signal):
            raise TypeError(
                "You should inherit your signals from Signal class."
                " It allows to track all the signals tree of the application."
            )
        if signal_type not in self._plugs:
            self._plugs[signal_type] = []
            logger.info(f"Registered signal type: {signal_type.__name__}")

    def on(
        self,
        signal_type: Type[Signal],
        conditions: Conditions = {},
    ):
        """Make a decorator which connects a signal to any slot."""

        def _wrapper(slot: Callable) -> Callable:
            self.connect(signal_type, slot, conditions)
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


def _json_encode_default(o: Any) -> Any:
    """JSON encoder default function to handle specific types."""
    if isinstance(o, Enum):
        return o.name
    raise TypeError(
        f"Object of type {o.__class__.__name__} is not JSON serializable"
    )


def encode(signal: Signal) -> str:
    """
    Make a JSON string encoding a signal and all its parameters,
    for insertion into a callback field.
    The format is SignalName:JSON_PAYLOAD.
    """
    signal_name = type(signal).__name__
    payload = asdict(signal)
    # Use separators to create a compact JSON string
    json_payload = json.dumps(
        payload, default=_json_encode_default, separators=(",", ":")
    )
    return f"{signal_name}:{json_payload}"


def make_regexp(signal_type: Type[Signal]) -> str:
    """
    Make a regexp to parse a signal from its string encoding.
    The format is `SignalName:JSON_PAYLOAD`.
    """
    # Use re.escape for safety, in case a signal name contains special regex characters.
    pattern = f"^{re.escape(signal_type.__name__)}:(.*)$"
    return pattern


def decode(signal_type: Type[Signal], string: str) -> Optional[Signal]:
    """
    Parse a string (SignalName:JSON_PAYLOAD) and return a signal
    of the given type, or None if the format is not matching or payload is invalid.
    """
    pattern = make_regexp(signal_type)
    match = re.match(pattern, string)

    if not match:
        logger.warning(
            f"decode: {signal_type.__name__} didn't match against {string}"
        )
        return None

    json_payload = match.group(1)
    try:
        data = json.loads(json_payload)
        if not isinstance(data, dict):
            raise TypeError("Decoded JSON payload is not a dictionary.")
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(
            f"Failed to decode or validate JSON payload for {signal_type.__name__}: {e}"
        )
        return None

    # Coerce fields that are not native JSON types (e.g., Enums)
    try:
        for field in fields(signal_type):
            field_name = field.name
            # Check if the field exists in the decoded data and is not None
            if field_name in data and data[field_name] is not None:
                # Get the base type, removing Optional wrapper
                target_type = unoption(field.type)
                if isinstance(target_type, type) and issubclass(
                    target_type, Enum
                ):
                    # Convert string back to Enum member
                    enum_str_value = data[field_name]
                    if not isinstance(enum_str_value, str):
                        raise TypeError(
                            f"Enum value for {field_name} must be a string, got {type(enum_str_value)}"
                        )
                    data[field_name] = target_type[enum_str_value]

    except (KeyError, TypeError) as e:
        # KeyError for invalid enum name, TypeError for other issues
        logger.error(
            f"Failed to coerce field for signal {signal_type.__name__}: {e}"
        )
        return None

    try:
        return signal_type(**data)
    except TypeError as e:
        # This will catch:
        # - Mismatched arguments (e.g., extra keys in `data`).
        # - Missing required arguments (if not in `data`).
        # - Wrong types for non-enum fields (e.g., str for an int field).
        logger.error(
            f"Error instantiating signal {signal_type.__name__} from payload {data}: {e}"
        )
        return None
