import json
import logging
from dataclasses import dataclass
import uuid
import pytest
from unittest.mock import patch, ANY

# Assuming your test setup can import the application factory and db object
from nachricht import create_app, db as _db
from nachricht.bus.backends import (
    Signal,
    NoOpBackend,
    LogFileBackend,
    DatabaseBackend,
    EmittedSignal,
    SlotCall,
)


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
class MyTestSignal(Signal):
    value: int


async def my_test_slot(value: int):
    pass


class TestNoOpBackend:
    def test_log_signal_emitted_returns_none(self):
        backend = NoOpBackend()
        signal = MyTestSignal(value=1)
        emitted_signal_id = backend.log_signal_emitted(signal, [my_test_slot])
        assert emitted_signal_id is None

    def test_log_slot_execution_does_nothing(self):
        backend = NoOpBackend()
        try:
            backend.log_slot_execution(
                emitted_signal_id=None,
                slot=my_test_slot,
                status="success",
                duration_ms=10.0,
            )
        except Exception as e:
            pytest.fail(
                f"NoOpBackend.log_slot_execution raised an exception: {e}"
            )


class TestLogFileBackend:
    def test_log_signal_emitted(self, caplog):
        caplog.set_level(logging.INFO)
        backend = LogFileBackend()
        signal = MyTestSignal(value=42)
        emitted_signal_id = backend.log_signal_emitted(signal, [my_test_slot])

        assert isinstance(emitted_signal_id, uuid.UUID)
        assert len(caplog.records) == 1
        log_data = json.loads(caplog.records[0].msg)

        assert log_data["event"] == "signal_emitted"
        assert log_data["emitted_signal_id"] == str(emitted_signal_id)
        assert log_data["signal_type"] == "MyTestSignal"
        assert log_data["signal_fields"] == {"value": 42}
        assert log_data["triggered_slots"] == ["my_test_slot"]

    def test_log_slot_execution_success(self, caplog):
        caplog.set_level(logging.INFO)
        backend = LogFileBackend()
        emitted_signal_id = uuid.uuid4()
        backend.log_slot_execution(
            emitted_signal_id=emitted_signal_id,
            slot=my_test_slot,
            status="success",
            duration_ms=123.45,
        )

        assert len(caplog.records) == 1
        log_data = json.loads(caplog.records[0].msg)

        assert log_data["event"] == "slot_executed"
        assert log_data["emitted_signal_id"] == str(emitted_signal_id)
        assert log_data["slot_name"] == "my_test_slot"
        assert log_data["status"] == "success"
        assert log_data["duration_ms"] == 123.45
        assert "error" not in log_data

    def test_log_slot_execution_error(self, caplog):
        caplog.set_level(logging.INFO)
        backend = LogFileBackend()
        emitted_signal_id = uuid.uuid4()
        backend.log_slot_execution(
            emitted_signal_id=emitted_signal_id,
            slot=my_test_slot,
            status="error",
            duration_ms=50.0,
            error_message="Something went wrong",
        )
        log_data = json.loads(caplog.records[0].msg)
        assert log_data["status"] == "error"
        assert log_data["error"] == "Something went wrong"


class TestDatabaseBackend:
    def test_log_signal_emitted(self, db_session):
        backend = DatabaseBackend()
        signal = MyTestSignal(value=99)
        emitted_signal_id = backend.log_signal_emitted(signal, [my_test_slot])

        assert isinstance(emitted_signal_id, int)
        log_entry = EmittedSignal.query.filter_by(id=emitted_signal_id).one()
        assert log_entry.signal_type == "MyTestSignal"
        assert log_entry.signal_fields == {"value": 99}
        assert log_entry.slots == ["my_test_slot"]

    def test_log_slot_execution(self, db_session):
        backend = DatabaseBackend()
        signal_id = backend.log_signal_emitted(MyTestSignal(1), [my_test_slot])

        backend.log_slot_execution(
            emitted_signal_id=signal_id,
            slot=my_test_slot,
            status="success",
            duration_ms=77.0,
            error_message=None,
        )

        log_entry = SlotCall.query.one()
        assert log_entry.emitted_signal_id == signal_id
        assert log_entry.slot_name == "my_test_slot"
        assert log_entry.status == "success"
        assert log_entry.duration_ms == 77
        assert log_entry.error_message is None

    def test_log_slot_execution_no_emitted_signal_id(self, db_session):
        backend = DatabaseBackend()
        backend.log_slot_execution(
            emitted_signal_id=None,
            slot=my_test_slot,
            status="success",
            duration_ms=10.0,
        )
        assert SlotCall.query.count() == 0
