import logging
import os
from typing import Dict, Optional, Set

from babel import Locale
from polib import POFile, POEntry, pofile, mofile

from ..llm import query_llm

logger = logging.getLogger(__name__)

_catalog_path: Optional[str] = None


def init_catalog(path: str):
    """Initializes the path to the message catalogs."""
    global _catalog_path
    _catalog_path = path
    logger.info(f"Message catalog path set to: {_catalog_path}")


class TranslatableString:
    """
    Represents a string that can be translated. Instances are registered
    globally to be collected into a .po file.

    The concept is this:

    - a delayed string class gets and stores English strings
    - there is a function which collects all the declared entities of this class and saves them in a `.pot` file;
    - There is a function to resolve the delayed string, which takes it and the locale and returns the string in a given language.
    - Language files are stored in `data/locale/` folder in gettext `.po` format.
    - The resolving function implements lazy-loading of language files: a language file is loaded when the user with this language makes a request.
    - There is support for translating on demand: if a user with a new language appears, the background translation is started via some external api (e.g. Google Translate or an OpenAI-compatible LLM) and, when finished, is saved into a new language file.
    - If a delayed string is not resolved till the time of usage, it defaults to its English value.
    - Delayed strings behave like regulr strings as much as possible, e.g. they're serializable.
    - This mechanics tries to be compliant with gettext logic and file format, but allows fine control of strings resolution and simplifies generating new translations.
    - If an application is started without any `.po` files, it generates them on the fly not bothering the user, and generates translation files on demand, allowing to improve the translation later.

    Example workflow:

    1.  *Developer*: Adds `NEW_FEATURE_PROMPT = TranslatableString("Please enable the new feature.")` to `app/features/new.py`.
    2.  *Developer*: Runs `python scripts/collect_strings.py`. The `messages.pot` file is updated with the new string.
    3.  *User A (locale: `es`)*: Interacts with the bot. The feature prompt needs to be displayed.
    4.  *System*: `ctx.resolve(NEW_FEATURE_PROMPT)` is called.
    5.  *System*: `Context` checks for `data/locale/es/LC_MESSAGES/messages.mo`. It doesn't exist.
    6.  *System*: A background task is launched to translate all strings in `messages.pot` to Spanish and create `messages.po`/`.mo`.
    7.  *System*: For the current request, `resolve` falls back and returns the English string: "Please enable the new feature.".
    8.  *User B (locale: `es`)*: Later makes a request that also requires the same prompt.
    9.  *System*: By now, the background task has finished, and `messages.mo` exists.
    10. *System*: `Context` lazy-loads `data/locale/es/LC_MESSAGES/messages.mo` into its cache.
    11. *System*: `resolve` now looks up the string and returns the Spanish version: "Por favor, active la nueva función.".

    """

    _registry: Set["TranslatableString"] = set()

    def __init__(self, msgid: str, comment: Optional[str] = None, **kwargs):
        if not isinstance(msgid, str) or not msgid:
            raise ValueError("msgid must be a non-empty string.")
        self.msgid = msgid
        self.comment = comment
        self.kwargs = kwargs
        self._registry.add(self)

    def __str__(self) -> str:
        # Default to the English msgid if not resolved.
        return self.msgid.format(**self.kwargs)

    def __repr__(self) -> str:
        return f"TranslatableString('{self.msgid}')"

    def __hash__(self):
        return hash(self.msgid)

    def __eq__(self, other):
        return (
            isinstance(other, TranslatableString) and self.msgid == other.msgid
        )


_translation_cache: Dict[Locale, Optional[POFile]] = {}

# The flow:
# no file -> no entry -> entry without translation -> entry with translation


def _init_catalog(locale: Locale) -> POFile:
    """
    Create a new POFile from TranslatableStrings registry and write it
    to the .po file.
    """
    if _catalog_path is None:
        raise RuntimeError(
            "Catalog path not initialized. Call init_catalog first."
        )
    po_file = POFile()
    po_file.metadata = {
        "Project-Id-Version": "1.0",
        "Report-Msgid-Bugs-To": "EMAIL@ADDRESS",
        "POT-Creation-Date": "2027-10-28 14:00+0000",
        "PO-Revision-Date": "2027-10-28 14:00+0000",
        "Last-Translator": "FULL NAME <EMAIL@ADDRESS>",
        "Language-Team": "LANGUAGE <LL@li.org>",
        "Language": str(locale),
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Transfer-Encoding": "8bit",
    }

    for ts in sorted(
        list(TranslatableString._registry), key=lambda x: x.msgid
    ):
        entry = POEntry(msgid=ts.msgid, msgstr="", comment=ts.comment or "")
        po_file.append(entry)

    po_path = os.path.join(
        _catalog_path, str(locale), "LC_MESSAGES", "messages.po"
    )
    os.makedirs(os.path.dirname(po_path), exist_ok=True)

    try:
        po_file.save(po_path)
        po_file.fpath = po_path
        logger.info(
            f"Created and saved a new catalog for locale '{str(locale)}' at {po_path}"
        )
    except OSError as e:
        logger.error(
            f"Failed to save catalog for locale '{str(locale)}' at {po_path}: {e}"
        )
        return POFile()

    return po_file


