"""Lightweight runtime translation layer for Boostlayer.

Polish is the source language: the strings passed to :func:`tr` are the
canonical keys.  English and German catalogs live in plain Python modules so
PyInstaller bundles them automatically and no external translation tooling is
required.

The fallback is deliberately safe: an unknown key (or an unknown language)
always returns the original Polish text.
"""
from __future__ import annotations

from typing import Any

LANGUAGES: dict[str, str] = {
    "pl": "Polski",
    "en": "English",
    "de": "Deutsch",
}
DEFAULT_LANGUAGE = "pl"

_current_language = DEFAULT_LANGUAGE

try:
    from i18n_en import TRANSLATIONS as _EN
except ImportError:  # pragma: no cover - only possible in a broken install
    _EN = {}

try:
    from i18n_de import TRANSLATIONS as _DE
except ImportError:  # pragma: no cover - only possible in a broken install
    _DE = {}

_CATALOGS: dict[str, dict[str, str]] = {
    "pl": {},
    "en": _EN,
    "de": _DE,
}


def normalize_language(code: str | None) -> str:
    """Return a supported language code, falling back to Polish."""
    normalized = (code or "").strip().lower().replace("_", "-")
    if normalized in LANGUAGES:
        return normalized
    # Accept locale variants such as en-US / de_DE.
    base = normalized.split("-", 1)[0]
    return base if base in LANGUAGES else DEFAULT_LANGUAGE


def set_language(code: str | None) -> str:
    """Activate a language and return the normalized code."""
    global _current_language
    _current_language = normalize_language(code)
    return _current_language


def get_language() -> str:
    return _current_language


def language_name(code: str) -> str:
    return LANGUAGES.get(normalize_language(code), LANGUAGES[DEFAULT_LANGUAGE])


def tr(text: str, **params: Any) -> str:
    """Translate *text* into the active language.

    Dynamic messages use ``{}`` placeholders, e.g.::

        tr("Usunięto runner {name}.", name=root.name)

    Missing keys and malformed placeholders fail open to the source string so a
    translation problem can never break a launcher action.
    """
    if not isinstance(text, str):
        return text
    if _current_language == DEFAULT_LANGUAGE:
        translated = text
    else:
        translated = _CATALOGS.get(_current_language, {}).get(text, text)
    if params:
        try:
            translated = translated.format(**params)
        except (KeyError, IndexError, ValueError):
            try:
                translated = text.format(**params)
            except (KeyError, IndexError, ValueError):
                pass
    return translated
