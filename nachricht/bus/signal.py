from dataclasses import dataclass


@dataclass
class Signal:
    pass


@dataclass
class TerminalSignal(Signal):
    pass


@dataclass
class InternalSignal(Signal):
    """
    The type of signal not intended to be serialized for a callback:
    - its field types are not restricted to int, float, string or enum
    - but it also can't be packed into button
    """

    pass
