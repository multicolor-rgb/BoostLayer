"""Headless regression tests for the stdlib backend and launch shim."""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

TEST_HOME = tempfile.mkdtemp(prefix="boostlayer-tests-")
os.environ["BOOSTLAYER_HOME"] = TEST_HOME

import core  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402
import theme  # noqa: E402
from console import parse_js_event  # noqa: E402


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = db.Database()

    def tearDown(self) -> None:
        self.database.close()

    def test_crud_and_fps_validation(self) -> None:
        game_id = self.database.add_game(
            name="Test Game",
            exe_path="/tmp/Test Game/game.exe",
            scaling_mode="fsr_1080_1440",
            fps_limit=60,
        )
        game = self.database.get_game(game_id)
        assert game is not None
        self.assertEqual(game["name"], "Test Game")
        self.assertEqual(game["fps_limit"], 60)
        self.database.update_game(game_id, fps_limit=37)
        self.assertEqual(self.database.get_game(game_id)["fps_limit"], 0)

    def test_steam_upsert_preserves_user_settings(self) -> None:
        game_id, created = self.database.upsert_steam_game(
            name="Steam Game",
            exe_path="/tmp/steam-game",
            runner_path="",
            wine_prefix="",
            env_vars="",
            launch_args="",
            scaling_mode="fsr_1080_1440",
            fps_limit=90,
            is_steam=1,
            steam_appid="12345",
            cover_path="",
        )
        self.assertTrue(created)
        updated_id, created = self.database.upsert_steam_game(
            name="Steam Game Renamed",
            exe_path="/tmp/steam-game",
            runner_path="",
            wine_prefix="",
            env_vars="",
            launch_args="",
            scaling_mode="native",
            fps_limit=0,
            is_steam=1,
            steam_appid="12345",
            cover_path="",
        )
        self.assertFalse(created)
        self.assertEqual(updated_id, game_id)
        game = self.database.get_game(game_id)
        self.assertEqual(game["name"], "Steam Game Renamed")
        self.assertEqual(game["scaling_mode"], "fsr_1080_1440")
        self.assertEqual(game["fps_limit"], 90)


class MangoHudTests(unittest.TestCase):
    def test_modules_and_mandatory_custom_text(self) -> None:
        profile = dict(db.DEFAULT_MANGOHUD)
        profile.update({"show_fps": False, "show_cpu": False, "show_temps": False})
        config = db.mangohud_config(profile, "fsr_1080_1440", 60)
        parts = config.split(",")
        self.assertNotIn("fps", parts)
        self.assertNotIn("cpu_stats", parts)
        self.assertNotIn("cpu_temp", parts)
        self.assertIn("fps_limit=60", parts)
        custom = [part for part in parts if part.startswith("custom_text=")]
        self.assertEqual(len(custom), 1)
        self.assertEqual(custom[0], "custom_text=FSR1080p")
        self.assertIn("legacy_layout=0", parts)
        self.assertNotIn(" ", custom[0])
        self.assertNotIn("\n", config)
        self.assertNotIn(",", custom[0])
        self.assertNotIn("text_outline_color", config)

    def test_invalid_position_and_colour_are_sanitised(self) -> None:
        profile = dict(db.DEFAULT_MANGOHUD)
        profile.update({"position": "somewhere", "gpu_color": "not-a-colour"})
        config = db.mangohud_config(profile, "native", 0)
        self.assertIn("position=top-left", config)
        self.assertIn("gpu_color=42F5A7", config)
        self.assertNotIn("fps_limit=", config)


class ThemeTests(unittest.TestCase):
    def test_all_themes_build_stylesheet(self) -> None:
        original = theme.get_theme()
        try:
            for key, item in theme.THEMES.items():
                theme.set_theme(key)
                qss = theme.build_qss(main.QSS)
                self.assertIn(item.accent, qss)
                self.assertGreater(len(qss), len(main.QSS))
        finally:
            theme.set_theme(original.key)

    def test_svg_contains_lightning_and_icon_files(self) -> None:
        svg = Path("assets/boostlayer.svg").read_text(encoding="utf-8")
        self.assertIn("<path", svg)
        self.assertIn("FF335F", svg)
        icons = Path("assets/icons")
        if icons.is_dir():
            for size in (16, 32, 48, 256):
                self.assertTrue((icons / f"boostlayer-{size}.png").is_file())


