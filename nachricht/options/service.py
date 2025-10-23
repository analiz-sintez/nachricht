from __future__ import annotations
import logging
from typing import Optional, Type, Dict, TypeVar, Generic, get_type_hints

from ..bus import Bus
from ..i18n import TranslatableString

# Forward declaration to avoid circular imports.
# This type represents any class that includes the OptionsMixin.
OptionsMixin = "OptionsMixin"

logger = logging.getLogger(__name__)

T = TypeVar("T")


class OptionGroup:
    """
    A namespace for a collection of related options. Groups can be nested.
    """

    group: Optional[Type[OptionGroup]] = None
    model: Optional[Type[OptionsMixin]] = None
    name: TranslatableString
    description: Optional[TranslatableString] = None


class Option(Generic[T]):
    """
    Defines a single, typed, configurable option with a default value.
    """

    group: Optional[Type[OptionGroup]] = None
    model: Optional[Type[OptionsMixin]] = None
    name: TranslatableString
    value: T
    description: Optional[TranslatableString] = None

    @classmethod
    def _check(cls, value: T) -> bool:
        """
        An optional hook for custom, complex validation logic.
        """
        return True


class OptionRegistry:
    """
    A central registry for all discovered Option subclasses.
    """

    def __init__(self, bus: Bus):
        self.bus = bus
        self._options: Dict[Type[Option], dict] = {}
        self._paths: Dict[str, Type[Option]] = {}

    def register(self, cls: Type[Option]):
        """
        Registers an Option subclass, computes its path, and checks for duplicates.
        """
        path_parts = []
        current_group = cls.group
        while current_group:
            path_parts.insert(0, current_group.__name__)
            current_group = current_group.group
        path_parts.append(cls.__name__)
        path = "/".join(path_parts)

        if path in self._paths:
            logger.warning(
                f"Duplicate option path '{path}' detected for class {cls.__name__}. "
                f"Original: {self._paths[path].__name__}. Skipping registration."
            )
            return

        # Determine the effective model, inheriting from the group hierarchy
        model = cls.model
        if model is None:
            current = cls.group
            while current and model is None:
                model = getattr(current, "model", None)
                current = getattr(current, "group", None)

        self._paths[path] = cls
        self._options[cls] = {"path": path, "model": model}
        logger.info(
            f"Registered option {cls.__name__} at path '{path}'"
            + (f" for model {model}" if model else "")
        )

    def get_option(self, path: str) -> Optional[Type[Option]]:
        """Retrieves an Option class by its unique string path."""
        return self._paths.get(path)

    def get_path(self, cls: Type[Option]) -> Optional[str]:
        """Retrieves the unique string path for a registered Option class."""
        return self._options.get(cls, {}).get("path")

    def get_model(self, cls: Type[Option]) -> Optional[Type[OptionsMixin]]:
        """
        Retrieves the model an Option is scoped to.
        """
        return self._options.get(cls, {}).get("model")


def discover_options(registry: OptionRegistry):
    """
    Finds all subclasses of Option and registers them.
    """
    logger.debug("Discovering Option subclasses...")
    unprocessed = list(Option.__subclasses__())
    processed = set()
    while unprocessed:
        cls = unprocessed.pop(0)
        if cls not in processed:
            registry.register(cls)
            processed.add(cls)
            unprocessed.extend(cls.__subclasses__())
    logger.debug(f"Option discovery complete. {len(processed)} options found.")


option_registry: Optional[OptionRegistry] = None


def create_options_registry(bus: Bus) -> OptionRegistry:
    """
    Initializes the global option registry, discovers all Option subclasses,
    and returns the registry instance.
    """
    global option_registry
    option_registry = OptionRegistry(bus=bus)
    discover_options(option_registry)
    return option_registry


def get_options_registry() -> Optional[OptionRegistry]:
    """Returns the global option registry instance."""
    return option_registry
