"""GOG/Epic store adapter tests using fake CLI tools."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault(
    "BOOSTLAYER_HOME", tempfile.mkdtemp(prefix="boostlayer-store-tests-")
)

import db  # noqa: E402
import stores  # noqa: E402


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class GenericStoreDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = db.Database()

    def tearDown(self) -> None:
        self.database.close()

    def test_store_library_roundtrip(self) -> None:
        games = [
            {
                "store_id": "g1",
                "title": "GOG Game",
                "installed": 1,
                "install_path": "/games/g1",
                "version": "1",
                "size": 100,
            }
        ]
        self.database.replace_store_library("gog", games, "now")
        self.assertEqual(
            self.database.store_library_stats("gog"),
            {"total": 1, "installed": 1},
        )
        item = self.database.get_store_library_game("gog", "g1")
        assert item is not None
        self.assertEqual(item["title"], "GOG Game")
        self.assertEqual(item["install_path"], "/games/g1")

    def test_store_size_is_preserved_and_updatable(self) -> None:
        self.database.replace_store_library(
            "gog", [{"store_id": "g1", "title": "Game", "size": 100}], "now"
        )
        self.database.replace_store_library(
            "gog", [{"store_id": "g1", "title": "Game", "size": 0}], "now"
        )
        self.assertEqual(
            self.database.get_store_library_game("gog", "g1")["size"], 100
        )
        self.database.set_store_size("gog", "g1", 250)
        self.assertEqual(
            self.database.get_store_library_game("gog", "g1")["size"], 250
        )

    def test_upsert_preserves_user_settings(self) -> None:
        game_id, created = self.database.upsert_store_game(
            "epic",
            name="Epic Game",
            exe_path="/games/epic/game.exe",
            store_id="e1",
            scaling_mode="crt",
            fps_limit=60,
        )
        self.assertTrue(created)
        self.database.update_game(
            game_id, runner_path="/runner/wine", wine_prefix="/prefix/e1"
        )
        _, created_again = self.database.upsert_store_game(
            "epic",
            name="Epic Renamed",
            exe_path="/games/epic/new.exe",
            store_id="e1",
        )
        self.assertFalse(created_again)
        game = self.database.find_store_game("epic", "e1")
        assert game is not None
        self.assertEqual(game["name"], "Epic Renamed")
        self.assertEqual(game["exe_path"], "/games/epic/new.exe")
        self.assertEqual(game["scaling_mode"], "crt")
        self.assertEqual(game["fps_limit"], 60)
        self.assertEqual(game["runner_path"], "/runner/wine")


class GogAdapterTests(unittest.TestCase):
    def test_launch_spec_reads_primary_task_and_case_insensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            (root / "Bin").mkdir()
            (root / "Bin" / "Game.exe").write_bytes(b"MZ")
            (root / "goggame-123.info").write_text(
                json.dumps(
                    {
                        "playTasks": [
                            {
                                "isPrimary": True,
                                "type": "FileTask",
                                "path": "game.exe",
                                "workingDir": "BIN",
                                "arguments": "-windowed +fps_max 60",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            spec = stores.STORES["gog"].launch_spec("gogdl", "123", root)
            self.assertEqual(spec["command"], str(root / "Bin" / "Game.exe"))
            self.assertEqual(spec["arguments"], ["-windowed", "+fps_max", "60"])
            self.assertEqual(spec["cwd"], str(root / "Bin"))

    def test_install_uses_parent_and_renames_to_exact_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            args_file = root / "args.txt"
            script = _script(
                root / "gogdl",
                f'echo "$@" > "{args_file}"\n'
                f'mkdir -p "{root}/gogdl-folder"\n'
                f'printf "{{}}" > "{root}/gogdl-folder/goggame-123.info"\n'
                "exit 0\n",
            )
            target = root / "Game Folder"
            result = stores.STORES["gog"].install(script, "123", target)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_path"], str(target))
            self.assertTrue((target / "goggame-123.info").is_file())
            args = args_file.read_text(encoding="utf-8")
            self.assertIn("download", args)
            self.assertIn("--path", args)
            self.assertIn(str(root), args)
            self.assertIn("--os windows", args)

    def test_find_game_dir_nested_and_other_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            nested = root / "actual" / "game"
            nested.mkdir(parents=True)
            (nested / "goggame-999.info").write_text("{}", encoding="utf-8")
            self.assertEqual(
                stores.STORES["gog"].find_game_dir(root, "123"), nested
            )

    def test_install_moves_nested_game_to_exact_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            script = _script(
                root / "gogdl",
                f'mkdir -p "{root}/actual/game"\n'
                f'printf "{{}}" > "{root}/actual/game/goggame-123.info"\n'
                "exit 0\n",
            )
            target = root / "Chosen"
            result = stores.STORES["gog"].install(script, "123", target)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_path"], str(target))
            self.assertTrue((target / "goggame-123.info").is_file())

    def test_install_keeps_actual_when_target_is_not_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            script = _script(
                root / "gogdl",
                f'mkdir -p "{root}/actual"\n'
                f'printf "{{}}" > "{root}/actual/goggame-123.info"\n'
                "exit 0\n",
            )
            target = root / "Chosen"
            target.mkdir()
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            result = stores.STORES["gog"].install(script, "123", target)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_path"], str(root / "actual"))
            self.assertTrue((target / "keep.txt").is_file())

    def test_install_forces_fresh_download_when_manifest_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            manifest = stores.STORES["gog"]._manifest_path("123")
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text("stale", encoding="utf-8")
            script = _script(
                root / "gogdl",
                'if [ -f "$GOGDL_CONFIG_PATH/heroic_gogdl/manifests/123" ]; then\n'
                "  echo 'Nothing to do'\n"
                "  exit 0\n"
                "fi\n"
                f'mkdir -p "{root}/gogdl-folder"\n'
                f'printf "{{}}" > "{root}/gogdl-folder/goggame-123.info"\n'
                "exit 0\n",
            )
            target = root / "Chosen"
            result = stores.STORES["gog"].install(script, "123", target)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_path"], str(target))
            self.assertTrue((target / "goggame-123.info").is_file())
            self.assertFalse(
                manifest.with_name(manifest.name + ".boostlayer-backup").exists()
            )

    def test_install_restores_manifest_when_download_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            manifest = stores.STORES["gog"]._manifest_path("123")
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text("stale", encoding="utf-8")
            script = _script(root / "gogdl", "exit 0\n")
            result = stores.STORES["gog"].install(
                script, "123", root / "Chosen"
            )
            self.assertFalse(result["ok"])
            self.assertTrue(manifest.is_file())
            self.assertEqual(manifest.read_text(encoding="utf-8"), "stale")

    def test_install_reports_missing_game_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            script = _script(root / "gogdl", "exit 0\n")
            result = stores.STORES["gog"].install(
                script, "123", root / "Chosen"
            )
            self.assertFalse(result["ok"])
            self.assertIn("gogdl nie utworzył", result["error"])

    def test_resolves_gogdl_appended_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            actual = root / "gogdl-folder"
            actual.mkdir()
            (actual / "game.exe").write_bytes(b"MZ")
            (actual / "goggame-123.info").write_text(
                json.dumps(
                    {
                        "playTasks": [
                            {
                                "isPrimary": True,
                                "type": "FileTask",
                                "path": "game.exe",
                                "workingDir": "",
                                "arguments": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            spec = stores.STORES["gog"].launch_spec(
                "gogdl", "123", root / "Chosen Folder"
            )
            self.assertEqual(spec["command"], str(actual / "game.exe"))

    def test_fetch_size_parses_info_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            script = _script(
                root / "gogdl",
                'echo \'{"disk_size": 1234, "download_size": 1000}\'\n',
            )
            self.assertEqual(
                stores.STORES["gog"].fetch_size(script, "123"), 1234
            )

    def test_login_with_fake_gogdl(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-gog-") as tmp:
            root = Path(tmp)
            script = _script(
                root / "gogdl",
                "echo '{\"access_token\":\"tok\",\"refresh_token\":\"ref\","
                "\"user_id\":\"123\",\"expires_in\":3600,\"loginTime\":0}'\n",
            )
            user = stores.STORES["gog"].finish_login(
                script, {}, "https://embed.gog.com/on_login_success?code=ABC"
            )
            self.assertEqual(user["user_id"], "123")
            self.assertTrue(stores.STORES["gog"].current_user()["user_id"])


class EpicAdapterTests(unittest.TestCase):
    def _fake_legendary(self, root: Path, args_file: Path) -> Path:
        body = f'''
case "$1" in
  auth)
    mkdir -p "$XDG_CONFIG_HOME/legendary"
    printf '%s' '{{"displayName":"Tester","account_id":"acc1"}}' > "$XDG_CONFIG_HOME/legendary/user.json"
    ;;
  list)
    printf '%s' '[{{"app_name":"epic1","app_title":"Epic Game","metadata":{{"description":"d","developer":"dev","keyImages":[{{"type":"DieselStoreFrontWide","url":"https://example.invalid/c.jpg"}}]}}}}]'
    ;;
  list-installed)
    printf '%s' '[{{"app_name":"epic1","title":"Epic Game","version":"1.2","install_path":"/games/epic1","install_size":123}}]'
    ;;
  launch)
    printf '%s' '{{"game_directory":"/games/epic1","game_executable":"game.exe","game_parameters":["-x"],"user_parameters":[],"egl_parameters":[],"working_directory":"/games/epic1","environment":{{"EPIC_TOKEN":"1"}}}}'
    ;;
  *)
    echo "$@" > "{args_file}"
    ;;
esac
exit 0
'''
        return _script(root / "legendary", body)

    def test_login_and_current_user(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-epic-") as tmp:
            root = Path(tmp)
            args_file = root / "args.txt"
            script = self._fake_legendary(root, args_file)
            user = stores.STORES["epic"].finish_login(script, {}, '{"authorizationCode":"CODE"}')
            self.assertEqual(user["name"], "Tester")
            self.assertEqual(stores.STORES["epic"].current_user()["name"], "Tester")

    def test_sync_normalizes_owned_and_installed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-epic-") as tmp:
            root = Path(tmp)
            script = self._fake_legendary(root, root / "args.txt")
            games = stores.STORES["epic"].sync(script)
            self.assertEqual(len(games), 1)
            game = games[0]
            self.assertEqual(game["store_id"], "epic1")
            self.assertEqual(game["installed"], 1)
            self.assertEqual(game["install_path"], "/games/epic1")
            self.assertEqual(game["cover_url"], "https://example.invalid/c.jpg")
            self.assertIn("spec_json", game)

    def test_launch_spec(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-epic-") as tmp:
            root = Path(tmp)
            script = self._fake_legendary(root, root / "args.txt")
            spec = stores.STORES["epic"].launch_spec(script, "epic1", "/games/epic1")
            self.assertEqual(spec["command"], "/games/epic1/game.exe")
            self.assertEqual(spec["arguments"], ["-x"])
            self.assertEqual(spec["env"]["EPIC_TOKEN"], "1")

    def test_install_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-epic-") as tmp:
            root = Path(tmp)
            args_file = root / "args.txt"
            script = self._fake_legendary(root, args_file)
            target = root / "Epic Game"
            result = stores.STORES["epic"].install(script, "epic1", target)
            self.assertTrue(result["ok"])
            args = args_file.read_text(encoding="utf-8")
            self.assertIn("--base-path", args)
            self.assertIn("--game-folder", args)
            self.assertIn("Epic Game", args)
            self.assertIn("--skip-sdl", args)

    def test_fetch_size_parses_info_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="boostlayer-epic-") as tmp:
            root = Path(tmp)
            script = _script(
                root / "legendary",
                'echo \'{"manifest": {"disk_size": 4567, "download_size": 4000}}\'\n',
            )
            self.assertEqual(
                stores.STORES["epic"].fetch_size(script, "epic1"), 4567
            )


class SafetyTests(unittest.TestCase):
    def test_refuses_root(self) -> None:
        with self.assertRaises(stores.StoreError):
            stores.safe_remove_game_dir("/")

    def test_safe_slug(self) -> None:
        self.assertEqual(stores.safe_slug("A/B:C?D"), "ABCD")
        self.assertEqual(stores.safe_slug("  "), "Game")


if __name__ == "__main__":
    unittest.main()