class GamepadTests(unittest.TestCase):
    def test_parse_button_and_axis(self) -> None:
        button = (123).to_bytes(4, "little") + (1).to_bytes(2, "little", signed=True) + bytes([1, 5])
        self.assertEqual(parse_js_event(button), (1, 5, 1))
        axis = (124).to_bytes(4, "little") + (-16000).to_bytes(2, "little", signed=True) + bytes([2, 7])
        self.assertEqual(parse_js_event(axis), (2, 7, -16000))
        self.assertIsNone(parse_js_event(b"short"))


class PeTests(unittest.TestCase):
    def test_exe_bits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bits, machine in ((32, 0x014C), (64, 0x8664)):
                path = root / f"game{bits}.exe"
                header = bytearray(0x100)
                header[0:2] = b"MZ"
                header[0x3C:0x40] = (0x80).to_bytes(4, "little")
                header[0x80:0x84] = b"PE\0\0"
                header[0x84:0x86] = machine.to_bytes(2, "little")
                path.write_bytes(header)
                self.assertEqual(core.exe_bits(path), bits)
            bad = root / "not.exe"
            bad.write_text("nope", encoding="utf-8")
            self.assertIsNone(core.exe_bits(bad))


class ArchiveTests(unittest.TestCase):
    def test_blocks_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                payload = b"owned"
                info = tarfile.TarInfo("../escaped.txt")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            with self.assertRaises(ValueError):
                core.safe_extract_tar(archive, root / "out")
            self.assertFalse((root / "escaped.txt").exists())

    def test_extracts_regular_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "bin").mkdir()
            (source / "bin" / "wine").write_text("#!/bin/sh\n", encoding="utf-8")
            archive = root / "good.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(source, arcname="runner")
            target = root / "target"
            core.safe_extract_tar(archive, target)
            self.assertTrue((target / "runner" / "bin" / "wine").is_file())


class RunnerReleaseTests(unittest.TestCase):
    def test_choose_asset_prefers_current_architecture(self) -> None:
        assets = [
            {"name": "GE-Proton11-11-aarch64.tar.gz"},
            {"name": "GE-Proton11-11-x86_64.tar.gz"},
            {"name": "GE-Proton11-11-x86_64.sha512sum"},
        ]
        chosen = core.choose_runner_asset(assets)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["name"], "GE-Proton11-11-x86_64.tar.gz")

    def test_release_cache_is_used(self) -> None:
        cache_dir = Path(TEST_HOME) / "cache" / "releases"
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "tag_name": "GE-Proton9-20",
                "name": "GE-Proton9-20",
                "published_at": "2024-01-01T00:00:00Z",
                "prerelease": False,
                "assets": [{"name": "GE-Proton9-20-x86_64.tar.gz"}],
            }
        ]
        (cache_dir / "proton_ge.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        releases = core.fetch_runner_releases("proton_ge", force=False)
        self.assertEqual(releases[0]["tag_name"], "GE-Proton9-20")


class SteamTests(unittest.TestCase):
    def test_generated_wrapper_uses_steam_appid(self) -> None:
        wrapper = core.ensure_steam_wrapper()
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("SteamAppId", text)
        self.assertIn("--steam-exec", text)
        self.assertTrue(os.access(wrapper, os.X_OK))
        option = core.steam_launch_option(wrapper)
        self.assertTrue(option.endswith(" %command%"))
        self.assertIn(str(wrapper), option)

    def test_manifest_regex_handles_quotes_and_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steamapps = root / "steamapps"
            steamapps.mkdir()
            (steamapps / "appmanifest_4242.acf").write_text(
                '"AppState"\n{\n'
                '  "appid" "4242"\n'
                '  "name" "A Game: \\"Deluxe\\""\n'
                '  "installdir" "A Game"\n'
                "}\n",
                encoding="utf-8",
            )
            manifests = core.read_steam_manifests(root)
            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0].appid, "4242")
            self.assertEqual(manifests[0].name, 'A Game: "Deluxe"')
            self.assertEqual(manifests[0].installdir, "A Game")


