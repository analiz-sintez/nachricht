from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Type

from ..db import JsonValue
from ..bus import InternalSignal


@dataclass
class OptionChanged(InternalSignal):
    """Emitted when an option's value is changed. Serializable for logging."""

    # The object whose option was changed.
    model_name: str
    obj_id: int

    # The option that was changed, identified by its unique path.
    option_path: str

    # The previous and new values. These must be JSON-serializable.
    old_value: JsonValue
    new_value: JsonValue
