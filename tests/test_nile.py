"""Amazon Games / nile parsing, database and runtime integration tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault(
    "BOOSTLAYER_HOME", tempfile.mkdtemp(prefix="boostlayer-amazon-tests-")
)

import amazon  # noqa: E402
import core  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402


class RedirectParsingTests(unittest.TestCase):
    def test_extracts_code_from_full_redirect_url(self) -> None:
        url = (
            "https://www.amazon.com/ap/maplanding"
            "?openid.oa2.authorization_code=ANAgbGdn&openid.mode=id_res"
        )
        self.assertEqual(amazon.parse_login_redirect(url), "ANAgbGdn")

    def test_accepts_raw_code(self) -> None:
        self.assertEqual(amazon.parse_login_redirect("  ABC-123_xyz  "), "ABC-123_xyz")

    def test_returns_empty_for_url_without_code(self) -> None:
        self.assertEqual(amazon.parse_login_redirect("https://www.amazon.com/"), "")

    def test_empty_input(self) -> None:
        self.assertEqual(amazon.parse_login_redirect("   "), "")


class ProgressParsingTests(unittest.TestCase):
    def test_parses_all_fields(self) -> None:
        line = (
            "= Progress: 42.50 1234/5678, Running for: 00:00:30, "
            "ETA: 00:01:20"
        )
        data = amazon.parse_progress(line)
        self.assertEqual(data["percent"], 42.5)
        self.assertEqual(data["eta"], "00:01:20")
        self.assertNotIn("downloaded", data)

    def test_parses_percent_sign_and_speeds(self) -> None:
        line = (
            "Progress: 42.5 % ETA: 00:01:20 Downloaded: 123.4 MiB "
            "Download\t- 5.2 MiB/s Disk\t- 9.1 MiB/s"
        )
        data = amazon.parse_progress(line)
        self.assertEqual(data["percent"], 42.5)
        self.assertEqual(data["eta"], "00:01:20")
        self.assertEqual(data["downloaded"], "123.4 MiB")
        self.assertIn("5.2", data["download_speed"])
        self.assertIn("9.1", data["disk_speed"])

    def test_ignores_unrelated_lines(self) -> None:
        self.assertEqual(amazon.parse_progress("INFO [DOWNLOAD]: started"), {})


class ToolSelectionTests(unittest.TestCase):
    def test_selects_x86_64(self) -> None:
        assets = [
            {"name": "nile_linux_arm64"},
            {"name": "nile_linux_x86_64"},
        ]
        self.assertEqual(
            amazon.select_nile_asset(assets, "x86_64")["name"],
            "nile_linux_x86_64",
        )

    def test_selects_arm64(self) -> None:
        assets = [{"name": "nile_linux_arm64"}]
        self.assertEqual(
            amazon.select_nile_asset(assets, "aarch64")["name"],
            "nile_linux_arm64",
        )

    def test_missing_asset(self) -> None:
        self.assertIsNone(amazon.select_nile_asset([], "x86_64"))


class LibraryParsingTests(unittest.TestCase):
    def test_normalizes_entries_and_installed_state(self) -> None:
        entries = [
            {
                "id": "entitlement-1",
                "product": {
                    "id": "product-1",
                    "title": "Example Game",
                    "productDetail": {
                        "iconUrl": "https://example.invalid/icon.png",
                        "details": {
                            "shortDescription": "Short description",
                            "developer": "Example Studio",
                            "backgroundUrl2": "https://example.invalid/cover.jpg",
                        },
                    },
                },
            },
            {"product": {"id": "", "title": "Broken"}},
            "not-a-dict",
        ]
        installed = {
            "product-1": {"path": "/games/example", "version": "1.2", "size": 1234}
        }
        games = amazon.normalize_library(entries, installed)
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game["product_id"], "product-1")
        self.assertEqual(game["entitlement_id"], "entitlement-1")
        self.assertEqual(game["title"], "Example Game")
        self.assertEqual(game["developer"], "Example Studio")
        self.assertEqual(game["cover_url"], "https://example.invalid/cover.jpg")
        self.assertEqual(game["installed"], 1)
        self.assertEqual(game["install_path"], "/games/example")
        self.assertEqual(game["version"], "1.2")
        self.assertEqual(game["size"], 1234)

    def test_not_installed_entry(self) -> None:
        entries = [{"id": "e", "product": {"id": "p", "title": "T"}}]
        game = amazon.normalize_library(entries, {})[0]
        self.assertEqual(game["installed"], 0)
        self.assertEqual(game["install_path"], "")


class LaunchSpecTests(unittest.TestCase):
    def test_parses_json_output(self) -> None:
        payload = {
            "command": {
                "instruction": "/games/example/game.exe",
                "arguments": ["-windowed", "+fps_max 144"],
            },
            "game_directory": "/games/example",
            "env": {
                "FUEL_DIR": "/sdk/Legacy",
                "AMAZON_GAMES_SDK_PATH": "/sdk/AmazonGamesSDK",
            },
        }
        spec = amazon.parse_launch_spec(payload)
        self.assertEqual(spec["command"], "/games/example/game.exe")
        self.assertEqual(spec["arguments"], ["-windowed", "+fps_max 144"])
        self.assertEqual(spec["cwd"], "/games/example")
        self.assertEqual(spec["env"]["FUEL_DIR"], "/sdk/Legacy")

    def test_rejects_missing_command(self) -> None:
        with self.assertRaises(amazon.NileError):
            amazon.parse_launch_spec({"command": {}})

    def test_fuel_json5_working_dir_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-fuel-") as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            (root / "fuel.json").write_text(
                """
                {
                    // Amazon ships JSON5, not strict JSON.
                    "SchemaVersion": 1,
                    "Main": {
                        "Command": "game.exe",
                        "Args": [],
                        "WorkingSubdirOverride": "bin",
                    },
                }
                """,
                encoding="utf-8",
            )
            spec = amazon.parse_launch_spec(
                {
                    "command": {"instruction": str(root / "game.exe")},
                    "game_directory": str(root),
                    "env": {},
                },
                root,
            )
            self.assertEqual(spec["cwd"], str(root / "bin"))


class FakeNileTests(unittest.TestCase):
    def _fake_nile(self, root: Path, body: str) -> Path:
        script = root / "nile"
        script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        script.chmod(0o755)
        return script

    def test_auth_status_parses_json_after_logs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-nile-") as tmp:
            script = self._fake_nile(
                Path(tmp),
                "echo 'INFO [AUTH_MANAGER]: checking'\n"
                "echo '{\"Username\":\"Tester\",\"LoggedIn\":true}'\n",
            )
            status = amazon.auth_status(script)
            self.assertTrue(status["logged_in"])
            self.assertEqual(status["username"], "Tester")

    def test_auth_status_not_logged_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-nile-") as tmp:
            script = self._fake_nile(
                Path(tmp),
                "echo '{\"Username\":\"<not logged in>\",\"LoggedIn\":false}'\n",
            )
            status = amazon.auth_status(script)
            self.assertFalse(status["logged_in"])

    def test_begin_login_parses_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-nile-") as tmp:
            payload = {
                "url": "https://www.amazon.com/ap/signin?x=1",
                "client_id": "abc",
                "code_verifier": "def",
                "serial": "123",
            }
            script = self._fake_nile(
                Path(tmp), f"echo '{json.dumps(payload)}'\n"
            )
            data = amazon.begin_login(script)
            self.assertEqual(data["client_id"], "abc")
            self.assertEqual(data["serial"], "123")

    def test_missing_binary_raises(self) -> None:
        with self.assertRaises(amazon.NileError):
            amazon.run_nile(["--version"], "/nonexistent/nile")

    def test_current_user_reads_config(self) -> None:
        directory = amazon.nile_config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "current_user.json"
        path.write_text(
            json.dumps({"name": "Tester", "user_id": "u1"}), encoding="utf-8"
        )
        try:
            user = amazon.current_user()
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(user, {"name": "Tester", "user_id": "u1"})

    def test_install_exact_path_uses_nile_path_flag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-nile-") as tmp:
            root = Path(tmp)
            args_file = root / "args.txt"
            script = self._fake_nile(
                root, f'echo "$@" > "{args_file}"\nexit 0\n'
            )
            result = amazon.install_game(
                script, "prod1", exact_path=root / "My Game"
            )
            self.assertTrue(result["ok"])
            args = args_file.read_text(encoding="utf-8")
            self.assertIn("--path", args)
            self.assertIn("My Game", args)
            self.assertNotIn("--base-path", args)


class AmazonDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = db.Database()

    def tearDown(self) -> None:
        self.database.close()

    def test_catalog_replace_and_stats(self) -> None:
        games = [
            {
                "product_id": "p1",
                "title": "Game One",
                "installed": 1,
                "install_path": "/games/one",
                "version": "1.0",
                "size": 100,
            },
            {"product_id": "p2", "title": "Game Two", "installed": 0},
        ]
        self.database.replace_amazon_library(games, "2026-01-01 10:00")
        self.assertEqual(self.database.amazon_library_stats(), {"total": 2, "installed": 1})
        items = self.database.list_amazon_library()
        self.assertEqual([item["product_id"] for item in items], ["p1", "p2"])
        one = self.database.get_amazon_library_game("p1")
        assert one is not None
        self.assertEqual(one["install_path"], "/games/one")
        self.assertEqual(one["size"], 100)
        self.assertEqual(self.database.list_amazon_library(installed=0)[0]["product_id"], "p2")

    def test_spec_cache_survives_library_replace(self) -> None:
        self.database.replace_amazon_library(
            [{"product_id": "p1", "title": "Game One"}], ""
        )
        spec = '{"command": "/games/one/game.exe", "arguments": []}'
        self.database.set_amazon_spec("p1", spec)
        self.database.replace_amazon_library(
            [{"product_id": "p1", "title": "Game One", "installed": 1}], ""
        )
        game = self.database.get_amazon_library_game("p1")
        assert game is not None
        self.assertEqual(game["spec_json"], spec)

    def test_upsert_preserves_user_settings(self) -> None:
        game_id, created = self.database.upsert_amazon_game(
            name="Amazon Game",
            exe_path="/games/amazon/game.exe",
            is_amazon=1,
            amazon_id="p1",
            scaling_mode="crt",
            fps_limit=60,
        )
        self.assertTrue(created)
        self.database.update_game(
            game_id, runner_path="/runners/wine", wine_prefix="/prefixes/p1"
        )
        _, created_again = self.database.upsert_amazon_game(
            name="Amazon Game Renamed",
            exe_path="/games/amazon/new.exe",
            is_amazon=1,
            amazon_id="p1",
            scaling_mode="native",
            fps_limit=0,
        )
        self.assertFalse(created_again)
        game = self.database.find_amazon_game("p1")
        assert game is not None
        self.assertEqual(game["name"], "Amazon Game Renamed")
        self.assertEqual(game["exe_path"], "/games/amazon/new.exe")
        self.assertEqual(game["scaling_mode"], "crt")
        self.assertEqual(game["fps_limit"], 60)
        self.assertEqual(game["runner_path"], "/runners/wine")
        self.assertEqual(game["wine_prefix"], "/prefixes/p1")

    def test_update_install_and_delete(self) -> None:
        self.database.replace_amazon_library(
            [{"product_id": "p1", "title": "Game"}], ""
        )
        self.database.update_amazon_install(
            "p1", installed=True, install_path="/games/p1", version="2", size=500
        )
        game = self.database.get_amazon_library_game("p1")
        assert game is not None
        self.assertEqual(game["installed"], 1)
        self.assertEqual(game["version"], "2")
        self.database.upsert_amazon_game(
            name="Game", exe_path="/games/p1/game.exe", is_amazon=1, amazon_id="p1"
        )
        self.assertIsNotNone(self.database.find_amazon_game("p1"))
        self.assertEqual(self.database.delete_amazon_games(), 1)
        self.assertIsNone(self.database.find_amazon_game("p1"))
        self.database.clear_amazon_library()
        self.assertEqual(self.database.amazon_library_stats()["total"], 0)


class AmazonRuntimeTests(unittest.TestCase):
    def test_runtime_file_uses_nile_command_and_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-amazon-runtime-") as tmp:
            root = Path(tmp)
            game_dir = root / "game"
            game_dir.mkdir()
            exe = game_dir / "game.exe"
            exe.write_bytes(b"MZ")
            runner = root / "wine"
            runner.write_text("#!/bin/sh\n", encoding="utf-8")
            runner.chmod(0o755)
            database = db.Database(root / "data.db")
            try:
                game_id = database.add_game(
                    name="Amazon Runtime",
                    exe_path=str(exe),
                    is_amazon=1,
                    amazon_id="p1",
                    wine_prefix=str(root / "prefix"),
                )
                game = database.get_game(game_id)
                assert game is not None
                info = core.RunnerInfo(kind="wine", version="test", path=str(runner))
                with patch.object(main, "resolve_runner", return_value=info):
                    runtime = main.write_runtime_file(
                        database,
                        game,
                        command=[str(exe), "--nile-arg"],
                        extra_env={
                            "FUEL_DIR": "/sdk/Legacy",
                            "AMAZON_GAMES_SDK_PATH": "/sdk/AmazonGamesSDK",
                        },
                        working_dir=str(game_dir),
                    )
                text = runtime.read_text(encoding="utf-8")
                self.assertIn("export FUEL_DIR=/sdk/Legacy", text)
                self.assertIn("export AMAZON_GAMES_SDK_PATH=/sdk/AmazonGamesSDK", text)
                self.assertIn(f"export BL_WORKDIR={game_dir}", text)
                self.assertIn("export BL_DIRECT=0", text)
                self.assertIn(f"set -- {exe} --nile-arg", text)
                self.assertIn(f"export BL_RUNNER={runner}", text)
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