class SteamVdfTests(unittest.TestCase):
    WRAPPER = Path("/tmp/boostlayer/steam-wrapper.sh")

    SAMPLE = (
        '"UserLocalConfigStore"\n'
        "{\n"
        '\t"Software"\n'
        "\t{\n"
        '\t\t"Valve"\n'
        "\t\t{\n"
        '\t\t\t"Steam"\n'
        "\t\t\t{\n"
        '\t\t\t\t"apps"\n'
        "\t\t\t\t{\n"
        '\t\t\t\t\t"123"\n'
        "\t\t\t\t\t{\n"
        '\t\t\t\t\t\t"Playtime"\t\t"42"\n'
        "\t\t\t\t\t}\n"
        "\t\t\t\t}\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )

    def test_insert_missing_app_and_launch_options(self) -> None:
        text = self.SAMPLE
        new_text, action = core.update_steam_launch_options(
            text, "999", self.WRAPPER
        )
        self.assertEqual(action, "insert")
        self.assertIn(str(self.WRAPPER), new_text)
        self.assertEqual(
            core.get_steam_launch_options(new_text, "999"),
            f"{self.WRAPPER} %command%",
        )
        self.assertEqual(core.get_steam_launch_options(new_text, "123"), None)
        core._vdf_parse(new_text)

    def test_replace_empty_launch_options(self) -> None:
        text = self.SAMPLE.replace(
            '\t\t\t\t\t\t"Playtime"\t\t"42"\n',
            '\t\t\t\t\t\t"Playtime"\t\t"42"\n'
            '\t\t\t\t\t\t"LaunchOptions"\t\t""\n',
        )
        new_text, action = core.update_steam_launch_options(
            text, "123", self.WRAPPER
        )
        self.assertEqual(action, "set")
        self.assertEqual(
            core.get_steam_launch_options(new_text, "123"),
            f"{self.WRAPPER} %command%",
        )
        self.assertEqual(new_text.count('"LaunchOptions"'), 1)

    def test_preserve_simple_arguments(self) -> None:
        text = self.SAMPLE.replace(
            '\t\t\t\t\t\t"Playtime"\t\t"42"\n',
            '\t\t\t\t\t\t"Playtime"\t\t"42"\n'
            '\t\t\t\t\t\t"LaunchOptions"\t\t"-novid -windowed"\n',
        )
        new_text, action = core.update_steam_launch_options(
            text, "123", self.WRAPPER
        )
        self.assertEqual(action, "prepend")
        self.assertEqual(
            core.get_steam_launch_options(new_text, "123"),
            f"{self.WRAPPER} %command% -novid -windowed",
        )

    def test_skip_complex_existing_chain(self) -> None:
        text = self.SAMPLE.replace(
            '\t\t\t\t\t\t"Playtime"\t\t"42"\n',
            '\t\t\t\t\t\t"Playtime"\t\t"42"\n'
            '\t\t\t\t\t\t"LaunchOptions"\t\t"mangohud %command%"\n',
        )
        new_text, action = core.update_steam_launch_options(
            text, "123", self.WRAPPER
        )
        self.assertEqual(action, "complex")
        self.assertEqual(new_text, text)

    def test_worker_injects_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "steam"
            (root / "steamapps").mkdir(parents=True)
            userdata = root / "userdata" / "39734272" / "config"
            userdata.mkdir(parents=True)
            localconfig = userdata / "localconfig.vdf"
            localconfig.write_text(self.SAMPLE, encoding="utf-8")
            wrapper = Path(temporary) / "steam-wrapper.sh"
            wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
            old_root = core.detect_steam_root
            old_running = core.steam_is_running
            core.detect_steam_root = lambda preferred="": root
            core.steam_is_running = lambda: False
            try:
                worker = core.SteamOptionsWorker(["123"], wrapper)
                results: list[dict] = []
                worker.result.connect(lambda payload: results.append(payload))
                worker.run()
            finally:
                core.detect_steam_root = old_root
                core.steam_is_running = old_running
            self.assertTrue(results and results[0]["ok"])
            self.assertEqual(results[0]["updated"], 1)
            self.assertEqual(
                core.get_steam_launch_options(
                    localconfig.read_text(encoding="utf-8"), "123"
                ),
                f"{wrapper} %command%",
            )
            self.assertIsNotNone(core.latest_steam_backup())

    def test_account_selection_uses_autologin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "steamapps").mkdir()
            (root / "config").mkdir()
            steamid = "76561198000000000"
            account_id = str(int(steamid) & 0xFFFFFFFF)
            localconfig = root / "userdata" / account_id / "config" / "localconfig.vdf"
            localconfig.parent.mkdir(parents=True)
            localconfig.write_text(self.SAMPLE, encoding="utf-8")
            (root / "config" / "loginusers.vdf").write_text(
                '"users"\n{\n'
                f'\t"{steamid}"\n'
                "\t{\n"
                '\t\t"AccountName"\t\t"tester"\n'
                '\t\t"AutoLogin"\t\t"1"\n'
                '\t\t"timestamp"\t\t"123"\n'
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            account = core.steam_account(root)
            self.assertIsNotNone(account)
            self.assertEqual(account.account_id, account_id)
            self.assertEqual(account.account_name, "tester")
            self.assertEqual(account.localconfig, localconfig)


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = db.Database()
        self.database.set_many(
            {
                "gamemode": "0",
                "mangohud": "1",
                "gamescope": "0",
                "debug_logging": "1",
            }
        )

    def tearDown(self) -> None:
        self.database.close()

    def test_direct_steam_runtime_does_not_require_wine(self) -> None:
        game_id = self.database.add_game(
            name="Steam Test",
            exe_path="/tmp/steam-test",
            scaling_mode="fsr_1080_1440",
            fps_limit=60,
            is_steam=1,
            steam_appid="998877",
        )
        game = self.database.get_game(game_id)
        runtime = main.write_runtime_file(
            self.database,
            game,
            ["/bin/echo", "hello world"],
            direct=True,
            use_prefix=False,
        )
        text = runtime.read_text(encoding="utf-8")
        self.assertIn("BL_DIRECT=1", text)
        self.assertIn("SteamAppId=998877", text)
        self.assertIn("BL_PREFIX=''", text)
        self.assertIn("BL_RUNNER=''", text)
        self.assertIn("set -- /bin/echo 'hello world'", text)
        self.assertNotIn("export WINEPREFIX=", text)

    def test_standalone_runtime_uses_fake_wine_and_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wine = root / "wine"
            wine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wine.chmod(wine.stat().st_mode | stat.S_IXUSR)
            exe = root / "Game With Space.exe"
            exe.write_text("MZ", encoding="utf-8")
            prefix = root / "prefix"
            game_id = self.database.add_game(
                name="Standalone Test",
                exe_path=str(exe),
                runner_path=str(wine),
                wine_prefix=str(prefix),
                scaling_mode="crt",
                fps_limit=144,
            )
            game = self.database.get_game(game_id)
            runtime = main.write_runtime_file(self.database, game)
            text = runtime.read_text(encoding="utf-8")
            self.assertIn("BL_DIRECT=0", text)
            self.assertIn("BL_RUNNER_KIND=wine", text)
            self.assertIn(f"BL_PREFIX={prefix}", text)
            self.assertIn("export WINEPREFIX=", text)
            self.assertIn("Game With Space.exe'", text)
            self.assertIn("BL_FPS=144", text)
            self.assertIn("custom_text=CRT", text)
            self.assertIn("Mode: wine/proton", text)

            completed = subprocess.run(
                ["/bin/sh", str(core.ensure_launcher()), str(runtime)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            log_text = (Path(TEST_HOME) / "last_run.log").read_text(encoding="utf-8")
            self.assertIn("Game With Space.exe", log_text)

    def test_proton_runner_uses_proton_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "GE-Proton9-Test"
            (root / "files" / "bin").mkdir(parents=True)
            wine = root / "files" / "bin" / "wine"
            wine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wine.chmod(wine.stat().st_mode | stat.S_IXUSR)
            proton = root / "proton"
            proton.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            proton.chmod(proton.stat().st_mode | stat.S_IXUSR)
            exe = Path(temporary) / "Proton Game.exe"
            exe.write_text("MZ", encoding="utf-8")
            game_id = self.database.add_game(
                name="Proton Test",
                exe_path=str(exe),
                runner_path=str(wine),
                wine_prefix=str(Path(temporary) / "compatdata"),
            )
            game = self.database.get_game(game_id)
            runtime = main.write_runtime_file(self.database, game)
            text = runtime.read_text(encoding="utf-8")
            self.assertIn("BL_RUNNER_KIND=proton", text)
            self.assertIn(f"BL_PROTON={proton}", text)
            self.assertNotIn("export WINEPREFIX=", text)

            completed = subprocess.run(
                ["/bin/sh", str(core.ensure_launcher()), str(runtime)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            log_text = (Path(TEST_HOME) / "last_run.log").read_text(encoding="utf-8")
            self.assertIn(f"Proton: {proton}", log_text)
            self.assertIn("Proton Game.exe", log_text)

    def test_steam_wrapper_cli_passthrough_without_library_entry(self) -> None:
        env = dict(os.environ)
        env["BOOSTLAYER_HOME"] = TEST_HOME
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(main.__file__).resolve()),
                "--steam-exec",
                "",
                "--",
                "/bin/echo",
                "wrapper-ok",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("wrapper-ok", completed.stdout)


def tearDownModule() -> None:
    shutil.rmtree(TEST_HOME, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
