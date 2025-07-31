import asyncio
import os
import pytest
from unittest.mock import patch

from babel import Locale
from polib import pofile

from . import catalog
from .catalog import (
    TranslatableString,
    init_catalog,
    resolve,
    _get_catalog,
    _update_catalog,
)


@pytest.fixture(autouse=True)
def i18n_test_setup(tmp_path):
    """
    This fixture runs for every test. It initializes the catalog path to a
    temporary directory and clears the TranslatableString registry and
    translation cache to ensure test isolation.
    """
    init_catalog(str(tmp_path))
    TranslatableString._registry.clear()
    catalog._translation_cache.clear()
    yield
    TranslatableString._registry.clear()
    catalog._translation_cache.clear()


class TestTranslatableString:
    """Tests for the TranslatableString class."""

    def test_creation_and_properties(self):
        """Test basic creation and properties of TranslatableString."""
        ts = TranslatableString("Hello", "A greeting")
        assert ts.msgid == "Hello"
        assert ts.comment == "A greeting"
        assert str(ts) == "Hello"
        assert repr(ts) == "TranslatableString('Hello')"

    def test_registry(self):
        """Test that instances are added to the global registry."""
        assert len(TranslatableString._registry) == 0
        ts1 = TranslatableString("Test 1")
        ts2 = TranslatableString("Test 2")
        assert len(TranslatableString._registry) == 2
        assert ts1 in TranslatableString._registry
        assert ts2 in TranslatableString._registry

    def test_uniqueness_in_registry(self):
        """Test that the registry handles strings with the same msgid."""
        TranslatableString("Test 1")
        TranslatableString("Test 1")
        assert len(TranslatableString._registry) == 1
        assert {ts.msgid for ts in TranslatableString._registry} == {"Test 1"}

    def test_equality_and_hash(self):
        """Test equality and hashing based on msgid."""
        ts1a = TranslatableString("One")
        ts1b = TranslatableString("One")
        ts2 = TranslatableString("Two")
        assert ts1a == ts1b
        assert ts1a != ts2
        assert hash(ts1a) == hash(ts1b)
        assert hash(ts1a) != hash(ts2)
        s = {ts1a, ts1b, ts2}
        assert len(s) == 2

    def test_invalid_msgid(self):
        """Test that creating a TranslatableString with an invalid msgid raises ValueError."""
        with pytest.raises(
            ValueError, match="msgid must be a non-empty string."
        ):
            TranslatableString("")
        with pytest.raises(
            ValueError, match="msgid must be a non-empty string."
        ):
            TranslatableString(None)


class TestCatalogManagement:
    """Tests for catalog file creation, loading, and updating."""

    def test_init_and_create_new_catalog(self, tmp_path):
        """
        Test that _get_catalog triggers the creation of a new .po file
        from the registry when one does not exist.
        """
        locale = Locale("es")
        po_path = tmp_path / "es" / "LC_MESSAGES" / "messages.po"

        TranslatableString("Welcome", "A welcome message")
        TranslatableString("Goodbye")

        assert not po_path.exists()
        catalog_obj = _get_catalog(locale)

        assert catalog_obj is not None
        assert po_path.exists()

        loaded_po = pofile(str(po_path))
        assert len(loaded_po) == 2
        entry1 = loaded_po.find("Welcome")
        assert entry1.msgid == "Welcome"
        assert entry1.msgstr == ""
        assert entry1.comment == "A welcome message"
        entry2 = loaded_po.find("Goodbye")
        assert entry2.msgid == "Goodbye"
        assert entry2.msgstr == ""
        assert entry2.comment == ""

    def test_get_existing_po_file(self, tmp_path):
        """Test loading an existing .po file."""
        locale = Locale("fr")
        locale_dir = tmp_path / "fr" / "LC_MESSAGES"
        locale_dir.mkdir(parents=True)
        po_path = locale_dir / "messages.po"
        po_path.write_text(
            'msgid "Hello"\n' 'msgstr "Bonjour"\n', encoding="utf-8"
        )

        catalog_obj = _get_catalog(locale)

        assert catalog_obj is not None
        entry = catalog_obj.find("Hello")
        assert entry is not None
        assert entry.msgstr == "Bonjour"

    def test_update_catalog_add_and_update_entry(self, tmp_path):
        """Test adding a new entry and updating an existing one."""
        locale = Locale("de")
        po_path = tmp_path / "de" / "LC_MESSAGES" / "messages.po"

        ts_existing = TranslatableString("Existing")
        catalog_obj = _get_catalog(locale)
        assert catalog_obj.find("Existing") is not None
        assert catalog_obj.find("New") is None

        ts_new = TranslatableString("New", "A new string")
        _update_catalog(catalog_obj, ts_new, "Neu")
        _update_catalog(catalog_obj, ts_existing, "Bestehend")

        assert catalog_obj.find("New").msgstr == "Neu"
        assert catalog_obj.find("Existing").msgstr == "Bestehend"

        loaded_po = pofile(str(po_path))
        assert loaded_po.find("New").msgstr == "Neu"
        assert loaded_po.find("Existing").msgstr == "Bestehend"


