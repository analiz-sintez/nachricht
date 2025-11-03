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
    private: bool = False


class Option(Generic[T]):
    """
    Defines a single, typed, configurable option with a default value.
    """

    group: Optional[Type[OptionGroup]] = None
    model: Optional[Type[OptionsMixin]] = None
    name: TranslatableString
    value: T
    description: Optional[TranslatableString] = None
    private: bool = False

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
        self._groups: Dict[str, Type[OptionGroup]] = {}
        self._privacy: Dict[str, bool] = {}

    def register(self, cls: Type[Option]):
        """
        Registers an Option subclass, computes its path, and checks for duplicates.
        """
        path_parts = []
        current_group = cls.group
        while current_group:
            # Build group path and register the group class
            group_path_parts = path_parts.copy()
            group_path_parts.insert(0, current_group.__name__)
            group_path = "/".join(group_path_parts)
            if group_path not in self._groups:
                self._groups[group_path] = current_group

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

        # Determine privacy by checking the option and its entire group hierarchy
        is_private = cls.private
        if not is_private:
            current_group = cls.group
            while current_group:
                if getattr(current_group, "private", False):
                    is_private = True
                    break
                current_group = current_group.group
        self._privacy[path] = is_private

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

    def is_private(self, path: str) -> bool:
        """Checks if an option path was marked as private during registration."""
        return self._privacy.get(path, False)

    def get_parent_path(self, path: str) -> Optional[str]:
        """
        Calculates the parent path for a given option or group path.
        Returns "" for top-level items, and None for the root itself.
        """
        if not path:
            return None
        parts = path.split("/")
        if len(parts) == 1:
            return ""
        return "/".join(parts[:-1])

    def get_children(
        self, path: str
    ) -> tuple[dict[str, Type[OptionGroup]], list[Type[Option]]]:
        """
        Gets all non-private direct child groups and options for a given path.
        """
        subgroups: dict[str, Type[OptionGroup]] = {}
        for group_path, group_cls in self._groups.items():
            if self.get_parent_path(
                group_path
            ) == path and not self.is_private(group_path):
                subgroups[group_path] = group_cls

        options: list[Type[Option]] = []
        for option_path, option_cls in self._paths.items():
            if self.get_parent_path(
                option_path
            ) == path and not self.is_private(option_path):
                options.append(option_cls)

        return subgroups, options


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


def create_option_registry(bus: Bus) -> OptionRegistry:
    """
    Initializes the global option registry, discovers all Option subclasses,
    and returns the registry instance.
    """
    global option_registry
    option_registry = OptionRegistry(bus=bus)
    discover_options(option_registry)
    return option_registry


def get_option_registry() -> Optional[OptionRegistry]:
    """Returns the global option registry instance."""
    return option_registry
