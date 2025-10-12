import json
import logging
from functools import wraps
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
import pytest


from nachricht import create_app, db as _db
from nachricht.bus.backends import (
    Signal,
    NoOpBackend,
    LogFileBackend,
    DatabaseBackend,
    EmittedSignal,
    SlotCall,
)
from nachricht.bus import Bus, encode, decode, make_regexp


class TestingConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # other test-specific settings


@pytest.fixture(scope="function")
def db_session(request):
    """
    Fixture for providing a clean in-memory database for each test function.
    """
    app = create_app(TestingConfig)
    ctx = app.app_context()
    ctx.push()

    _db.create_all()

    yield _db.session

    _db.session.remove()
    _db.drop_all()
    ctx.pop()


@dataclass
class IntegrationTestSignal(Signal):
    data: str


async def mock_slot_spec(data: str):
    pass


@pytest.mark.asyncio
class TestBusAndBackendIntegration:
    async def test_bus_with_noop_backend(self):
        backend = NoOpBackend()
        bus = Bus(saving_backend=backend)
        mock_slot = wraps(mock_slot_spec)(AsyncMock())

        bus.connect(IntegrationTestSignal, mock_slot)
        await bus.emit_and_wait(IntegrationTestSignal(data="test"))

        mock_slot.assert_awaited_once_with(data="test")
        # No easy way to assert "nothing happened" in the backend,
        # we just ensure it ran without error.

    async def test_bus_with_logfile_backend(self, caplog):
        caplog.set_level(logging.INFO)
        backend = LogFileBackend()
        bus = Bus(saving_backend=backend)
        mock_slot = wraps(mock_slot_spec)(AsyncMock())

        bus.connect(IntegrationTestSignal, mock_slot)
        await bus.emit_and_wait(IntegrationTestSignal(data="log this"))

        mock_slot.assert_awaited_once_with(data="log this")

        assert len(caplog.records) >= 2
        signal_log = json.loads(caplog.records[-2].msg)
        slot_log = json.loads(caplog.records[-1].msg)

        # Check signal log
        assert signal_log["event"] == "signal_emitted"
        assert signal_log["signal_type"] == "IntegrationTestSignal"
        assert signal_log["signal_fields"]["data"] == "log this"

        # Check slot log
        assert slot_log["event"] == "slot_executed"
        assert slot_log["slot_name"] == "mock_slot_spec"
        assert slot_log["status"] == "success"
        assert "error" not in slot_log

        # Check correlation
        assert signal_log["emitted_signal_id"] == slot_log["emitted_signal_id"]

    async def test_bus_with_database_backend(self, db_session):
        backend = DatabaseBackend()
        bus = Bus(saving_backend=backend)
        mock_slot = wraps(mock_slot_spec)(AsyncMock())

        bus.connect(IntegrationTestSignal, mock_slot)
        await bus.emit_and_wait(IntegrationTestSignal(data="db test"))

        mock_slot.assert_awaited_once_with(data="db test")

        assert EmittedSignal.query.count() == 1
        assert SlotCall.query.count() == 1

        signal_entry = EmittedSignal.query.one()
        slot_entry = SlotCall.query.one()

        assert signal_entry.signal_type == "IntegrationTestSignal"
        assert signal_entry.signal_fields["data"] == "db test"
        assert slot_entry.slot_name == "mock_slot_spec"
        assert slot_entry.status == "success"
        assert slot_entry.emitted_signal_id == signal_entry.id

    async def test_bus_with_database_backend_slot_error(self, db_session):
        backend = DatabaseBackend()
        bus = Bus(saving_backend=backend)

        async def failing_slot(data: str):
            raise ValueError("It failed")

        bus.connect(IntegrationTestSignal, failing_slot)

        # emit_and_wait re-raises the exception
        with pytest.raises(ValueError, match="It failed"):
            await bus.emit_and_wait(IntegrationTestSignal(data="fail"))

        slot_entry = SlotCall.query.one()
        assert slot_entry.status == "error"
        assert slot_entry.duration_ms >= 0
        assert "ValueError: It failed" in slot_entry.error_message
