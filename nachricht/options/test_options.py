import pytest
from unittest.mock import MagicMock, patch

from ..i18n import TranslatableString as _
from . import (
    Option,
    OptionGroup,
    OptionRegistry,
    discover_options,
    OptionAccessor,
    OptionChanged,
)


# Mock data for testing
class TestGroup(OptionGroup):
    name = _("Test Group")
    description = _("A group for testing.")


class RootOption(Option):
    group = None
    name = _("Root Option")
    value: bool = True
    description = _("A boolean option at the root.")


class IntOption(Option):
    group = TestGroup
    name = _("Integer Option")
    value: int = 10
    description = _("An integer option.")

    @classmethod
    def _check(cls, value):
        return value > 0


class StrOption(Option):
    group = TestGroup
    name = _("String Option")
    value: str = "default"
    description = _("A string option.")


# Pytest Fixtures
@pytest.fixture
def option_registry(mock_bus):
    """Provides a clean, empty registry for each test."""
    registry = OptionRegistry(mock_bus)
    # Clear the global registry's internal state before each test
    registry._options.clear()
    registry._paths.clear()
    return registry


@pytest.fixture
def mock_user():
    """Provides a mock object with an OptionsMixin-like interface."""
    user = MagicMock()
    user.options = {}

    # Simulate SQLAlchemy's flag_modified
    def flag_modified(instance, attribute):
        instance._flag_modified_called = True

    with patch("nachricht.options.mixin.flag_modified", flag_modified):
        yield user


@pytest.fixture
def mock_bus():
    """Provides a mock signal bus."""
    bus = MagicMock()
    with patch("nachricht.bus.get_bus", return_value=bus):
        yield bus


class TestOptionRegistryAndDiscovery:
    def test_discover_options(self, option_registry):
        """Verify that discover_options finds and registers Option subclasses."""
        discover_options(option_registry)

        assert RootOption in option_registry._options
        assert IntOption in option_registry._options
        assert StrOption in option_registry._options
        assert len(option_registry._options) == 3

    def test_option_path_generation(self, option_registry):
        """Verify correct path generation for root and grouped options."""
        discover_options(option_registry)

        assert option_registry.get_path(RootOption) == "RootOption"
        assert option_registry.get_path(IntOption) == "TestGroup/IntOption"

    def test_get_option_by_path(self, option_registry):
        """Verify that we can retrieve an option class by its path."""
        discover_options(option_registry)
        path = option_registry.get_path(IntOption)
        retrieved_option = option_registry.get_option(path)
        assert retrieved_option is IntOption

    def test_duplicate_option_warning(self, option_registry, caplog):
        """Verify that defining an option with a duplicate path logs a warning."""

        class DupeOption(Option):
            group = TestGroup
            name = "Integer Option"
            value: int = 99

        discover_options(option_registry)  # First discovery
        discover_options(
            option_registry
        )  # Second discovery should trigger warning
        assert "Duplicate option path" in caplog.text
        assert "TestGroup/IntOption" in caplog.text


class TestOptionAccessor:
    @pytest.fixture
    def accessor(self, mock_user, option_registry):
        """Provides an accessor initialized with a mock user and a populated registry."""
        discover_options(option_registry)
        return OptionAccessor(mock_user, option_registry)

    def test_getitem_default_value(self, accessor):
        """Test getting an option that has not been set; should return the default."""
        assert accessor[IntOption] == 10
        assert accessor[RootOption] is True
        assert accessor[StrOption] == "default"

    def test_getitem_stored_value(self, accessor, mock_user):
        """Test getting an option after it has been set."""
        mock_user.options = {"TestGroup/IntOption": 99}
        assert accessor[IntOption] == 99

    def test_setitem_valid_value(self, accessor, mock_user):
        """Test setting a valid value for an option."""
        accessor[IntOption] = 42
        assert mock_user.options["TestGroup/IntOption"] == 42
        assert mock_user._flag_modified_called is True

    def test_setitem_invalid_type(self, accessor):
        """Test that setting a value of the wrong type raises TypeError."""
        with pytest.raises(TypeError):
            accessor[IntOption] = "not a number"

    def test_setitem_custom_check_failure(self, accessor):
        """Test that setting a value failing the custom _check raises ValueError."""
        with pytest.raises(ValueError):
            accessor[IntOption] = -5  # Fails the value > 0 check

    def test_setitem_emits_signal(
        self, accessor, mock_user, mock_bus, option_registry
    ):
        """Test that setting a value emits an OptionChanged signal."""
        accessor[IntOption] = 20

        mock_bus.emit.assert_called_once()
        signal_instance = mock_bus.emit.call_args[0][0]

        assert isinstance(signal_instance, OptionChanged)
        assert signal_instance.obj_id is mock_user.id
        assert signal_instance.option_path is option_registry.get_path(
            IntOption
        )
        assert signal_instance.old_value == 10  # The default value
        assert signal_instance.new_value == 20

    def test_setitem_emits_signal_with_old_stored_value(
        self, accessor, mock_user, mock_bus
    ):
        """Test that the signal contains the correct old value if one was already set."""
        mock_user.options = {"TestGroup/IntOption": 50}
        accessor[IntOption] = 100

        mock_bus.emit.assert_called_once()
        signal_instance = mock_bus.emit.call_args[0][0]

        assert signal_instance.old_value == 50
        assert signal_instance.new_value == 100

    def test_get_nonexistent_option_raises_keyerror(self, accessor):
        """Test that accessing an unregistered Option class raises KeyError."""

        class UnregisteredOption(Option):
            pass

        with pytest.raises(KeyError):
            _ = accessor[UnregisteredOption]

    def test_set_nonexistent_option_raises_keyerror(self, accessor):
        """Test that setting an unregistered Option class raises KeyError."""

        class UnregisteredOption(Option):
            pass

        with pytest.raises(KeyError):
            accessor[UnregisteredOption] = 123