@pytest.mark.asyncio
class TestResolve:
    """Tests for the async resolve() function."""

    async def test_resolve_default_locales(self):
        """Test that resolve() returns the msgid for English or None locales."""
        ts = TranslatableString("Test")
        assert await resolve(ts, None) == "Test"
        assert await resolve(ts, Locale("en")) == "Test"
        assert await resolve(ts, Locale("en", "US")) == "Test"

    async def test_resolve_with_existing_translation(self, tmp_path):
        """Test resolving a string that has a translation in the .po file."""
        locale = Locale("es")
        locale_dir = tmp_path / "es" / "LC_MESSAGES"
        locale_dir.mkdir(parents=True)
        po_path = locale_dir / "messages.po"
        po_path.write_text(
            'msgid "Welcome"\n' 'msgstr "Bienvenido"\n', encoding="utf-8"
        )

        ts = TranslatableString("Welcome")
        result = await resolve(ts, locale)
        assert result == "Bienvenido"

    @patch("nachricht.i18n.catalog._translate")
    async def test_resolve_triggers_online_translation(
        self, mock_translate, tmp_path
    ):
        """Test that resolve() calls the translation service for a missing translation."""

        async def translator(*args, **kwargs):
            return "Bonjour"

        mock_translate.side_effect = translator

        locale = Locale("fr")
        po_path = tmp_path / "fr" / "LC_MESSAGES" / "messages.po"
        mo_path = tmp_path / "fr" / "LC_MESSAGES" / "messages.mo"
        ts = TranslatableString("Hello", "A greeting")

        result = await resolve(ts, locale)

        assert result == "Bonjour"
        mock_translate.assert_awaited_once_with(
            "Hello",
            src_language="English",
            dst_language="French",
            comment="A greeting",
        )
        assert po_path.exists()
        assert mo_path.exists()

        loaded_po = pofile(str(po_path))
        assert loaded_po.find("Hello").msgstr == "Bonjour"

        mock_translate.reset_mock()
        result2 = await resolve(ts, locale)
        assert result2 == "Bonjour"
        mock_translate.assert_not_awaited()

    @patch("nachricht.i18n.catalog._translate")
    async def test_resolve_fallback_on_translation_failure(
        self, mock_translate
    ):
        """Test that resolve() returns None if translation fails."""

        async def translator(*args, **kwargs):
            raise Exception("API down")

        mock_translate.side_effect = translator

        locale = Locale("de")
        ts = TranslatableString("Failure")

        result = await resolve(ts, locale)
        assert result == ts.msgid
        mock_translate.assert_awaited_once_with(
            "Failure",
            src_language="English",
            dst_language="German",
            comment=None,
        )

        result2 = await resolve(ts, locale)
        assert result2 == ts.msgid
        assert mock_translate.call_count == 2

    async def test_resolve_raises_type_error_for_invalid_input(self):
        """Test that resolve() raises TypeError for non-TranslatableString input."""
        with pytest.raises(TypeError):
            await resolve("not a translatable string", Locale("es"))
