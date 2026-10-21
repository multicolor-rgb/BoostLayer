"""Winetricks backend tests (no network, no Wine required)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core
import db


class WinetricksTests(unittest.TestCase):
    def test_normalize_verbs(self) -> None:
        self.assertEqual(
            core.normalize_winetricks_verbs("physx, vcrun2022\nphysx"),
            ["physx", "vcrun2022"],
        )
        self.assertEqual(
            core.normalize_winetricks_verbs(["d3dx9", "xact"]),
            ["d3dx9", "xact"],
        )
        for invalid in ("physx;rm", "-bad", "bad$verb"):
            with self.assertRaises(ValueError):
                core.normalize_winetricks_verbs(invalid)

    def test_prefix_for_wine_and_proton(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-prefix-") as tmp:
            prefix = Path(tmp) / "game"
            wine = Path(tmp) / "wine"
            wine.touch()
            game = {"wine_prefix": str(prefix)}
            self.assertEqual(
                core.winetricks_actual_prefix(
                    game, core.RunnerInfo("wine", "Wine", str(wine))
                ),
                prefix,
            )
            self.assertEqual(
                core.winetricks_actual_prefix(
                    game, core.RunnerInfo("proton", "Proton", str(wine))
                ),
                prefix / "pfx",
            )

    def test_plan_for_wine_and_proton(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-plan-") as tmp:
            prefix = Path(tmp) / "game"
            prefix.mkdir()
            wine = Path(tmp) / "wine"
            wine.touch()
            game = {
                "wine_prefix": str(prefix),
                "runner_path": str(wine),
                "env_vars": "GAME_TEST=1",
            }
            with patch.object(core, "winetricks_path", return_value="/usr/bin/winetricks"), patch.object(
                core, "resolve_runner", return_value=core.RunnerInfo("wine", "Wine", str(wine))
            ):
                plan = core.build_winetricks_plan(db.Database(Path(tmp) / "db.sqlite"), game, "physx")
            self.assertEqual(plan.command, ("/usr/bin/winetricks", "-q", "physx"))
            self.assertEqual(plan.env["WINEPREFIX"], str(prefix))
            self.assertEqual(plan.env["WINE"], str(wine))
            self.assertEqual(plan.env["GAME_TEST"], "1")
            self.assertEqual(plan.mode, "wine")
            self.assertIsNotNone(plan.marker)

            with patch.object(core, "winetricks_path", return_value="/usr/bin/winetricks"), patch.object(
                core, "resolve_runner", return_value=core.RunnerInfo("proton", "Proton", str(wine))
            ):
                plan = core.build_winetricks_plan(db.Database(Path(tmp) / "db.sqlite"), game, ["vcrun2022"])
            self.assertEqual(plan.env["WINEPREFIX"], str(prefix / "pfx"))
            self.assertEqual(plan.env["STEAM_COMPAT_DATA_PATH"], str(prefix))
            self.assertEqual(plan.mode, "proton")

    def test_plan_for_steam_uses_protontricks(self) -> None:
        game = {"is_steam": 1, "steam_appid": "12345"}
        with patch.object(core, "protontricks_path", return_value="/usr/bin/protontricks"), patch.object(
            core, "winetricks_path", return_value="/usr/bin/winetricks"
        ):
            plan = core.build_winetricks_plan(None, game, "physx")
        self.assertEqual(
            plan.command, ("/usr/bin/protontricks", "12345", "-q", "physx")
        )
        self.assertEqual(plan.env["WINETRICKS"], "/usr/bin/winetricks")
        self.assertEqual(plan.mode, "steam")
        self.assertIsNone(plan.marker)

    def test_marker_detects_applied_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-marker-") as tmp:
            prefix = Path(tmp) / "game"
            prefix.mkdir()
            marker = prefix / core.WINETRICKS_MARKER
            plan = core.WinetricksPlan(
                command=("/bin/true",),
                env={},
                mode="wine",
                verbs=("physx",),
                state="abc123",
                prefix=prefix,
                marker=marker,
            )
            self.assertFalse(core.winetricks_applied({}, plan))
            core.write_winetricks_marker(plan)
            self.assertTrue(core.winetricks_applied({}, plan))
            marker.write_text("different\n", encoding="utf-8")
            self.assertFalse(core.winetricks_applied({}, plan))


class WinetricksDatabaseTests(unittest.TestCase):
    def test_migration_adds_winetricks_columns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-migrate-") as tmp:
            path = Path(tmp) / "data.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE library ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL, exe_path TEXT NOT NULL, "
                "runner_path TEXT NOT NULL DEFAULT '', "
                "wine_prefix TEXT NOT NULL DEFAULT '', "
                "env_vars TEXT NOT NULL DEFAULT '', "
                "launch_args TEXT NOT NULL DEFAULT '', "
                "scaling_mode TEXT NOT NULL DEFAULT 'native', "
                "fps_limit INTEGER NOT NULL DEFAULT 0, "
                "is_steam INTEGER NOT NULL DEFAULT 0, "
                "steam_appid TEXT NOT NULL DEFAULT '', "
                "cover_path TEXT NOT NULL DEFAULT '')"
            )
            connection.execute(
                "INSERT INTO library(name, exe_path) VALUES('Old', '/tmp/old.exe')"
            )
            connection.commit()
            connection.close()

            database = db.Database(path)
            try:
                row = database.get_game(1)
                self.assertEqual(row["name"], "Old")
                self.assertEqual(row["winetricks_verbs"], "")
                self.assertEqual(row["winetricks_auto"], 0)
                self.assertEqual(row["winetricks_state"], "")

                database.update_game(
                    1,
                    winetricks_verbs="physx vcrun2022",
                    winetricks_auto=1,
                    winetricks_state="abc",
                )
                row = database.get_game(1)
                self.assertEqual(row["winetricks_verbs"], "physx vcrun2022")
                self.assertEqual(row["winetricks_auto"], 1)
                self.assertEqual(row["winetricks_state"], "abc")
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
