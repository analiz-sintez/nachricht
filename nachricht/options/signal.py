from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Type

from ..bus import Signal


@dataclass
class OptionChanged(Signal):
    """Emitted when an option's value is changed."""

    obj: Any
    option: Type["Option"]
    old_value: Any
    new_value: Any
