"""Steam owned-library cache and Web API parsing tests."""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import core
import db


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class SteamApiTests(unittest.TestCase):
    def test_parses_owned_games(self) -> None:
        payload = {
            "response": {
                "game_count": 2,
                "games": [
                    {"appid": 220, "name": "Half-Life 2", "playtime_forever": 125},
                    {"appid": 400, "name": "Portal", "playtime_forever": 0},
                ],
            }
        }
        with patch.object(
            core,
            "http_open",
            return_value=FakeResponse(json.dumps(payload).encode()),
        ):
            games = core.fetch_steam_owned_games("key", "76561198000000000")
        self.assertEqual([game["appid"] for game in games], ["220", "400"])
        self.assertEqual(games[0]["playtime_minutes"], 125)

    def test_private_or_empty_response_is_reported(self) -> None:
        with patch.object(
            core,
            "http_open",
            return_value=FakeResponse(json.dumps({"response": {}}).encode()),
        ):
            with self.assertRaises(ValueError):
                core.fetch_steam_owned_games("key", "76561198000000000")

    def test_invalid_credentials(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.invalid", 403, "Forbidden", {}, None
        )
        with patch.object(core, "http_open", side_effect=error):
            with self.assertRaises(ValueError):
                core.fetch_steam_owned_games("bad", "76561198000000000")

    def test_installed_appids_requires_fully_installed_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-steam-") as tmp:
            root = Path(tmp)
            steamapps = root / "steamapps"
            steamapps.mkdir()
            (steamapps / "appmanifest_1.acf").write_text(
                '"AppState" { "appid" "1" "name" "Installed" '
                '"installdir" "Installed" "StateFlags" "4" '
                '"SizeOnDisk" "123456789" }',
                encoding="utf-8",
            )
            (steamapps / "appmanifest_2.acf").write_text(
                '"AppState" { "appid" "2" "name" "Updating" '
                '"installdir" "Updating" "StateFlags" "1026" }',
                encoding="utf-8",
            )
            self.assertEqual(core.steam_installed_appids(root), {"1"})
            manifests = core.read_steam_manifests(root)
            self.assertEqual(manifests[0].size, 123456789)


class SteamLibraryDatabaseTests(unittest.TestCase):
    def test_cache_round_trip_and_installed_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-steam-db-") as tmp:
            database = db.Database(Path(tmp) / "data.db")
            try:
                database.replace_steam_library(
                    [
                        {
                            "appid": "10",
                            "name": "Alpha",
                            "playtime_minutes": 60,
                            "installed": 1,
                        },
                        {
                            "appid": "20",
                            "name": "Beta",
                            "playtime_minutes": 0,
                            "installed": 0,
                        },
                    ],
                    "2026-01-01 12:00",
                )
                self.assertEqual(
                    [game["appid"] for game in database.list_steam_library()],
                    ["10", "20"],
                )
                self.assertEqual(
                    [game["appid"] for game in database.list_steam_library(installed=0)],
                    ["20"],
                )
                database.set_steam_installed({"20"})
                self.assertEqual(database.steam_library_stats(), {"total": 2, "installed": 1})
                self.assertEqual(
                    database.get_steam_library_game("20")["installed"], 1
                )
                database.set_steam_cover("20", "/tmp/cover.jpg")
                self.assertEqual(
                    database.get_steam_library_game("20")["cover_path"],
                    "/tmp/cover.jpg",
                )
                database.set_steam_size("20", 987654321)
                self.assertEqual(
                    database.get_steam_library_game("20")["size"], 987654321
                )
                database.replace_steam_library(
                    [{"appid": "20", "name": "Beta", "size": 0}], ""
                )
                self.assertEqual(
                    database.get_steam_library_game("20")["size"], 987654321
                )
            finally:
                database.close()

    def test_install_and_run_uris(self) -> None:
        self.assertEqual(core.steam_install_uri("220"), "steam://install/220")
        self.assertEqual(core.steam_run_uri("220"), "steam://run/220")
        self.assertEqual(core.steam_store_uri("220"), "steam://store/220")


if __name__ == "__main__":
    unittest.main()
