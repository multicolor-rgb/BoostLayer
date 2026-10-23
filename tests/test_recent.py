"""Last-played bookkeeping used by the 'Continue' row."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOOSTLAYER_HOME", tempfile.mkdtemp(prefix="boostlayer-recent-"))

import db  # noqa: E402


class RecentGamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = db.Database()

    def tearDown(self) -> None:
        self.database.close()

    def test_touch_orders_recent_games(self) -> None:
        first = self.database.add_game(name="Recent A", exe_path="/tmp/recent-a.exe")
        second = self.database.add_game(name="Recent B", exe_path="/tmp/recent-b.exe")
        self.database.touch_last_played(first)
        self.database.touch_last_played(second)
        names = [game["name"] for game in self.database.recent_games(limit=50)]
        self.assertLess(names.index("Recent B"), names.index("Recent A"))
        self.assertTrue(self.database.get_game(first)["last_played"])

    def test_recent_limit(self) -> None:
        ids = [
            self.database.add_game(name=f"Limit {i}", exe_path=f"/tmp/limit-{i}.exe")
            for i in range(8)
        ]
        for game_id in ids:
            self.database.touch_last_played(game_id)
        self.assertEqual(len(self.database.recent_games(limit=6)), 6)

    def test_migration_adds_last_played_to_old_database(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="boostlayer-legacy-")) / "boostlayer.db"
        legacy = db.Database(path)
        game_id = legacy.add_game(name="Legacy", exe_path="/tmp/legacy.exe")
        legacy.close()
        with sqlite3.connect(path) as connection:
            connection.execute("ALTER TABLE library DROP COLUMN last_played")
        upgraded = db.Database(path)
        self.addCleanup(upgraded.close)
        game = upgraded.get_game(game_id)
        self.assertIsNotNone(game)
        self.assertEqual(game["last_played"], "")
        upgraded.touch_last_played(game_id)
        self.assertEqual(
            [entry["name"] for entry in upgraded.recent_games()], ["Legacy"]
        )


if __name__ == "__main__":
    unittest.main()
