"""Translation catalog and language-switch tests."""
from __future__ import annotations

import ast
import os
import string
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOOSTLAYER_HOME", tempfile.mkdtemp(prefix="boostlayer-i18n-tests-"))

import db  # noqa: E402
import i18n  # noqa: E402
import i18n_de  # noqa: E402
import i18n_en  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = ("main.py", "console.py", "core.py", "db.py")


def source_keys() -> set[str]:
    keys: set[str] = set()
    for filename in SOURCE_FILES:
        tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
            ):
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    keys.add(first.value)
    return keys


class TranslationTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_language_names_and_normalization(self) -> None:
        self.assertEqual(
            i18n.LANGUAGES,
            {"pl": "Polski", "en": "English", "de": "Deutsch"},
        )
        self.assertEqual(i18n.normalize_language("de_DE"), "de")
        self.assertEqual(i18n.normalize_language("en-US"), "en")
        self.assertEqual(i18n.normalize_language("fr"), "pl")

    def test_default_is_polish(self) -> None:
        i18n.set_language(None)
        self.assertEqual(i18n.get_language(), "pl")
        self.assertEqual(i18n.tr("Ustawienia globalne"), "Ustawienia globalne")

    def test_translation_and_placeholders(self) -> None:
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Ustawienia globalne"), "Global settings")
        self.assertEqual(
            i18n.tr("Usunięto runner {name}.", name="GE-Proton"),
            "Runner GE-Proton removed.",
        )
        i18n.set_language("de")
        self.assertEqual(i18n.tr("Ustawienia globalne"), "Globale Einstellungen")

    def test_unknown_key_falls_back_to_polish(self) -> None:
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Nieznany tekst testowy"), "Nieznany tekst testowy")

    def test_catalogs_cover_every_source_key(self) -> None:
        keys = source_keys()
        self.assertTrue(keys)
        self.assertTrue(keys.issubset(i18n_en.TRANSLATIONS))
        self.assertTrue(keys.issubset(i18n_de.TRANSLATIONS))
        # Display-only labels are translated through db.scaling_label().
        extra = {
            "Natywnie",
            "Retro Kineskop (CRT)",
            "PhysX (starsze gry)",
            "Visual C++ 2015–2022",
            "DirectX 9",
            "XACT",
            ".NET Framework 4.8",
            "Media Foundation",
            "Czcionki Core",
        }
        self.assertEqual(set(i18n_en.TRANSLATIONS) - keys, extra)
        self.assertEqual(set(i18n_de.TRANSLATIONS) - keys, extra)

    def test_catalog_placeholders_are_preserved(self) -> None:
        def placeholders(value: str) -> set[str]:
            return {
                field_name
                for _literal, field_name, _spec, _conversion
                in string.Formatter().parse(value)
                if field_name
            }

        for catalog, label in (
            (i18n_en.TRANSLATIONS, "EN"),
            (i18n_de.TRANSLATIONS, "DE"),
        ):
            for key, translated in catalog.items():
                try:
                    expected = placeholders(key)
                except ValueError:
                    continue
                self.assertEqual(
                    expected,
                    placeholders(translated),
                    f"placeholder mismatch in {label}: {key!r}",
                )

    def test_database_default_language(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-db-") as tmp:
            database = db.Database(Path(tmp) / "data.db")
            try:
                self.assertEqual(database.get_setting("language", "pl"), "pl")
            finally:
                database.close()

    def test_scaling_labels_are_translated(self) -> None:
        i18n.set_language("en")
        self.assertEqual(db.scaling_label("native"), "Native")
        i18n.set_language("de")
        self.assertEqual(db.scaling_label("crt"), "Retro-Röhre (CRT)")


if __name__ == "__main__":
    unittest.main()
