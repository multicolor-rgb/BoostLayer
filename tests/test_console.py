"""Console/Steam process detection tests."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import core


class SteamProcessDetectionTests(unittest.TestCase):
    @unittest.skipUnless(Path("/proc").is_dir(), "requires /proc")
    def test_detects_process_with_steam_appid(self) -> None:
        appid = "987654"
        env = dict(os.environ)
        env["SteamAppId"] = appid
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            env=env,
        )
        try:
            time.sleep(0.25)
            self.assertTrue(core.steam_game_process_running(appid))
        finally:
            process.terminate()
            process.wait(timeout=5)
        time.sleep(0.2)
        self.assertFalse(core.steam_game_process_running(appid))


if __name__ == "__main__":
    unittest.main()
