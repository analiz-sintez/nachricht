import logging
from typing import Type, TypeVar, get_type_hints

from sqlalchemy.orm import mapped_column
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableDict

from ..db import db, JsonValue
from .service import Option, get_options_registry
from .signal import OptionChanged

T = TypeVar("T")
logger = logging.getLogger(__name__)


class OptionAccessor:
    """
    A descriptor that provides dictionary-like access to typed options
    on an object that has an 'options' JSON field.
    """

    def __init__(self, instance=None, registry=None):
        self.instance = instance
        self.registry = registry or get_options_registry()

    def __get__(self, instance, owner):
        if instance is None:
            return self  # Class-level access
        return self.__class__(instance)

    def __getitem__(self, option_cls: Type[Option]) -> T:
        """
        Gets the value for an option, falling back to its default.
        """
        if not self.registry or not self.registry.get_path(option_cls):
            raise KeyError(f"Option {option_cls.__name__} is not registered.")

        required_model = self.registry.get_model(option_cls)
        if required_model and not isinstance(self.instance, required_model):
            raise TypeError(
                f"Option {option_cls.__name__} is not applicable to object "
                f"of type {type(self.instance).__name__}"
            )

        path = self.registry.get_path(option_cls)
        return self.instance.options.get(path, option_cls.value)

    def __setitem__(self, option_cls: Type[Option], value: T):
        """
        Sets the value for an option after validation.
        """
        if not self.registry or not self.registry.get_path(option_cls):
            raise KeyError(f"Option {option_cls.__name__} is not registered.")

        # Type validation
        type_hints = get_type_hints(option_cls)
        expected_type = type_hints.get("value")
        if expected_type and not isinstance(value, expected_type):
            raise TypeError(
                f"Invalid type for {option_cls.__name__}. "
                f"Expected {expected_type}, got {type(value)}"
            )

        # Custom validation
        if not option_cls._check(value):
            raise ValueError(
                f"Value '{value}' failed custom validation for "
                f"option {option_cls.__name__}"
            )

        path = self.registry.get_path(option_cls)
        old_value = self[option_cls]

        if self.instance.options is None:
            self.instance.options = {}
        self.instance.options[path] = value
        flag_modified(self.instance, "options")
        logger.debug(f"Set option '{path}' for {self.instance} to '{value}'")

        # Emit signal
        if self.registry.bus:
            signal = OptionChanged(
                model_name=self.instance.__class__.__name__,
                obj_id=self.instance.id,
                option_path=path,
                old_value=old_value,
                new_value=value,
            )
            self.registry.bus.emit(signal)


class OptionsMixin:
    options = mapped_column(MutableDict.as_mutable(JSON))
    option = OptionAccessor()

    def set_option(self, name: str, value) -> None:
        logger.warning(
            "set_option and get_option methods are deprecated and will be deleted soon. Please migrate to Option and OptionGroup approach."
        )
        if self.options is None:
            self.options = {}
        keys = name.split("/")
        d = self.options
        for key in keys[:-1]:
            if key not in d or not isinstance(d[key], dict):
                d[key] = {}
            d = d[key]
        d[keys[-1]] = value
        logger.info("Setting option for: %s = %s", name, value)
        flag_modified(self, "options")
        db.session.add(self)
        db.session.commit()

    def get_option(self, name: str, default_value=None) -> JsonValue:
        logger.warning(
            "set_option and get_option methods are deprecated and will be deleted soon. Please migrate to Option and OptionGroup approach."
        )
        if not self.options:
            logger.debug(
                "No options set. Returning default value for %s: %s",
                name,
                default_value,
            )
            return default_value
        keys = name.split("/")
        d = self.options
        for key in keys:
            if key not in d:
                logger.debug(
                    "Option '%s' not found. Returning default value: %s",
                    name,
                    default_value,
                )
                return default_value
            d = d[key]
        logger.debug("Retrieved option: %s = %s", name, d)
        return d
