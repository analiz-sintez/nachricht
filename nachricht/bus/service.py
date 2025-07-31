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
    if len(contexts) == 0 or not contexts[-1]:
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
            if conditions := plug.conditions:
                # ??? get all the contexts from the args provided
                # TERRIBLE LEAK FROM THE CONTEXT LAYER
                if not (ctx := kwargs.get("ctx")):
                    continue
                contexts = []
                if ctx.message:
                    contexts.append(ctx.context(ctx.message))
                if ctx.conversation:
                    contexts.append(ctx.context(ctx.conversation))
                if check_conditions(conditions, *contexts) is None:
                    continue

            slot = plug.slot
            slot_signature = signature(slot)
            relevant_args = {}

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
    for insertion into callback field.
    """
    values = []

    for field, value in zip(fields(signal), astuple(signal)):
        if isinstance(value, Enum):
            values.append(value.name)
        elif isinstance(value, bool):
            values.append(str(value).lower())
        else:
            values.append(str(value))

    return f"{type(signal).__name__}:{':'.join(values)}"


def make_regexp(signal_type: Type[Signal]) -> str:
    """
    Make a regexp to parse signal attributes from its string encoding.

    E.g.:
    "CardAnswerShown:1"
    becomes "^CardAnswerShown:(?P<card_id>\d+)$"
    "CardAnswerGraded:1:good"
    becomes "^CardAnswerGraded:(?P<card_id>\d+):(?P<answer>again|hard|good|easy)$"

    Attribute types are taken from signal class definition.
    Supported are: all scalars, enums.
    """
    # Start the regular expression pattern with the signal name
    pattern = f"^{signal_type.__name__}"

    # Iterate through the fields to match each attribute
    # TODO support lists and dicts of scalar types?
    for field in fields(signal_type):
        attr = field.name
        attr_type = field.type
        if is_optional(attr_type):
            attr_type = unoption(attr_type)
        if isinstance(attr_type, object) and issubclass(attr_type, Enum):
            # If the attribute is an Enum, match its possible values
            enum_values = "|".join([e.name for e in attr_type])
            pattern += f":(?P<{attr}>{enum_values})"
        elif attr_type is int:
            # Match digits for integers
            pattern += f":(?P<{attr}>\\d+)"
        elif attr_type is float:
            # Match floating point numbers
            pattern += f":(?P<{attr}>\\d+(\\.\\d+)?)"
        elif attr_type is str:
            # Match any non-whitespace characters for strings
            pattern += f":(?P<{attr}>\\S+)"
        elif attr_type is bool:
            # Match 'true' or 'false' for boolean
            pattern += f":(?P<{attr}>true|false)"
        else:
            raise TypeError(f"Unsupported attribute type: {attr_type}")

    pattern += "$"
    return pattern


def decode(signal_type: Type[Signal], string: str) -> Optional[Signal]:
    """
    Parse a string according to signal type and return
    a signal of this type, or None if the format is not matching.
    """
    # Get the regular expression pattern for the signal type
    pattern = make_regexp(signal_type)
    match = re.match(pattern, string)

    if not match:
        logger.warning(
            f"decode: {signal_type.__name__} didn't match against {string}"
        )
        return None

    # Extract matched attributes
    matched_params = match.groupdict()
    # Convert matched attributes to the correct type and create signal instance
    signal_params = {}
    for field in fields(signal_type):
        value = matched_params.get(field.name)
        if value is not None:
            if issubclass(field.type, Enum):
                signal_params[field.name] = field.type[value]
            elif field.type is int:
                signal_params[field.name] = int(value)
            elif field.type is float:
                signal_params[field.name] = float(value)
            elif field.type is bool:
                signal_params[field.name] = value.lower() == "true"
            else:
                signal_params[field.name] = value

    return signal_type(**signal_params)
