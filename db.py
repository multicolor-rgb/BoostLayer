"""Boostlayer data layer.

Pure standard-library SQLite access.  The UI never builds SQL strings from user
data; every dynamic value is passed as a bound parameter.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from i18n import tr

APP_NAME = "boostlayer"
FPS_LIMITS = (0, 30, 40, 60, 90, 120, 144)

# The stored values are deliberately stable: they are written into the database
# and consumed by launcher.sh.  Labels can change without a migration.
SCALING_PROFILES: dict[str, dict[str, Any]] = {
    "native": {
        "label": "Natywnie",
        "kind": "native",
    },
    "fsr_720_1080": {
        "label": "AMD FSR 720p -> 1080p",
        "kind": "gamescope",
        "source": (1280, 720),
        "output": (1920, 1080),
        "upscaler": "fsr",
        "sharpness": 8,
    },
    "fsr_1080_1440": {
        "label": "AMD FSR 1080p -> 1440p",
        "kind": "gamescope",
        "source": (1920, 1080),
        "output": (2560, 1440),
        "upscaler": "fsr",
        "sharpness": 8,
    },
    "fsr_1440_4k": {
        "label": "AMD FSR 1440p -> 4K",
        "kind": "gamescope",
        "source": (2560, 1440),
        "output": (3840, 2160),
        "upscaler": "fsr",
        "sharpness": 8,
    },
    "nis_1080_1440": {
        "label": "NVIDIA NIS 1080p -> 1440p",
        "kind": "gamescope",
        "source": (1920, 1080),
        "output": (2560, 1440),
        "upscaler": "nis",
        "sharpness": 8,
    },
    "integer": {
        "label": "Integer Scaling (720p -> 4K)",
        "kind": "gamescope",
        "source": (1280, 720),
        "output": (3840, 2160),
        "upscaler": "integer",
        "sharpness": 0,
    },
    "crt": {
        "label": "Retro Kineskop (CRT)",
        "kind": "crt",
        "source": (1280, 720),
        "output": (1920, 1080),
        "upscaler": "stretch",
        "sharpness": 0,
    },
    "proton_fsr_quality": {
        "label": "Proton FSR Quality",
        "kind": "proton",
        "fsr_strength": 2,
    },
    "proton_fsr_balanced": {
        "label": "Proton FSR Balanced",
        "kind": "proton",
        "fsr_strength": 3,
    },
    "proton_fsr_performance": {
        "label": "Proton FSR Performance",
        "kind": "proton",
        "fsr_strength": 4,
    },
}

# Short labels keep custom_text readable inside MangoHud's table layout.
HUD_MODE_LABELS: dict[str, str] = {
    "native": "NATIVE",
    "fsr_720_1080": "FSR720p",
    "fsr_1080_1440": "FSR1080p",
    "fsr_1440_4k": "FSR1440p",
    "nis_1080_1440": "NIS1080p",
    "integer": "INTEGER",
    "crt": "CRT",
    "proton_fsr_quality": "PFSR-Q",
    "proton_fsr_balanced": "PFSR-B",
    "proton_fsr_performance": "PFSR-P",
}


DEFAULT_MANGOHUD: dict[str, Any] = {
    "position": "top-left",
    "show_fps": True,
    "show_cpu": True,
    "show_gpu": True,
    "show_ram": True,
    "show_vram": True,
    "show_temps": True,
    "show_frametime": True,
    "accent": "#00E5FF",
    "gpu_color": "#42F5A7",
    "cpu_color": "#00B8FF",
    "text_color": "#E6FAFF",
    "background_alpha": 0.35,
    "font_size": 18,
    "round_corners": 8,
}

DEFAULT_SETTINGS: dict[str, str] = {
    "default_runner": "",
    "gamemode": "1",
    "mangohud": "1",
    "gamescope": "1",
    "debug_logging": "0",
    "ghost_mode": "1",
    "close_to_tray": "1",
    "library_view": "grid",
    "steam_path": "",
    "steam_wrapper": "",
    "steam_api_key": "",
    "steam_id64": "",
    "steam_library_synced": "",
    "auto_steam_wrapper": "1",
    "amazon_install_dir": str(Path.home() / "Games" / "nile"),
    "amazon_nile_path": "",
    "amazon_library_synced": "",
    "amazon_max_workers": "0",
    "prefetch_covers": "1",
    "prefetch_sizes": "1",
    "global_hotkey": "1",
    "theme": "epic",
    "language": "pl",
    "console_monitor": "0",
    "mangohud_profile": json.dumps(DEFAULT_MANGOHUD),
    "crt_shader": "",
}

LIBRARY_FIELDS = (
    "name",
    "exe_path",
    "runner_path",
    "wine_prefix",
    "env_vars",
    "launch_args",
    "scaling_mode",
    "fps_limit",
    "is_steam",
    "steam_appid",
    "is_amazon",
    "amazon_id",
    "store",
    "store_id",
    "cover_path",
    "winetricks_verbs",
    "winetricks_auto",
    "winetricks_state",
)


def config_dir() -> Path:
    override = os.environ.get("BOOSTLAYER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / "boostlayer"


CONFIG_DIR = config_dir()
DB_PATH = CONFIG_DIR / "data.db"
PREFIXES_DIR = CONFIG_DIR / "prefixes"
RUNNERS_DIR = CONFIG_DIR / "runners"
COVERS_DIR = CONFIG_DIR / "covers"
RUNTIME_DIR = CONFIG_DIR / "runtime"
DOWNLOADS_DIR = CONFIG_DIR / ".downloads"
SHADER_DIR = CONFIG_DIR / "shaders"


def ensure_app_dirs() -> None:
    for directory in (
        CONFIG_DIR,
        PREFIXES_DIR,
        RUNNERS_DIR,
        COVERS_DIR,
        RUNTIME_DIR,
        DOWNLOADS_DIR,
        SHADER_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "game"


def make_prefix(name: str) -> str:
    ensure_app_dirs()
    stem = slugify(name)[:48]
    for _ in range(20):
        candidate = PREFIXES_DIR / f"{stem}-{uuid.uuid4().hex[:8]}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return str(candidate)
    raise RuntimeError(tr("Nie udało się utworzyć katalogu prefiksu."))


def sanitize_hex(value: str, fallback: str = "FFFFFF") -> str:
    value = (value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        return value.upper()
    return fallback


def mangohud_config(profile: dict[str, Any], scaling_mode: str, fps_limit: int) -> str:
    """Build a MANGOHUD_CONFIG value from a stored profile.

    Only options understood by MangoHud are emitted.  ``custom_text`` is
    mandatory and always describes the scaling profile of the current game.
    Commas are stripped from its value because MangoHud uses them as the
    option separator.
    """
    parts: list[str] = []
    # MangoHud defaults to legacy_layout=true, and its legacy renderer does
    # not include custom_text at all.  The newer layout is required to show
    # the active scaling profile.
    parts.append("legacy_layout=0")
    if profile.get("show_fps", True):
        parts.append("fps")
    if profile.get("show_cpu", True):
        parts.append("cpu_stats")
    if profile.get("show_gpu", True):
        parts.append("gpu_stats")
    if profile.get("show_ram", True):
        parts.append("ram")
    if profile.get("show_vram", True):
        parts.append("vram")
    if profile.get("show_temps", True):
        parts.extend(("cpu_temp", "gpu_temp"))
    if profile.get("show_frametime", True):
        parts.extend(("frametime", "frame_timing"))

    position = str(profile.get("position", "top-left"))
    if position not in {
        "top-left",
        "top-center",
        "top-right",
        "middle-left",
        "middle-center",
        "middle-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }:
        position = "top-left"
    try:
        font_size = int(profile.get("font_size", 18))
    except (TypeError, ValueError):
        font_size = 18
    try:
        background_alpha = float(profile.get("background_alpha", 0.35))
    except (TypeError, ValueError):
        background_alpha = 0.35
    try:
        round_corners = int(profile.get("round_corners", 8))
    except (TypeError, ValueError):
        round_corners = 8
    parts.append(f"position={position}")
    parts.append(f"font_size={max(10, min(48, font_size))}")
    parts.append(f"background_alpha={max(0.0, min(1.0, background_alpha)):.2f}")
    parts.append(f"round_corners={max(0, min(30, round_corners))}")
    parts.append(
        f"text_color={sanitize_hex(str(profile.get('text_color', '#E6FAFF')), 'E6FAFF')}"
    )
    parts.append(
        f"gpu_color={sanitize_hex(str(profile.get('gpu_color', '#42F5A7')), '42F5A7')}"
    )
    parts.append(
        f"cpu_color={sanitize_hex(str(profile.get('cpu_color', '#00B8FF')), '00B8FF')}"
    )
    try:
        fps_value = int(fps_limit or 0)
    except (TypeError, ValueError):
        fps_value = 0
    if fps_value > 0:
        parts.append(f"fps_limit={fps_value}")

    label = HUD_MODE_LABELS.get(
        scaling_mode,
        HUD_MODE_LABELS["native"],
    )
    # MangoHud 0.6.x splits values on whitespace and punctuation.  Keep
    # custom_text a single compact token so it fits the HUD table and never
    # breaks the rest of MANGOHUD_CONFIG.
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
    safe_label = re.sub(r"_{2,}", "_", safe_label).strip("_")
    parts.append(f"custom_text={safe_label or 'NATIVE'}")
    return ",".join(parts)


def scaling_label(mode: str) -> str:
    profile = SCALING_PROFILES.get(mode, SCALING_PROFILES["native"])
    return tr(str(profile["label"]))


class Database:
    """Small, thread-safe-enough SQLite wrapper for a single desktop app."""

    def __init__(self, path: Path | str | None = None) -> None:
        ensure_app_dirs()
        self.path = Path(path) if path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), timeout=20, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS library (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    name         TEXT NOT NULL,
                    exe_path     TEXT NOT NULL,
                    runner_path  TEXT NOT NULL DEFAULT '',
                    wine_prefix  TEXT NOT NULL DEFAULT '',
                    env_vars     TEXT NOT NULL DEFAULT '',
                    launch_args  TEXT NOT NULL DEFAULT '',
                    scaling_mode TEXT NOT NULL DEFAULT 'native',
                    fps_limit    INTEGER NOT NULL DEFAULT 0,
                    is_steam     INTEGER NOT NULL DEFAULT 0,
                    steam_appid  TEXT NOT NULL DEFAULT '',
                    is_amazon    INTEGER NOT NULL DEFAULT 0,
                    amazon_id    TEXT NOT NULL DEFAULT '',
                    store        TEXT NOT NULL DEFAULT '',
                    store_id     TEXT NOT NULL DEFAULT '',
                    cover_path   TEXT NOT NULL DEFAULT '',
                    winetricks_verbs TEXT NOT NULL DEFAULT '',
                    winetricks_auto  INTEGER NOT NULL DEFAULT 0,
                    winetricks_state TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_library_name
                    ON library(name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_library_steam
                    ON library(steam_appid);

                CREATE TABLE IF NOT EXISTS steam_library (
                    appid            TEXT PRIMARY KEY,
                    name             TEXT NOT NULL,
                    playtime_minutes INTEGER NOT NULL DEFAULT 0,
                    installed        INTEGER NOT NULL DEFAULT 0,
                    cover_path       TEXT NOT NULL DEFAULT '',
                    size             INTEGER NOT NULL DEFAULT 0,
                    last_synced      TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_steam_library_name
                    ON steam_library(name COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS amazon_library (
                    product_id     TEXT PRIMARY KEY,
                    entitlement_id TEXT NOT NULL DEFAULT '',
                    title          TEXT NOT NULL,
                    description    TEXT NOT NULL DEFAULT '',
                    developer      TEXT NOT NULL DEFAULT '',
                    icon_url       TEXT NOT NULL DEFAULT '',
                    cover_url      TEXT NOT NULL DEFAULT '',
                    cover_path     TEXT NOT NULL DEFAULT '',
                    installed      INTEGER NOT NULL DEFAULT 0,
                    install_path   TEXT NOT NULL DEFAULT '',
                    version        TEXT NOT NULL DEFAULT '',
                    size           INTEGER NOT NULL DEFAULT 0,
                    spec_json      TEXT NOT NULL DEFAULT '',
                    last_synced    TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_amazon_library_title
                    ON amazon_library(title COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS store_library (
                    store         TEXT NOT NULL,
                    store_id      TEXT NOT NULL,
                    title         TEXT NOT NULL,
                    description   TEXT NOT NULL DEFAULT '',
                    developer     TEXT NOT NULL DEFAULT '',
                    icon_url      TEXT NOT NULL DEFAULT '',
                    cover_url     TEXT NOT NULL DEFAULT '',
                    cover_path    TEXT NOT NULL DEFAULT '',
                    installed     INTEGER NOT NULL DEFAULT 0,
                    install_path  TEXT NOT NULL DEFAULT '',
                    version       TEXT NOT NULL DEFAULT '',
                    size          INTEGER NOT NULL DEFAULT 0,
                    spec_json     TEXT NOT NULL DEFAULT '',
                    extra_json    TEXT NOT NULL DEFAULT '',
                    last_synced   TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (store, store_id)
                );

                CREATE INDEX IF NOT EXISTS idx_store_library_title
                    ON store_library(store, title COLLATE NOCASE);
                """
            )
            self._migrate_schema()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_amazon "
                "ON library(amazon_id)"
            )
            for key, value in DEFAULT_SETTINGS.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (key, value),
                )

    def _migrate_schema(self) -> None:
        """Add columns introduced after the first public database format."""
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(library)").fetchall()
        }
        additions = {
            "winetricks_verbs": "TEXT NOT NULL DEFAULT ''",
            "winetricks_auto": "INTEGER NOT NULL DEFAULT 0",
            "winetricks_state": "TEXT NOT NULL DEFAULT ''",
            "is_amazon": "INTEGER NOT NULL DEFAULT 0",
            "amazon_id": "TEXT NOT NULL DEFAULT ''",
            "store": "TEXT NOT NULL DEFAULT ''",
            "store_id": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                self._conn.execute(
                    f"ALTER TABLE library ADD COLUMN {name} {definition}"
                )
        amazon_columns = {
            str(row["name"])
            for row in self._conn.execute(
                "PRAGMA table_info(amazon_library)"
            ).fetchall()
        }
        if "spec_json" not in amazon_columns:
            self._conn.execute(
                "ALTER TABLE amazon_library ADD COLUMN spec_json "
                "TEXT NOT NULL DEFAULT ''"
            )
        steam_columns = {
            str(row["name"])
            for row in self._conn.execute(
                "PRAGMA table_info(steam_library)"
            ).fetchall()
        }
        if "size" not in steam_columns:
            self._conn.execute(
                "ALTER TABLE steam_library ADD COLUMN size "
                "INTEGER NOT NULL DEFAULT 0"
            )
        # Backfill the generic store columns from the legacy ones.  The old
        # columns/tables stay in place as a safety net for existing databases.
        self._conn.execute(
            "UPDATE library SET store = 'steam', store_id = steam_appid "
            "WHERE (store IS NULL OR store = '') AND is_steam = 1 "
            "AND steam_appid <> ''"
        )
        self._conn.execute(
            "UPDATE library SET store = 'amazon', store_id = amazon_id "
            "WHERE (store IS NULL OR store = '') AND is_amazon = 1 "
            "AND amazon_id <> ''"
        )
        for legacy_store, table in (("steam", "steam_library"), ("amazon", "amazon_library")):
            try:
                count = int(
                    self._conn.execute(
                        f"SELECT COUNT(*) FROM store_library WHERE store = ?",
                        (legacy_store,),
                    ).fetchone()[0]
                )
            except sqlite3.Error:
                continue
            if count:
                continue
            try:
                rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                data = dict(row)
                store_id = str(
                    data.get("appid") if legacy_store == "steam" else data.get("product_id")
                )
                if not store_id:
                    continue
                self._conn.execute(
                    "INSERT OR IGNORE INTO store_library(store, store_id, title, "
                    "description, developer, icon_url, cover_url, cover_path, "
                    "installed, install_path, version, size, last_synced) "
                    "VALUES(?, ?, ?, '', '', '', '', ?, ?, ?, ?, ?, ?)",
                    (
                        legacy_store,
                        store_id,
                        str(data.get("name") or data.get("title") or store_id),
                        str(data.get("cover_path") or ""),
                        1 if data.get("installed") else 0,
                        str(data.get("install_path") or ""),
                        str(data.get("version") or ""),
                        int(data.get("size") or data.get("playtime_minutes") or 0)
                        if legacy_store == "amazon"
                        else 0,
                        str(data.get("last_synced") or ""),
                    ),
                )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_library_store "
            "ON library(store, store_id)"
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str | None = None) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return DEFAULT_SETTINGS.get(key, default if default is not None else "")
        return str(row["value"])

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get_setting(key, "1" if default else "0")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get_setting(key, str(default)))
        except (TypeError, ValueError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    def set_many(self, values: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(str(key), str(value)) for key, value in values.items()],
            )

    def all_settings(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        result = dict(DEFAULT_SETTINGS)
        result.update({str(row["key"]): str(row["value"]) for row in rows})
        return result

    # ------------------------------------------------------------------ MangoHud
    def get_mangohud(self) -> dict[str, Any]:
        raw = self.get_setting("mangohud_profile", "{}")
        try:
            stored = json.loads(raw)
            if not isinstance(stored, dict):
                stored = {}
        except (TypeError, ValueError):
            stored = {}
        profile = dict(DEFAULT_MANGOHUD)
        profile.update(stored)
        return profile

    def save_mangohud(self, profile: dict[str, Any]) -> None:
        clean = dict(DEFAULT_MANGOHUD)
        clean.update(profile)
        self.set_setting("mangohud_profile", json.dumps(clean))

    # ------------------------------------------------------------------- library
    def _clean_row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["id"] = int(data["id"])
        data["fps_limit"] = int(data.get("fps_limit", 0))
        data["is_steam"] = int(bool(data.get("is_steam", 0)))
        data["steam_appid"] = str(data.get("steam_appid") or "")
        data["is_amazon"] = int(bool(data.get("is_amazon", 0)))
        data["amazon_id"] = str(data.get("amazon_id") or "")
        data["store"] = str(data.get("store") or "")
        data["store_id"] = str(data.get("store_id") or "")
        data["winetricks_verbs"] = str(data.get("winetricks_verbs") or "")
        data["winetricks_auto"] = int(bool(data.get("winetricks_auto", 0)))
        data["winetricks_state"] = str(data.get("winetricks_state") or "")
        return data

    def list_games(self, search: str = "") -> list[dict[str, Any]]:
        with self._lock:
            if search.strip():
                term = f"%{search.strip()}%"
                rows = self._conn.execute(
                    "SELECT * FROM library WHERE name LIKE ? COLLATE NOCASE "
                    "ORDER BY name COLLATE NOCASE",
                    (term,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM library ORDER BY name COLLATE NOCASE"
                ).fetchall()
        return [self._clean_row(row) for row in rows]

    def get_game(self, game_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM library WHERE id = ?", (int(game_id),)
            ).fetchone()
        return self._clean_row(row) if row else None

    def find_steam_game(self, appid: str | int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM library WHERE steam_appid = ?", (str(appid),)
            ).fetchone()
        return self._clean_row(row) if row else None

    def add_game(self, **values: Any) -> int:
        data = {field: values.get(field, "") for field in LIBRARY_FIELDS}
        for field in LIBRARY_FIELDS:
            if data[field] is None:
                data[field] = ""
        data["name"] = str(data["name"]).strip()
        data["exe_path"] = str(data["exe_path"]).strip()
        if not data["name"] or not data["exe_path"]:
            raise ValueError(tr("Nazwa i ścieżka gry są wymagane."))
        if data["scaling_mode"] not in SCALING_PROFILES:
            data["scaling_mode"] = "native"
        try:
            data["fps_limit"] = int(data["fps_limit"] or 0)
        except (TypeError, ValueError):
            data["fps_limit"] = 0
        if data["fps_limit"] not in FPS_LIMITS:
            data["fps_limit"] = 0
        data["is_steam"] = 1 if data["is_steam"] else 0
        data["is_amazon"] = 1 if data["is_amazon"] else 0
        data["winetricks_auto"] = 1 if data["winetricks_auto"] else 0
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO library(name, exe_path, runner_path, wine_prefix, "
                "env_vars, launch_args, scaling_mode, fps_limit, is_steam, "
                "steam_appid, is_amazon, amazon_id, store, store_id, cover_path, "
                "winetricks_verbs, winetricks_auto, winetricks_state) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    data["name"],
                    data["exe_path"],
                    data["runner_path"],
                    data["wine_prefix"],
                    data["env_vars"],
                    data["launch_args"],
                    data["scaling_mode"],
                    data["fps_limit"],
                    data["is_steam"],
                    str(data["steam_appid"]),
                    data["is_amazon"],
                    str(data["amazon_id"]),
                    str(data["store"]),
                    str(data["store_id"]),
                    data["cover_path"],
                    str(data["winetricks_verbs"]),
                    data["winetricks_auto"],
                    str(data["winetricks_state"]),
                ),
            )
        return int(cursor.lastrowid)

    def update_game(self, game_id: int, **values: Any) -> None:
        allowed = {key: values[key] for key in LIBRARY_FIELDS if key in values}
        if not allowed:
            return
        for key, value in list(allowed.items()):
            if value is None:
                allowed[key] = ""
        if "scaling_mode" in allowed and allowed["scaling_mode"] not in SCALING_PROFILES:
            allowed["scaling_mode"] = "native"
        if "fps_limit" in allowed:
            try:
                allowed["fps_limit"] = int(allowed["fps_limit"] or 0)
            except (TypeError, ValueError):
                allowed["fps_limit"] = 0
            if allowed["fps_limit"] not in FPS_LIMITS:
                allowed["fps_limit"] = 0
        if "is_steam" in allowed:
            allowed["is_steam"] = 1 if allowed["is_steam"] else 0
        if "is_amazon" in allowed:
            allowed["is_amazon"] = 1 if allowed["is_amazon"] else 0
        if "winetricks_auto" in allowed:
            allowed["winetricks_auto"] = 1 if allowed["winetricks_auto"] else 0
        assignments = ", ".join(f"{field} = ?" for field in allowed)
        params = list(allowed.values()) + [int(game_id)]
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE library SET {assignments} WHERE id = ?", params
            )

    def upsert_steam_game(self, **values: Any) -> tuple[int, bool]:
        """Insert a Steam entry, or refresh only safe metadata of an existing one."""
        appid = str(values.get("steam_appid", ""))
        existing = self.find_steam_game(appid) if appid else None
        if existing:
            updates: dict[str, Any] = {"name": values.get("name", existing["name"])}
            if values.get("cover_path"):
                updates["cover_path"] = values["cover_path"]
            if values.get("exe_path"):
                updates["exe_path"] = values["exe_path"]
            self.update_game(existing["id"], **updates)
            return existing["id"], False
        values["is_steam"] = 1
        values["store"] = "steam"
        values["store_id"] = str(values.get("steam_appid", ""))
        return self.add_game(**values), True

    def find_amazon_game(self, product_id: str | int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM library WHERE amazon_id = ?", (str(product_id),)
            ).fetchone()
        return self._clean_row(row) if row else None

    def upsert_amazon_game(self, **values: Any) -> tuple[int, bool]:
        """Insert an Amazon entry, or refresh only safe metadata of an existing one."""
        product_id = str(values.get("amazon_id", ""))
        existing = self.find_amazon_game(product_id) if product_id else None
        if existing:
            updates: dict[str, Any] = {"name": values.get("name", existing["name"])}
            if values.get("cover_path"):
                updates["cover_path"] = values["cover_path"]
            if values.get("exe_path"):
                updates["exe_path"] = values["exe_path"]
            self.update_game(existing["id"], **updates)
            return existing["id"], False
        values["is_amazon"] = 1
        values["store"] = "amazon"
        values["store_id"] = str(values.get("amazon_id", ""))
        return self.add_game(**values), True

    def delete_game(self, game_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM library WHERE id = ?", (int(game_id),))

    # ------------------------------------------------------------- Steam catalog
    def replace_steam_library(
        self,
        games: Iterable[dict[str, Any]],
        synced_at: str = "",
    ) -> None:
        """Replace the cached owned-game list while preserving local covers."""
        with self._lock:
            existing = {
                str(row["appid"]): (
                    str(row["cover_path"] or ""),
                    int(row["size"] or 0),
                )
                for row in self._conn.execute(
                    "SELECT appid, cover_path, size FROM steam_library"
                ).fetchall()
            }
        rows: list[tuple[str, str, int, int, str, int, str]] = []
        for game in games:
            appid = str(game.get("appid", "")).strip()
            name = str(game.get("name", "")).strip()
            if not appid or not name:
                continue
            previous_cover, previous_size = existing.get(appid, ("", 0))
            rows.append(
                (
                    appid,
                    name,
                    int(game.get("playtime_minutes", 0) or 0),
                    1 if game.get("installed") else 0,
                    str(game.get("cover_path") or previous_cover),
                    int(game.get("size", 0) or previous_size or 0),
                    synced_at,
                )
            )
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM steam_library")
            self._conn.executemany(
                "INSERT INTO steam_library(appid, name, playtime_minutes, "
                "installed, cover_path, size, last_synced) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def list_steam_library(
        self,
        search: str = "",
        installed: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            clauses.append("name LIKE ? COLLATE NOCASE")
            params.append(f"%{search.strip()}%")
        if installed is not None:
            clauses.append("installed = ?")
            params.append(1 if installed else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM steam_library {where} "
                "ORDER BY installed DESC, name COLLATE NOCASE",
                params,
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["appid"] = str(item.get("appid") or "")
            item["playtime_minutes"] = int(item.get("playtime_minutes", 0) or 0)
            item["installed"] = int(bool(item.get("installed", 0)))
            item["cover_path"] = str(item.get("cover_path") or "")
            item["size"] = int(item.get("size", 0) or 0)
            result.append(item)
        return result

    def get_steam_library_game(self, appid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steam_library WHERE appid = ?", (str(appid),)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["appid"] = str(item.get("appid") or "")
        item["playtime_minutes"] = int(item.get("playtime_minutes", 0) or 0)
        item["installed"] = int(bool(item.get("installed", 0)))
        item["cover_path"] = str(item.get("cover_path") or "")
        item["size"] = int(item.get("size", 0) or 0)
        return item

    def set_steam_cover(self, appid: str, cover_path: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE steam_library SET cover_path = ? WHERE appid = ?",
                (str(cover_path), str(appid)),
            )

    def set_steam_size(self, appid: str, size: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE steam_library SET size = ? WHERE appid = ?",
                (int(size or 0), str(appid)),
            )

    def set_steam_installed(self, appids: Iterable[str]) -> None:
        installed = {str(appid) for appid in appids}
        with self._lock, self._conn:
            self._conn.execute("UPDATE steam_library SET installed = 0")
            self._conn.executemany(
                "UPDATE steam_library SET installed = 1 WHERE appid = ?",
                [(appid,) for appid in installed],
            )

    def steam_library_stats(self) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(installed), 0) AS installed "
                "FROM steam_library"
            ).fetchone()
        return {
            "total": int(row["total"] or 0) if row is not None else 0,
            "installed": int(row["installed"] or 0) if row is not None else 0,
        }

    # ------------------------------------------------------------ Amazon catalog
    def replace_amazon_library(
        self,
        games: Iterable[dict[str, Any]],
        synced_at: str = "",
    ) -> None:
        """Replace the cached Amazon list while preserving local covers."""
        with self._lock:
            existing = {
                str(row["product_id"]): (
                    str(row["cover_path"] or ""),
                    str(row["spec_json"] or ""),
                )
                for row in self._conn.execute(
                    "SELECT product_id, cover_path, spec_json FROM amazon_library"
                ).fetchall()
            }
        rows: list[tuple[str, str, str, str, str, str, str, str, int, str, str, int, str, str]] = []
        for game in games:
            product_id = str(game.get("product_id", "")).strip()
            title = str(game.get("title", "")).strip()
            if not product_id or not title:
                continue
            previous_cover, previous_spec = existing.get(product_id, ("", ""))
            rows.append(
                (
                    product_id,
                    str(game.get("entitlement_id", "") or ""),
                    title,
                    str(game.get("description", "") or ""),
                    str(game.get("developer", "") or ""),
                    str(game.get("icon_url", "") or ""),
                    str(game.get("cover_url", "") or ""),
                    str(game.get("cover_path") or previous_cover),
                    1 if game.get("installed") else 0,
                    str(game.get("install_path", "") or ""),
                    str(game.get("version", "") or ""),
                    int(game.get("size", 0) or 0),
                    str(game.get("spec_json") or previous_spec),
                    synced_at,
                )
            )
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM amazon_library")
            self._conn.executemany(
                "INSERT INTO amazon_library(product_id, entitlement_id, title, "
                "description, developer, icon_url, cover_url, cover_path, "
                "installed, install_path, version, size, spec_json, last_synced) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _clean_amazon_row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["product_id"] = str(item.get("product_id") or "")
        item["entitlement_id"] = str(item.get("entitlement_id") or "")
        item["installed"] = int(bool(item.get("installed", 0)))
        item["install_path"] = str(item.get("install_path") or "")
        item["version"] = str(item.get("version") or "")
        item["size"] = int(item.get("size", 0) or 0)
        item["cover_path"] = str(item.get("cover_path") or "")
        item["cover_url"] = str(item.get("cover_url") or "")
        item["icon_url"] = str(item.get("icon_url") or "")
        item["description"] = str(item.get("description") or "")
        item["developer"] = str(item.get("developer") or "")
        item["spec_json"] = str(item.get("spec_json") or "")
        return item

    def list_amazon_library(
        self,
        search: str = "",
        installed: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            clauses.append("title LIKE ? COLLATE NOCASE")
            params.append(f"%{search.strip()}%")
        if installed is not None:
            clauses.append("installed = ?")
            params.append(1 if installed else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM amazon_library {where} "
                "ORDER BY installed DESC, title COLLATE NOCASE",
                params,
            ).fetchall()
        return [self._clean_amazon_row(row) for row in rows]

    def get_amazon_library_game(self, product_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM amazon_library WHERE product_id = ?",
                (str(product_id),),
            ).fetchone()
        return self._clean_amazon_row(row) if row else None

    def set_amazon_cover(self, product_id: str, cover_path: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE amazon_library SET cover_path = ? WHERE product_id = ?",
                (str(cover_path), str(product_id)),
            )

    def set_amazon_spec(self, product_id: str, spec_json: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE amazon_library SET spec_json = ? WHERE product_id = ?",
                (str(spec_json), str(product_id)),
            )

    def update_amazon_install(
        self,
        product_id: str,
        *,
        installed: bool,
        install_path: str = "",
        version: str = "",
        size: int = 0,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE amazon_library SET installed = ?, install_path = ?, "
                "version = ?, size = ? WHERE product_id = ?",
                (
                    1 if installed else 0,
                    str(install_path or ""),
                    str(version or ""),
                    int(size or 0),
                    str(product_id),
                ),
            )

    def amazon_library_stats(self) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(installed), 0) AS installed "
                "FROM amazon_library"
            ).fetchone()
        return {
            "total": int(row["total"] or 0) if row is not None else 0,
            "installed": int(row["installed"] or 0) if row is not None else 0,
        }

    def clear_amazon_library(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM amazon_library")

    def delete_amazon_games(self) -> int:
        """Remove Amazon entries from the main library (game files stay)."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM library WHERE is_amazon = 1"
            )
        return int(cursor.rowcount or 0)

    # ------------------------------------------------------- generic store data
    def find_store_game(self, store: str, store_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM library WHERE store = ? AND store_id = ?",
                (str(store), str(store_id)),
            ).fetchone()
        return self._clean_row(row) if row else None

    def upsert_store_game(self, store: str, **values: Any) -> tuple[int, bool]:
        store_id = str(values.get("store_id", "") or "")
        existing = self.find_store_game(store, store_id) if store_id else None
        if existing:
            updates: dict[str, Any] = {
                "name": values.get("name", existing["name"])
            }
            if values.get("cover_path"):
                updates["cover_path"] = values["cover_path"]
            if values.get("exe_path"):
                updates["exe_path"] = values["exe_path"]
            self.update_game(existing["id"], **updates)
            return existing["id"], False
        values["store"] = store
        values["store_id"] = store_id
        return self.add_game(**values), True

    def replace_store_library(
        self,
        store: str,
        games: Iterable[dict[str, Any]],
        synced_at: str = "",
    ) -> None:
        with self._lock:
            existing = {
                str(row["store_id"]): (
                    str(row["cover_path"] or ""),
                    str(row["spec_json"] or ""),
                    str(row["extra_json"] or ""),
                    int(row["size"] or 0),
                )
                for row in self._conn.execute(
                    "SELECT store_id, cover_path, spec_json, extra_json, size "
                    "FROM store_library WHERE store = ?",
                    (str(store),),
                ).fetchall()
            }
        rows: list[tuple[str, str, str, str, str, str, str, str, int, str, str, int, str, str, str]] = []
        for game in games:
            store_id = str(game.get("store_id", "") or "").strip()
            title = str(game.get("title", "") or "").strip()
            if not store_id or not title:
                continue
            previous_cover, previous_spec, previous_extra, previous_size = existing.get(
                store_id, ("", "", "", 0)
            )
            rows.append(
                (
                    str(store),
                    store_id,
                    title,
                    str(game.get("description", "") or ""),
                    str(game.get("developer", "") or ""),
                    str(game.get("icon_url", "") or ""),
                    str(game.get("cover_url", "") or ""),
                    str(game.get("cover_path") or previous_cover),
                    1 if game.get("installed") else 0,
                    str(game.get("install_path", "") or ""),
                    str(game.get("version", "") or ""),
                    int(game.get("size", 0) or previous_size or 0),
                    str(game.get("spec_json") or previous_spec),
                    str(game.get("extra_json") or previous_extra),
                    synced_at,
                )
            )
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM store_library WHERE store = ?", (str(store),)
            )
            self._conn.executemany(
                "INSERT INTO store_library(store, store_id, title, description, "
                "developer, icon_url, cover_url, cover_path, installed, "
                "install_path, version, size, spec_json, extra_json, last_synced) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _clean_store_row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["store"] = str(item.get("store") or "")
        item["store_id"] = str(item.get("store_id") or "")
        item["installed"] = int(bool(item.get("installed", 0)))
        item["install_path"] = str(item.get("install_path") or "")
        item["version"] = str(item.get("version") or "")
        item["size"] = int(item.get("size", 0) or 0)
        item["cover_path"] = str(item.get("cover_path") or "")
        item["cover_url"] = str(item.get("cover_url") or "")
        item["icon_url"] = str(item.get("icon_url") or "")
        item["description"] = str(item.get("description") or "")
        item["developer"] = str(item.get("developer") or "")
        item["spec_json"] = str(item.get("spec_json") or "")
        item["extra_json"] = str(item.get("extra_json") or "")
        return item

    def list_store_library(
        self,
        store: str,
        search: str = "",
        installed: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["store = ?"]
        params: list[Any] = [str(store)]
        if search.strip():
            clauses.append("title LIKE ? COLLATE NOCASE")
            params.append(f"%{search.strip()}%")
        if installed is not None:
            clauses.append("installed = ?")
            params.append(1 if installed else 0)
        where = " AND ".join(clauses)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM store_library WHERE {where} "
                "ORDER BY installed DESC, title COLLATE NOCASE",
                params,
            ).fetchall()
        return [self._clean_store_row(row) for row in rows]

    def get_store_library_game(
        self, store: str, store_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM store_library WHERE store = ? AND store_id = ?",
                (str(store), str(store_id)),
            ).fetchone()
        return self._clean_store_row(row) if row else None

    def set_store_cover(self, store: str, store_id: str, cover_path: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE store_library SET cover_path = ? "
                "WHERE store = ? AND store_id = ?",
                (str(cover_path), str(store), str(store_id)),
            )

    def set_store_size(self, store: str, store_id: str, size: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE store_library SET size = ? "
                "WHERE store = ? AND store_id = ?",
                (int(size or 0), str(store), str(store_id)),
            )

    def set_store_spec(self, store: str, store_id: str, spec_json: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE store_library SET spec_json = ? "
                "WHERE store = ? AND store_id = ?",
                (str(spec_json), str(store), str(store_id)),
            )

    def update_store_install(
        self,
        store: str,
        store_id: str,
        *,
        installed: bool,
        install_path: str = "",
        version: str = "",
        size: int = 0,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE store_library SET installed = ?, install_path = ?, "
                "version = ?, size = ? WHERE store = ? AND store_id = ?",
                (
                    1 if installed else 0,
                    str(install_path or ""),
                    str(version or ""),
                    int(size or 0),
                    str(store),
                    str(store_id),
                ),
            )

    def store_library_stats(self, store: str) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(installed), 0) AS installed "
                "FROM store_library WHERE store = ?",
                (str(store),),
            ).fetchone()
        return {
            "total": int(row["total"] or 0) if row is not None else 0,
            "installed": int(row["installed"] or 0) if row is not None else 0,
        }

    def clear_store_library(self, store: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM store_library WHERE store = ?", (str(store),)
            )

    def delete_store_games(self, store: str) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM library WHERE store = ?", (str(store),)
            )
        return int(cursor.rowcount or 0)

    # -------------------------------------------------------------------- caches
    def clear_shader_cache(self, game_id: int | None = None) -> int:
        """Delete only known shader-cache locations, never game/prefix data."""
        removed = 0
        candidates: list[Path] = [
            SHADER_DIR,
            Path.home() / ".cache" / "boostlayer" / "shaders",
        ]
        if game_id is not None:
            game = self.get_game(game_id)
            if game and game.get("wine_prefix"):
                prefix = Path(game["wine_prefix"]).expanduser()
                prefix_roots = [prefix]
                if (prefix / "pfx").is_dir():
                    # Proton stores its Wine prefix below <compatdata>/pfx.
                    prefix_roots.append(prefix / "pfx")
                for prefix_root in prefix_roots:
                    users = prefix_root / "drive_c" / "users"
                    if not users.is_dir():
                        continue
                    for user_dir in users.iterdir():
                        if not user_dir.is_dir():
                            continue
                        local = user_dir / "AppData" / "Local"
                        for relative in (
                            "DXVK",
                            "vkd3d-proton",
                            "D3DSCache",
                            "AMD" / "DxCache",
                            "NVIDIA" / "DXCache",
                            "Microsoft" / "DirectX Shader Cache",
                        ):
                            candidates.append(local / relative)
        for candidate in candidates:
            try:
                if candidate.is_dir() and not candidate.is_symlink():
                    shutil.rmtree(candidate)
                    removed += 1
            except OSError:
                continue
        ensure_app_dirs()
        return removed

    def stats(self) -> dict[str, int]:
        with self._lock:
            games = int(
                self._conn.execute("SELECT COUNT(*) FROM library").fetchone()[0]
            )
            steam = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM library WHERE is_steam = 1"
                ).fetchone()[0]
            )
            amazon = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM library WHERE is_amazon = 1"
                ).fetchone()[0]
            )
            stores = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM library WHERE store <> ''"
                ).fetchone()[0]
            )
        return {"games": games, "steam": steam, "amazon": amazon, "stores": stores}
