from enum import Enum
from dataclasses import dataclass
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from . import Signal, Bus, encode, decode, make_regexp


@pytest.fixture
def bus():
    return Bus()


def test_register_signal(bus):
    class TestSignal(Signal):
        pass

    assert TestSignal not in bus._plugs
    bus.register(TestSignal)
    assert TestSignal in bus._plugs


def test_register_non_signal_should_raise_type_error(bus):
    with pytest.raises(TypeError):
        bus.register(object)


def test_connect_slot(bus):
    class TestSignal(Signal):
        pass

    slot = MagicMock()
    bus.connect(TestSignal, slot)

    assert slot in [p.slot for p in bus._plugs[TestSignal]]


def test_emit_signal_without_slots(bus):
    class TestSignal(Signal):
        pass

    signal = TestSignal()
    tasks = bus.emit(signal)

    assert not tasks


@pytest.mark.asyncio
async def test_emit_signal_with_slot(bus):
    class TestSignal(Signal):
        pass

    slot = AsyncMock()
    bus.connect(TestSignal, slot)

    signal = TestSignal()
    tasks = bus.emit(signal)

    assert tasks is not None
    await asyncio.gather(*tasks)
    slot.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_emit_and_wait_signal_with_slot(bus):
    class TestSignal(Signal):
        pass

    slot = AsyncMock()
    bus.connect(TestSignal, slot)

    signal = TestSignal()
    await bus.emit_and_wait(signal)

    slot.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_emit_signal_with_param(bus):
    @dataclass
    class TestSignal(Signal):
        param: int

    async def slot(param: int):
        await async_mock(param)

    async_mock = AsyncMock()
    bus.connect(TestSignal, slot)

    signal = TestSignal(param=42)
    tasks = bus.emit(signal)

    assert tasks is not None
    await asyncio.gather(*tasks)
    async_mock.assert_awaited_once_with(42)


def test_bus_encoding(bus):
    @dataclass
    class TestSignal(Signal):
        param: int
        param2: str

    assert encode(TestSignal(1, "hello")) == "TestSignal:1:hello"
    assert encode(TestSignal(1, "hello:world")) == 'TestSignal:1:"hello:world"'


def test_make_regexp(bus):
    @dataclass
    class TestSignal(Signal):
        param: int
        param2: str

    # expected_regexp = r"^TestSignal:(?P<param>\d+):(?P<param2>\S+)$"
    expected_regexp = (
        r'^TestSignal:(?P<param>(-?\d+)):(?P<param2>([^:]+|".+"))$'
    )
    assert make_regexp(TestSignal) == expected_regexp