def _get_catalog(locale: Locale) -> Optional[POFile]:
    """
    Open .po catalog if it exists, otherwise create a new one from
    TranslatableStrings registry and write it to the file.
    """
    if _catalog_path is None:
        raise RuntimeError(
            "Catalog path not initialized. Call init_catalog first."
        )
    translations = _translation_cache.get(locale)
    if translations is None and locale not in _translation_cache:
        # Not in cache, attempt to load
        locale_str = str(locale)
        po_path = os.path.join(
            _catalog_path, locale_str, "LC_MESSAGES", "messages.po"
        )
        mo_path = os.path.join(
            _catalog_path, locale_str, "LC_MESSAGES", "messages.mo"
        )

        try:
            # Prefer .po for modifiability
            if os.path.exists(po_path):
                translations = pofile(po_path)
                logger.info("Loaded .po file for locale %s", locale_str)
            elif os.path.exists(mo_path):
                translations = mofile(mo_path)
                logger.info("Loaded .mo file for locale %s", locale_str)
            else:
                logger.warning(
                    "No .po or .mo file found for locale %s", locale_str
                )
                translations = _init_catalog(locale)
        except Exception as e:
            logger.error(
                "Failed to load translation file for locale %s: %s",
                locale_str,
                e,
            )
            translations = None

        _translation_cache[locale] = translations
    return translations


def _update_catalog(
    catalog: POFile,
    string: TranslatableString,
    translation: Optional[str] = None,
):
    """Add entry to the catalog — with or without translation — and save the catalog to disk."""
    if not hasattr(catalog, "fpath") or not catalog.fpath:
        logger.error(
            "Cannot update catalog: The catalog object has no file path. "
            "It might have been loaded from a .mo file or is an in-memory object."
        )
        return

    po_path = catalog.fpath
    mo_path = os.path.splitext(po_path)[0] + ".mo"

    os.makedirs(os.path.dirname(po_path), exist_ok=True)

    entry = catalog.find(string.msgid)
    needs_save = False

    if entry:
        if translation is not None and entry.msgstr != translation:
            entry.msgstr = translation
            logger.info(
                f"Updated translation for '{entry.msgid}' in {po_path}"
            )
            needs_save = True
    else:
        entry = POEntry(
            msgid=string.msgid,
            msgstr=translation or "",
            comment=string.comment or "",
        )
        catalog.append(entry)
        logger.info(f"Added new string '{string.msgid}' to {po_path}")
        needs_save = True

    if needs_save:
        try:
            catalog.save(po_path)
            catalog.save_as_mofile(mo_path)
            logger.info(
                f"Saved catalog to {po_path} and compiled to {mo_path}"
            )
        except OSError as e:
            logger.error(
                f"Failed to save catalog file {po_path} or {mo_path}: {e}"
            )

    return entry


async def _translate(
    text: str,
    src_language: str,
    dst_language: str = "English",
    comment: Optional[str] = None,
) -> str:
    """
    Translate text from a source language to a destination language using LLM.

    Args:
        text (str): The text to translate.
        src_language (str): The source language of the text.
        dst_language (str, optional): The target language for the translation. Defaults to English.

    Returns:
        str: The translated text.
    """

    logger.info(
        "Translating text from '%s' to '%s': '%s' (%s)",
        src_language,
        dst_language,
        text,
        comment,
    )

    instructions = f"""Translate the following text from {src_language} to {dst_language}.
Ensure the translation captures the original meaning as accurately as possible.
If you find any markup in the text, keep it intact.

Examples (for translations from English to Russian):
- Continue - Продолжить
- Exit - Выход
- Choose Your Language - Выберите язык"""
    if comment:
        instructions += f"\n\n(Context: {comment})"

    translation = await query_llm(instructions, text)
    logger.info("Received translation: '%s'", translation)
    return translation


async def resolve(string: TranslatableString, locale: Optional[Locale]) -> str:
    """
    Get the translation from data/locale/*.po file or return the English default.
    Implements lazy-loading and caching of translation files.
    """
    logger.info("Got translation request for the locale: %s", locale)
    if not isinstance(string, TranslatableString):
        raise TypeError("resolve() expects a TranslatableString instance.")

    if locale is None or locale.language == "en":
        return str(string).format(**string.kwargs)

    if not (translations := _get_catalog(locale)):
        return str(string).format(**string.kwargs)

    if not (entry := translations.find(string.msgid)):
        entry = _update_catalog(translations, string, None)

    # If we already done the translation, format it and return the result.
    if entry.msgstr:
        return entry.msgstr.format(**string.kwargs)

    # If the translation is missing, try to translate,
    # otherwise default to english version.
    try:
        translation = await _translate(
            string.msgid,
            src_language="English",
            dst_language=locale.english_name,
            comment=string.comment,
        )
        _update_catalog(translations, string, translation)
        return translation.format(**string.kwargs)
    except Exception as e:
        logging.debug("Translation service unavailable: %s.", e)
        return str(string.msgid).format(**string.kwargs)
