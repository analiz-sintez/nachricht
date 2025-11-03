import pytest
from babel import Locale

from .backends import MemoryContextStore
from .models import Account, Chat, Message, Conversation


@pytest.fixture(autouse=True)
def clean_memory_store():
    """Clears the class-level dictionaries in MemoryContextStore before each test."""
    MemoryContextStore._messages.clear()
    MemoryContextStore._conversations.clear()
    MemoryContextStore._chats.clear()
    MemoryContextStore._accounts.clear()
    yield


@pytest.fixture
def store():
    return MemoryContextStore()


@pytest.fixture
def account1():
    return Account(id=101, login="user1", locale=Locale("en"))


@pytest.fixture
def account2():
    return Account(id=102, login="user2", locale=Locale("de"))


@pytest.fixture
def chat1():
    return Chat(id=201)


@pytest.fixture
def message_a1_c1(account1, chat1):
    return Message(id=301, chat_id=chat1.id, user_id=account1.id)


@pytest.fixture
def message_a2_c1(account2, chat1):
    return Message(id=302, chat_id=chat1.id, user_id=account2.id)


@pytest.fixture
def conversation_a1_c1(account1, chat1):
    return Conversation(id=401, chat_id=chat1.id, account_id=account1.id)


@pytest.fixture
def conversation_a2_c1(account2, chat1):
    return Conversation(id=402, chat_id=chat1.id, account_id=account2.id)


class TestMemoryContextStoreIndividualObjects:
    """Tests basic context getting and setting for each object type."""

    def test_account_context(self, store, account1):
        ctx = store[account1]
        assert ctx == {}
        ctx["key"] = "value"
        assert store[account1]["key"] == "value"

    def test_chat_context(self, store, chat1):
        ctx = store[chat1]
        assert ctx == {}
        ctx["setting"] = True
        assert store[chat1]["setting"] is True

    def test_message_context(self, store, message_a1_c1):
        ctx = store[message_a1_c1]
        assert ctx == {}
        ctx["on_reply"] = "signal_data"
        assert store[message_a1_c1]["on_reply"] == "signal_data"

    def test_conversation_context(self, store, conversation_a1_c1):
        ctx = store[conversation_a1_c1]
        assert ctx == {}
        ctx["state"] = "onboarding"
        assert store[conversation_a1_c1]["state"] == "onboarding"

    def test_context_is_mutable_reference(self, store, account1):
        """Tests that modifying a retrieved context dict persists changes."""
        ctx1 = store[account1]
        ctx1["counter"] = 1
        ctx2 = store[account1]
        assert ctx2["counter"] == 1
        ctx2["counter"] += 1
        assert ctx1["counter"] == 2


class TestMemoryContextStoreIsolation:
    """
    Tests that contexts are correctly isolated or shared between different
    objects as expected.
    """

    def test_chat_context_is_shared(self, store, chat1):
        """Context for a chat is shared, regardless of who accesses it."""
        chat_ctx = store[chat1]
        chat_ctx["topic"] = "general"
        assert store[chat1]["topic"] == "general"

    def test_account_context_is_isolated(self, store, account1, account2):
        """Contexts for different accounts must be separate."""
        store[account1]["theme"] = "dark"
        assert "theme" not in store[account2]
        assert store[account1]["theme"] == "dark"

    def test_message_context_is_isolated(
        self, store, message_a1_c1, message_a2_c1
    ):
        """Contexts for different messages must be separate."""
        store[message_a1_c1]["handled"] = True
        assert "handled" not in store[message_a2_c1]
        assert store[message_a1_c1]["handled"] is True

    def test_conversation_context_is_isolated(
        self, store, conversation_a1_c1, conversation_a2_c1
    ):
        """Contexts for different conversations must be separate."""
        store[conversation_a1_c1]["step"] = 5
        assert "step" not in store[conversation_a2_c1]
        assert store[conversation_a1_c1]["step"] == 5


class TestMemoryContextStoreEdgeCases:
    """Tests behavior with invalid or unsupported inputs."""

    def test_unsupported_type_returns_none(self, store, caplog):
        """An object not of a known type should return None and log an error."""
        unsupported_obj = object()
        assert store[unsupported_obj] is None
        assert "Unsupported context type" in caplog.text

    def test_none_object_returns_none(self, store):
        """Passing None should safely return None."""
        assert store[None] is None