def test_decode(bus):
    @dataclass
    class TestSignal(Signal):
        param: int
        param2: str

    signal_str = "TestSignal:1:hello"
    decoded_signal = decode(TestSignal, signal_str)
    assert decoded_signal == TestSignal(param=1, param2="hello")

    # Test string with colon is quoted and parsed correctly
    signal_str_with_colon = 'TestSignal:1:"hello:world"'
    decoded_signal_with_colon = decode(TestSignal, signal_str_with_colon)
    assert decoded_signal_with_colon == TestSignal(
        param=1, param2="hello:world"
    )

    # Test with incorrect format
    incorrect_signal_str = "TestSignal:1"
    assert decode(TestSignal, incorrect_signal_str) is None

    # Test with different signal type
    @dataclass
    class AnotherSignal(Signal):
        other_param: int

    another_signal_str = "AnotherSignal:2"
    decoded_another_signal = decode(AnotherSignal, another_signal_str)
    assert decoded_another_signal == AnotherSignal(other_param=2)

    # Enum test
    class Status(Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    @dataclass
    class EnumSignal(Signal):
        status: Status

    enum_signal_str = "EnumSignal:ACTIVE"
    decoded_enum_signal = decode(EnumSignal, enum_signal_str)
    assert decoded_enum_signal == EnumSignal(status=Status.ACTIVE)

    # Incorrect enum value
    incorrect_enum_signal_str = "EnumSignal:UNKNOWN"
    assert decode(EnumSignal, incorrect_enum_signal_str) is None

    # Partial enum data
    partial_enum_signal_str = "EnumSignal"
    assert decode(EnumSignal, partial_enum_signal_str) is None

    # Float field test
    @dataclass
    class FloatSignal(Signal):
        value: float

    float_signal_str = "FloatSignal:3.14"
    decoded_float_signal = decode(FloatSignal, float_signal_str)
    assert decoded_float_signal == FloatSignal(value=3.14)

    # Incorrect float format
    incorrect_float_signal_str = "FloatSignal:three_point_one_four"
    assert decode(FloatSignal, incorrect_float_signal_str) is None

    # Bool field test
    @dataclass
    class BoolSignal(Signal):
        is_active: bool

    bool_signal_str_true = "BoolSignal:true"
    decoded_bool_signal_true = decode(BoolSignal, bool_signal_str_true)
    assert decoded_bool_signal_true == BoolSignal(is_active=True)

    bool_signal_str_false = "BoolSignal:false"
    decoded_bool_signal_false = decode(BoolSignal, bool_signal_str_false)
    assert decoded_bool_signal_false == BoolSignal(is_active=False)

    # Incorrect bool format
    incorrect_bool_signal_str = "BoolSignal:yes"
    assert decode(BoolSignal, incorrect_bool_signal_str) is None


def test_unsupported_field_types_raise_error(bus):
    """Test that encode and make_regexp raise TypeError for unsupported field types."""

    @dataclass
    class ComplexObject:
        a: int
        b: str

    @dataclass
    class UnsupportedSignal(Signal):
        unsupported_field: ComplexObject

    signal_instance = UnsupportedSignal(
        unsupported_field=ComplexObject(1, "test")
    )

    with pytest.raises(TypeError, match="Unsupported attribute type"):
        encode(signal_instance)

    with pytest.raises(TypeError, match="Unsupported attribute type"):
        make_regexp(UnsupportedSignal)

    # Also test with a dict, which is also unsupported
    @dataclass
    class UnsupportedDictSignal(Signal):
        unsupported_field: dict

    signal_instance_dict = UnsupportedDictSignal(
        unsupported_field={"key": "value"}
    )
    with pytest.raises(TypeError, match="Unsupported attribute type"):
        encode(signal_instance_dict)

    with pytest.raises(TypeError, match="Unsupported attribute type"):
        make_regexp(UnsupportedDictSignal)


def test_encode_decode_roundtrip(bus):
    @dataclass
    class IntSignal(Signal):
        param: int

    int_signal = IntSignal(42)
    encoded_int_signal = encode(int_signal)
    decoded_int_signal = decode(IntSignal, encoded_int_signal)
    assert decoded_int_signal == int_signal

    @dataclass
    class FloatSignal(Signal):
        value: float

    float_signal = FloatSignal(3.14)
    encoded_float_signal = encode(float_signal)
    decoded_float_signal = decode(FloatSignal, encoded_float_signal)
    assert decoded_float_signal == float_signal

    @dataclass
    class BoolSignal(Signal):
        is_active: bool

    bool_signal = BoolSignal(True)
    encoded_bool_signal = encode(bool_signal)
    decoded_bool_signal = decode(BoolSignal, encoded_bool_signal)
    assert decoded_bool_signal == bool_signal

    @dataclass
    class StrSignal(Signal):
        message: str

    str_signal = StrSignal("hello")
    encoded_str_signal = encode(str_signal)
    decoded_str_signal = decode(StrSignal, encoded_str_signal)
    assert decoded_str_signal == str_signal

    # Test with colon in string
    str_signal_with_colon = StrSignal("hello:world")
    encoded_str_signal_colon = encode(str_signal_with_colon)
    decoded_str_signal_colon = decode(StrSignal, encoded_str_signal_colon)
    assert decoded_str_signal_colon == str_signal_with_colon

    class Status(Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    @dataclass
    class EnumSignal(Signal):
        status: Status

    enum_signal = EnumSignal(Status.ACTIVE)
    encoded_enum_signal = encode(enum_signal)
    decoded_enum_signal = decode(EnumSignal, encoded_enum_signal)
    assert decoded_enum_signal == enum_signal


@pytest.mark.asyncio
async def test_deferred_connection(bus):
    @dataclass
    class DeferredSignal(Signal):
        value: str

    mock_slot = AsyncMock()

    @bus.on("DeferredSignal")
    async def deferred_slot(value: str):
        await mock_slot(value)

    # Before setup, connection is deferred.
    assert len(bus._deferred_connections) == 1
    assert not bus._plugs.get(DeferredSignal)

    # Emitting does nothing.
    tasks = bus.emit(DeferredSignal(value="initial"))
    await asyncio.gather(*tasks)
    mock_slot.assert_not_awaited()

    # Setup discovers signals and resolves connections.
    bus.setup()

    # Connection is now resolved.
    assert not bus._deferred_connections
    assert deferred_slot in [p.slot for p in bus._plugs[DeferredSignal]]

    # Emitting now calls the slot.
    tasks = bus.emit(DeferredSignal(value="final"))
    await asyncio.gather(*tasks)
    mock_slot.assert_awaited_once_with("final")


def test_create_signal_by_name(bus):
    @dataclass
    class MySignal(Signal):
        id: int
        username: str

    bus.register(MySignal)
    signal_instance = bus.signal("MySignal", id=123, username="test")

    assert isinstance(signal_instance, MySignal)
    assert signal_instance.id == 123
    assert signal_instance.username == "test"


def test_create_signal_by_name_unknown_signal(bus):
    with pytest.raises(
        ValueError, match="Unknown signal type: 'NonExistentSignal'"
    ):
        bus.signal("NonExistentSignal")


def test_create_signal_by_name_wrong_args(bus):
    @dataclass
    class AnotherSignal(Signal):
        value: int

    bus.register(AnotherSignal)

    with pytest.raises(TypeError):
        bus.signal("AnotherSignal", 1, 2)  # Too many args

    with pytest.raises(TypeError):
        bus.signal("AnotherSignal", wrong_kw="test")  # Wrong keyword
