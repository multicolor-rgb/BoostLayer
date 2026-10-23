"""Boostlayer runtime core: paths, networking, runners and Steam import.

Kept separate from the PyQt6 presentation layer so every operation can be
tested without a display server.  Runtime dependencies: Python stdlib + PyQt6
(only QThread/QtGui for download signals and the generated icon).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import signal
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRectF, QThread, Qt, pyqtSignal

from i18n import tr
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
)

import db
from db import Database

APP_NAME = "Boostlayer"
APP_ID = "boostlayer"


def _read_version() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for candidate in (base / "VERSION", Path(__file__).resolve().with_name("VERSION")):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return "0.1.0"


APP_VERSION = _read_version()
USER_AGENT = f"Boostlayer/{APP_VERSION} (Linux)"
LOG_PATH = db.CONFIG_DIR / "boostlayer.log"
LAST_RUN_LOG = db.CONFIG_DIR / "last_run.log"

db.ensure_app_dirs()
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("boostlayer")

GITHUB_REPOS = {
    "proton_ge": ("Proton-GE", "GloriousEggroll/proton-ge-custom"),
    "wine_ge": ("Wine-GE", "GloriousEggroll/wine-ge-custom"),
}

RELEASE_CACHE_TTL = 6 * 60 * 60


def releases_cache_path(repo_key: str) -> Path:
    cache_dir = db.CONFIG_DIR / "cache" / "releases"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{repo_key}.json"


def choose_runner_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick a usable runner archive for the current CPU architecture."""
    archives = [
        item
        for item in assets
        if str(item.get("name", "")).endswith((".tar.gz", ".tar.xz"))
    ]
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        arch_tokens = ("aarch64", "arm64")
    else:
        arch_tokens = ("x86_64", "amd64")
    matching = [
        item
        for item in archives
        if any(token in str(item.get("name", "")).lower() for token in arch_tokens)
    ]
    return (matching or archives or [None])[0]


def fetch_runner_releases(
    repo_key: str,
    *,
    limit: int = 100,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Fetch GitHub releases, with a disk cache and stale-cache fallback."""
    _, repo = GITHUB_REPOS[repo_key]
    cache_path = releases_cache_path(repo_key)
    now = time.time()

    if not force and cache_path.is_file():
        try:
            age = now - cache_path.stat().st_mtime
            if age < RELEASE_CACHE_TTL:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    return cached[:limit]
        except (OSError, ValueError):
            pass

    try:
        with http_open(
            f"https://api.github.com/repos/{repo}/releases?per_page={max(1, min(limit, 100))}",
            timeout=30,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError(tr("Nieoczekiwana odpowiedź GitHub API."))
        releases = []
        for release in payload:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            assets = [
                asset
                for asset in (release.get("assets") or [])
                if isinstance(asset, dict)
            ]
            if not any(
                str(asset.get("name", "")).endswith((".tar.gz", ".tar.xz"))
                for asset in assets
            ):
                continue
            releases.append(
                {
                    "tag_name": str(release.get("tag_name") or ""),
                    "name": str(release.get("name") or ""),
                    "published_at": str(release.get("published_at") or ""),
                    "prerelease": bool(release.get("prerelease")),
                    "assets": assets,
                }
            )
        releases.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        try:
            cache_path.write_text(
                json.dumps(releases, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return releases[:limit]
    except (OSError, ValueError, urllib.error.URLError) as exc:
        log.warning("Cannot fetch runner releases: %s", exc)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return cached[:limit]
        except (OSError, ValueError):
            pass
        raise


class RunnerReleasesWorker(QThread):
    result = pyqtSignal(object)

    def __init__(
        self,
        repo_key: str,
        *,
        force: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.repo_key = repo_key
        self.force = force

    def run(self) -> None:
        try:
            releases = fetch_runner_releases(self.repo_key, force=self.force)
            self.result.emit({"ok": True, "releases": releases})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


def resource_path(name: str) -> Path:
    candidates = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name,
        Path(__file__).resolve().parent / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def ensure_launcher() -> Path:
    source = resource_path("launcher.sh")
    target = db.CONFIG_DIR / "launcher.sh"
    try:
        payload = source.read_bytes()
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
        target.chmod(0o755)
    except OSError as exc:
        log.warning("Cannot stage launcher.sh: %s", exc)
        if target.exists():
            target.chmod(0o755)
            return target
        return source
    return target


def app_exec_command() -> list[str]:
    """Return the argv prefix that starts this Boostlayer build.

    AppImages mount themselves in a temporary directory.  When frozen, prefer
    $APPIMAGE so a generated Steam wrapper keeps working after the mount is
    removed.
    """
    if getattr(sys, "frozen", False):
        appimage = os.environ.get("APPIMAGE", "").strip()
        if appimage and Path(appimage).is_file():
            return [appimage]
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().with_name("main.py"))]


def steam_wrapper_path() -> Path:
    return db.CONFIG_DIR / "steam-wrapper.sh"


def ensure_steam_wrapper() -> Path:
    """Create/refresh a tiny POSIX wrapper used in Steam launch options.

    Steam sets SteamAppId/SteamGameId for the process that runs the launch
    options.  The wrapper forwards those values to Boostlayer's CLI mode, which
    builds the environment and then execs the original %command%.
    """
    db.ensure_app_dirs()
    target = steam_wrapper_path()
    command = " ".join(shlex.quote(part) for part in app_exec_command())
    payload = f"""#!/bin/sh
# Generated by Boostlayer.  Use as a Steam launch option:
#   {shlex.quote(str(target))} %command%
set -u
APPID=${{SteamAppId:-${{SteamGameId:-}}}}
exec {command} --steam-exec "$APPID" -- "$@"
"""
    try:
        if not target.is_file() or target.read_text(encoding="utf-8") != payload:
            target.write_text(payload, encoding="utf-8")
        target.chmod(0o700)
    except OSError as exc:
        log.warning("Cannot write Steam wrapper: %s", exc)
        raise
    return target


def steam_launch_option(wrapper: Path | None = None) -> str:
    path = wrapper or steam_wrapper_path()
    return f"{shlex.quote(str(path))} %command%"


def steam_client_command() -> list[str] | None:
    """Locate native Steam, then the Flatpak build."""
    native = shutil.which("steam")
    if native:
        return [native]
    flatpak = shutil.which("flatpak")
    if flatpak:
        return [flatpak, "run", "com.valvesoftware.Steam"]
    return None


def find_proton_script(wine_path: str | Path) -> Path | None:
    path = Path(wine_path)
    for parent in (path.parent, *path.parents):
        candidate = parent / "proton"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


@dataclass(frozen=True)
class ToolStatus:
    key: str
    label: str
    binary: str
    package: str
    path: str

    @property
    def installed(self) -> bool:
        return bool(self.path)


TOOL_SPECS = (
    ("wine", "Wine", "wine", "wine"),
    ("gamemoderun", "GameMode", "gamemoderun", "gamemode"),
    ("mangohud", "MangoHud", "mangohud", "mangohud"),
    ("gamescope", "Gamescope", "gamescope", "gamescope"),
)


def tool_status() -> list[ToolStatus]:
    result: list[ToolStatus] = []
    for key, label, binary, package in TOOL_SPECS:
        path = shutil.which(binary) or ""
        result.append(ToolStatus(key, label, binary, package, path))
    return result


def missing_tools() -> list[ToolStatus]:
    return [tool for tool in tool_status() if not tool.installed]


INSTALLABLE_TOOLS = {"gamemoderun", "mangohud", "gamescope"}


def missing_installable_tools() -> list[ToolStatus]:
    return [tool for tool in missing_tools() if tool.key in INSTALLABLE_TOOLS]


def gamemode32_installed() -> bool:
    return Path("/usr/lib/i386-linux-gnu/libgamemodeauto.so.0").is_file()


def package_manager() -> str:
    for manager in ("apt-get", "dnf", "pacman"):
        if shutil.which(manager):
            return manager
    return ""


@dataclass(frozen=True)
class DependencyGroup:
    label: str
    packages: tuple[str, ...]
    argv: tuple[str, ...]

    @property
    def command(self) -> str:
        return " ".join(shlex.quote(item) for item in self.argv)


def dependency_install_groups() -> list[DependencyGroup]:
    """Build package-manager commands for missing optional tools.

    MangoHud and GameMode are one group; Gamescope is separate because some
    distributions (notably Ubuntu 24.04) do not ship it.  That way a missing
    Gamescope package cannot block the MangoHud installation.
    """
    manager = package_manager()
    pkexec = shutil.which("pkexec")
    if not manager or not pkexec:
        return []
    missing = {tool.key for tool in missing_installable_tools()}
    groups: list[tuple[str, tuple[str, ...]]] = []
    core_packages: list[str] = []
    if "mangohud" in missing:
        core_packages.append("mangohud")
    if "gamemoderun" in missing:
        core_packages.append("gamemode")
    if core_packages:
        groups.append(("MangoHud + GameMode", tuple(core_packages)))
    if "gamescope" in missing:
        groups.append(("Gamescope", ("gamescope",)))
    if manager == "apt-get" and not gamemode32_installed():
        groups.append(
            (
                "GameMode 32-bit",
                ("libgamemode0:i386", "libgamemodeauto0:i386"),
            )
        )

    manager_path = shutil.which(manager) or manager
    result: list[DependencyGroup] = []
    for label, packages in groups:
        if manager == "apt-get":
            argv = (pkexec, manager_path, "install", "-y", *packages)
        elif manager == "dnf":
            argv = (pkexec, manager_path, "install", "-y", *packages)
        else:
            argv = (pkexec, manager_path, "-S", "--needed", "--noconfirm", *packages)
        result.append(DependencyGroup(label, packages, argv))
    return result


def ensure_crt_shader() -> Path:
    source = resource_path("assets/crt.fx")
    target = db.SHADER_DIR / "crt.fx"
    try:
        payload = source.read_bytes()
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
    except OSError as exc:
        log.warning("Cannot stage CRT shader: %s", exc)
        return source
    return target


def _icon_pixmap(size: int) -> QPixmap:
    """Black rounded square with a white BL monogram."""
    size = max(8, int(size))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(0.5, 0.5, size - 1.0, size - 1.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#000000"))
    painter.drawRoundedRect(rect, size * 0.22, size * 0.22)

    font = QFont("DejaVu Sans")
    font.setPixelSize(max(6, int(size * 0.50)))
    font.setWeight(QFont.Weight.Black)
    font.setLetterSpacing(
        QFont.SpacingType.AbsoluteSpacing, -size * 0.045
    )
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "BL")

    painter.end()
    return pixmap


def app_icon(size: int = 256) -> QIcon:
    """Return the black-and-white BL icon, with multiple native sizes."""
    icon = QIcon()
    for icon_size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_icon_pixmap(icon_size))
    if size not in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_icon_pixmap(max(16, int(size))))
    return icon


def human_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"


def exe_bits(path: str | Path) -> int | None:
    """Return 32/64 for a PE executable, or None for non-PE/missing files."""
    try:
        with Path(path).open("rb") as handle:
            dos = handle.read(0x40)
            if len(dos) < 0x40 or dos[:2] != b"MZ":
                return None
            pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
            handle.seek(pe_offset)
            header = handle.read(6)
            if len(header) < 6 or header[:4] != b"PE\0\0":
                return None
            machine = struct.unpack_from("<H", header, 4)[0]
    except (OSError, struct.error):
        return None
    if machine == 0x014C:
        return 32
    if machine in {0x8664, 0xAA64}:
        return 64
    return None


def mangohud32_script() -> Path:
    return resource_path("tools/install-mangohud32.sh")


def gamepad_udev_script() -> Path:
    return resource_path("tools/install-gamepad-udev.sh")


def mangohud32_path() -> str:
    for candidate in (
        "/usr/lib/i386-linux-gnu/mangohud/libMangoHud.so",
        "/usr/lib32/mangohud/libMangoHud.so",
        "/usr/lib32/libMangoHud.so",
        "/usr/lib/i386-linux-gnu/libMangoHud.so",
    ):
        if Path(candidate).is_file():
            return candidate
    return ""


def mangohud_library_path(bits: int | None) -> str:
    if bits == 32:
        return mangohud32_path()
    if bits == 64:
        for candidate in (
            "/usr/lib/x86_64-linux-gnu/mangohud/libMangoHud.so",
            "/usr/lib64/mangohud/libMangoHud.so",
            "/usr/lib/mangohud/libMangoHud.so",
        ):
            if Path(candidate).is_file():
                return candidate
    return ""


def http_open(url: str, timeout: int = 30):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json, image/avif,image/webp,image/*,*/*",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def github_json(path: str) -> dict[str, Any]:
    with http_open(f"https://api.github.com{path}", timeout=30) as response:
        payload = response.read()
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(tr("Nieoczekiwana odpowiedź GitHub API."))
    return data


def download_file(
    url: str,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
    timeout: int = 90,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{uuid.uuid4().hex}.part")
    total = 0
    try:
        with http_open(url, timeout=timeout) as response, temporary.open("wb") as out:
            try:
                expected = int(response.headers.get("Content-Length", "0") or 0)
            except ValueError:
                expected = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                total += len(chunk)
                if progress:
                    progress(total, expected)
        if total <= 0:
            raise OSError(tr("Serwer zwrócił pusty plik."))
        if expected > 0 and total != expected:
            raise OSError(
                tr("Niekompletne pobieranie: {received} z {expected} bajtów.", received=total, expected=expected)
            )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def safe_extract_tar(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()
    with tarfile.open(archive, mode="r:*") as tar:
        members = tar.getmembers()
        for member in members:
            if member.isdev():
                raise ValueError(tr("Urządzenie w archiwum jest niedozwolone: {name}", name=member.name))
            member_path = (target / member.name).resolve()
            if member_path != target_resolved and target_resolved not in member_path.parents:
                raise ValueError(tr("Niebezpieczna ścieżka w archiwum: {name}", name=member.name))
            if member.issym() or member.islnk():
                link_path = (member_path.parent / member.linkname).resolve()
                if link_path != target_resolved and target_resolved not in link_path.parents:
                    raise ValueError(tr("Niebezpieczny link w archiwum: {name}", name=member.name))
        try:
            tar.extractall(target, members=members, filter="data")
        except TypeError:
            tar.extractall(target, members=members)


@dataclass(frozen=True)
class RunnerInfo:
    kind: str
    version: str
    path: str

    @property
    def label(self) -> str:
        kind = {"proton": "Proton", "wine": "Wine", "system": "System"}.get(
            self.kind, self.kind.title()
        )
        return f"{self.version}  [{kind}]"


def find_wine_in_root(root: Path) -> Path | None:
    candidates = [
        root / "files" / "bin" / "wine",
        root / "bin" / "wine",
        root / "wine",
    ]
    if root.is_dir():
        try:
            children = [child for child in root.iterdir() if child.is_dir()]
        except OSError:
            children = []
        for child in children:
            candidates.extend(
                [
                    child / "files" / "bin" / "wine",
                    child / "bin" / "wine",
                    child / "wine",
                ]
            )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def discover_runners() -> list[RunnerInfo]:
    found: list[RunnerInfo] = []
    seen: set[str] = set()
    system_wine = shutil.which("wine")
    if system_wine:
        found.append(RunnerInfo("system", "Systemowe Wine", system_wine))
        seen.add(str(Path(system_wine).resolve()))

    if not db.RUNNERS_DIR.is_dir():
        return found
    try:
        entries = sorted(
            (entry for entry in db.RUNNERS_DIR.iterdir() if entry.is_dir()),
            key=lambda item: item.name.lower(),
            reverse=True,
        )
    except OSError:
        return found

    for entry in entries:
        wine = find_wine_in_root(entry)
        if not wine:
            continue
        try:
            wine_resolved = str(wine.resolve())
        except OSError:
            wine_resolved = str(wine)
        if wine_resolved in seen:
            continue
        seen.add(wine_resolved)
        version = entry.name
        try:
            relative = wine.relative_to(entry)
            if len(relative.parts) > 3:
                version = relative.parts[0]
        except ValueError:
            pass
        kind = "proton" if find_proton_script(wine) is not None else "wine"
        found.append(RunnerInfo(kind, version, str(wine)))
    return found


def _runner_kind_for(path: Path, root: Path | None = None) -> str:
    if find_proton_script(path) is not None:
        return "proton"
    return "wine"


def resolve_runner(stored_path: str, default_path: str = "") -> RunnerInfo | None:
    requested = (stored_path or default_path or "").strip()
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.is_dir():
            wine = find_wine_in_root(candidate)
            if wine:
                return RunnerInfo(
                    _runner_kind_for(wine, candidate), candidate.name, str(wine)
                )
        elif candidate.is_file():
            return RunnerInfo(
                _runner_kind_for(candidate), candidate.parent.name or "Wine", str(candidate)
            )
    system_wine = shutil.which("wine")
    if system_wine:
        return RunnerInfo("system", "Systemowe Wine", system_wine)
    runners = discover_runners()
    return runners[0] if runners else None


WINETRICKS_URL = (
    "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks"
)
WINETRICKS_MARKER = ".boostlayer-winetricks"
WINETRICKS_LOG = db.CONFIG_DIR / "winetricks.log"
_WINETRICKS_VERB_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}")


def local_winetricks_path() -> Path:
    return db.CONFIG_DIR / "tools" / "winetricks"


def winetricks_path() -> str:
    """Prefer the system package, then a private copy downloaded by Boostlayer."""
    system = shutil.which("winetricks")
    if system:
        return system
    local = local_winetricks_path()
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return ""


def protontricks_path() -> str:
    return shutil.which("protontricks") or ""


def download_winetricks(
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download the official Winetricks script into Boostlayer's config dir."""
    target = local_winetricks_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    download_file(WINETRICKS_URL, target, progress=progress, timeout=90)
    try:
        payload = target.read_bytes()[:8192]
    except OSError as exc:
        raise OSError(tr("Nie można odczytać pobranego Winetricks.")) from exc
    if b"WINETRICKS_VERSION" not in payload:
        target.unlink(missing_ok=True)
        raise ValueError(tr("Pobrany plik nie wygląda na Winetricks."))
    target.chmod(0o700)
    return target


def normalize_winetricks_verbs(verbs: Iterable[str] | str) -> list[str]:
    """Normalize and validate Winetricks verb names.

    Verbs are executed through an argument vector, never through a shell, but
    rejecting unexpected characters still keeps stored state unambiguous.
    """
    if isinstance(verbs, str):
        raw = re.split(r"[\s,]+", verbs.strip())
    else:
        raw = []
        for value in verbs:
            raw.extend(re.split(r"[\s,]+", str(value).strip()))
    result: list[str] = []
    for verb in raw:
        if not verb:
            continue
        if not _WINETRICKS_VERB_RE.fullmatch(verb):
            raise ValueError(tr("Nieprawidłowa nazwa komponentu Winetricks: {verb}", verb=verb))
        if verb not in result:
            result.append(verb)
    return result


def winetricks_verbs_text(verbs: Iterable[str] | str) -> str:
    return " ".join(normalize_winetricks_verbs(verbs))


def winetricks_actual_prefix(
    game: dict[str, Any], runner: RunnerInfo, *, create: bool = True
) -> Path:
    prefix_text = str(game.get("wine_prefix", "") or "").strip()
    if not prefix_text:
        raise RuntimeError(tr("Gra nie ma ustawionego WINEPREFIX."))
    prefix = Path(prefix_text).expanduser()
    if create:
        prefix.mkdir(parents=True, exist_ok=True)
    # Proton owns a pfx directory inside STEAM_COMPAT_DATA_PATH.
    return prefix / "pfx" if runner.kind == "proton" else prefix


def _executable_stamp(path: str) -> str:
    try:
        stat = os.stat(path)
        return f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return path


def winetricks_state_hash(
    verbs: Iterable[str],
    executable: str,
    runner_path: str = "",
    appid: str = "",
    winetricks: str = "",
) -> str:
    payload = "\n".join(
        [
            executable,
            _executable_stamp(executable),
            runner_path,
            appid,
            winetricks,
            *sorted(set(verbs)),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class WinetricksPlan:
    command: tuple[str, ...]
    env: dict[str, str]
    mode: str
    verbs: tuple[str, ...]
    state: str
    prefix: Path | None = None
    marker: Path | None = None


def build_winetricks_plan(
    database: "db.Database",
    game: dict[str, Any],
    verbs: Iterable[str] | str,
) -> WinetricksPlan:
    normalized = normalize_winetricks_verbs(verbs)
    if not normalized:
        raise ValueError(tr("Wybierz co najmniej jeden komponent Winetricks."))
    if game.get("is_steam"):
        appid = str(game.get("steam_appid", "")).strip()
        if not appid:
            raise RuntimeError(tr("Brak AppID Steam dla tej gry."))
        protontricks = protontricks_path()
        if not protontricks:
            raise RuntimeError(
                tr(
                    "Protontricks nie jest zainstalowany. Zainstaluj go, aby "
                    "używać Winetricks dla gier Steam."
                )
            )
        winetricks = winetricks_path()
        if not winetricks:
            raise RuntimeError(
                tr(
                    "Winetricks nie jest zainstalowany. Zainstaluj go w "
                    "Ustawieniach → Zależności."
                )
            )
        env = os.environ.copy()
        env["WINETRICKS"] = winetricks
        if database is not None:
            steam_path = str(database.get_setting("steam_path", "") or "").strip()
            if steam_path:
                env["STEAM_DIR"] = steam_path
        state = winetricks_state_hash(
            normalized, protontricks, appid=appid, winetricks=winetricks
        )
        return WinetricksPlan(
            command=(protontricks, appid, "-q", *normalized),
            env=env,
            mode="steam",
            verbs=tuple(normalized),
            state=state,
        )

    runner = resolve_runner(
        str(game.get("runner_path", "")),
        str(database.get_setting("default_runner", "")),
    )
    if runner is None:
        raise RuntimeError(
            tr(
                "Brak runnera Wine. Zainstaluj Wine albo pobierz Proton-GE/Wine-GE "
                "w Menedżerze runnerów."
            )
        )
    winetricks = winetricks_path()
    if not winetricks:
        raise RuntimeError(
            tr(
                "Winetricks nie jest zainstalowany. Zainstaluj go w "
                "Ustawieniach → Zależności."
            )
        )
    prefix = winetricks_actual_prefix(game, runner)
    env = os.environ.copy()
    env.update(parse_env_vars(str(game.get("env_vars", ""))))
    env["WINEPREFIX"] = str(prefix)
    env["WINE"] = runner.path
    wineserver = Path(runner.path).with_name("wineserver")
    if wineserver.is_file():
        env["WINESERVER"] = str(wineserver)
    if runner.kind == "proton":
        env["STEAM_COMPAT_DATA_PATH"] = str(Path(game.get("wine_prefix", "")).expanduser())
    env["WINEDEBUG"] = "-all"
    env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
    env["W_OPT_UNATTENDED"] = "1"
    state = winetricks_state_hash(
        normalized, winetricks, runner.path, winetricks=winetricks
    )
    marker = prefix / WINETRICKS_MARKER
    return WinetricksPlan(
        command=(winetricks, "-q", *normalized),
        env=env,
        mode=runner.kind,
        verbs=tuple(normalized),
        state=state,
        prefix=prefix,
        marker=marker,
    )


def winetricks_applied(game: dict[str, Any], plan: WinetricksPlan) -> bool:
    if plan.marker is not None:
        try:
            return plan.marker.read_text(encoding="utf-8").strip() == plan.state
        except OSError:
            return False
    return str(game.get("winetricks_state", "")) == plan.state


def write_winetricks_marker(plan: WinetricksPlan) -> None:
    if plan.marker is None:
        return
    try:
        plan.marker.write_text(plan.state + "\n", encoding="utf-8")
        plan.marker.chmod(0o600)
    except OSError as exc:
        log.warning("Cannot write Winetricks marker: %s", exc)


class WinetricksInstallWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    result = pyqtSignal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            self.status.emit(tr("Pobieram Winetricks..."))

            def report(current: int, expected: int) -> None:
                if expected > 0:
                    self.progress.emit(min(100, int(current * 100 / expected)))

            target = download_winetricks(progress=report)
            self.result.emit(True, str(target))
        except Exception as exc:
            log.error("Winetricks download failed: %s", traceback.format_exc())
            self.result.emit(False, str(exc))


class WinetricksWorker(QThread):
    output = pyqtSignal(str)
    result = pyqtSignal(bool, str)

    def __init__(self, plan: WinetricksPlan, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self) -> None:
        if self._cancelled:
            self.result.emit(False, tr("Instalacja Winetricks została anulowana."))
            return
        WINETRICKS_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            WINETRICKS_LOG.write_text(
                f"=== Boostlayer Winetricks {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n",
                encoding="utf-8",
            )
            WINETRICKS_LOG.chmod(0o600)
        except OSError:
            pass
        try:
            self._process = subprocess.Popen(
                list(self.plan.command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.plan.env,
                start_new_session=True,
            )
            assert self._process.stdout is not None
            with WINETRICKS_LOG.open("a", encoding="utf-8") as log_file:
                for line in self._process.stdout:
                    self.output.emit(line.rstrip("\n"))
                    log_file.write(line)
            code = self._process.wait()
            if code == 0 and not self._cancelled:
                write_winetricks_marker(self.plan)
                self.result.emit(True, str(WINETRICKS_LOG))
            elif self._cancelled:
                self.result.emit(False, tr("Instalacja Winetricks została anulowana."))
            else:
                self.result.emit(
                    False,
                    tr("Winetricks zakończył się kodem {code}. Log: {path}", code=code, path=WINETRICKS_LOG),
                )
        except FileNotFoundError:
            self.result.emit(False, tr("Nie znaleziono programu Winetricks."))
        except Exception as exc:
            log.error("Winetricks failed: %s", traceback.format_exc())
            self.result.emit(False, str(exc))


def steam_game_process_running(appid: str, exe_path: str = "") -> bool:
    """Best-effort detection of a running Steam/Proton game process.

    Steam does not expose a completion signal to external launchers.  Looking
    for the inherited ``SteamAppId``/``SteamGameId`` variables is reliable for
    the lifetime of the game process; the executable name is only a fallback.
    """
    appid = str(appid or "").strip()
    if not appid:
        return False
    app_tag = f"SteamAppId={appid}".encode("utf-8", errors="ignore")
    game_tag = f"SteamGameId={appid}".encode("utf-8", errors="ignore")
    exe_name = Path(str(exe_path or "")).name.lower().encode("utf-8")
    own_pid = os.getpid()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            environ = (entry / "environ").read_bytes()[:65536]
            if app_tag in environ or game_tag in environ:
                return True
            if exe_name:
                cmdline = (entry / "cmdline").read_bytes().lower()
                if exe_name in cmdline:
                    return True
        except (OSError, ValueError):
            continue
    return False


def parse_env_vars(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for number, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(tr("Zmienna środowiskowa w linii {line} nie ma znaku '='.", line=number))
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(tr("Nieprawidłowa nazwa zmiennej w linii {line}: {key}", line=number, key=key))
        env[key] = value.strip()
    return env


# ---------------------------------------------------------------------------
# Steam
# ---------------------------------------------------------------------------
def _vdf_unescape(value: str) -> str:
    return value.replace("\\\\", "\\").replace('\\"', '"')


def _acf_value(text: str, key: str) -> str:
    match = re.search(
        rf'"{re.escape(key)}"\s+"((?:[^"\\]|\\.)*)"', text, flags=re.IGNORECASE
    )
    if not match:
        return ""
    return _vdf_unescape(match.group(1))


@dataclass
class _VdfEntry:
    key: str
    key_start: int
    key_end: int
    value: str | None
    value_start: int
    value_end: int
    children: list["_VdfEntry"]
    open_start: int
    close_start: int
    close_end: int

    @property
    def is_block(self) -> bool:
        return self.open_start >= 0


@dataclass
class _VdfToken:
    kind: str
    value: str
    start: int
    end: int


def _vdf_tokens(text: str) -> list[_VdfToken]:
    tokens: list[_VdfToken] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\r\n":
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if char in "{}":
            tokens.append(_VdfToken("brace", char, index, index + 1))
            index += 1
            continue
        if char == '"':
            start = index
            index += 1
            buffer: list[str] = []
            while index < length:
                current = text[index]
                if current == "\\" and index + 1 < length:
                    buffer.append(current)
                    buffer.append(text[index + 1])
                    index += 2
                    continue
                if current == '"':
                    index += 1
                    break
                buffer.append(current)
                index += 1
            else:
                raise ValueError(tr("Nieukończony string w pliku VDF."))
            tokens.append(
                _VdfToken("string", _vdf_unescape("".join(buffer)), start, index)
            )
            continue
        start = index
        while index < length and text[index] not in " \t\r\n{}":
            if text.startswith("//", index):
                break
            index += 1
        if index == start:
            raise ValueError(tr("Nieprawidłowy token w pliku VDF."))
        tokens.append(_VdfToken("string", text[start:index], start, index))
    return tokens


def _vdf_parse(text: str) -> list[_VdfEntry]:
    tokens = _vdf_tokens(text)
    position = 0

    def parse_entries(expect_close: bool) -> tuple[list[_VdfEntry], _VdfToken | None]:
        nonlocal position
        entries: list[_VdfEntry] = []
        while position < len(tokens):
            token = tokens[position]
            if token.kind == "brace" and token.value == "}":
                if not expect_close:
                    raise ValueError(tr("Nadmiarowy znak '}' w pliku VDF."))
                position += 1
                return entries, token
            if token.kind != "string":
                raise ValueError(tr("Oczekiwano klucza VDF."))
            key_token = token
            position += 1
            if position >= len(tokens):
                raise ValueError(tr("Brak wartości dla klucza VDF."))
            value_token = tokens[position]
            if value_token.kind == "brace" and value_token.value == "{":
                position += 1
                children, close_token = parse_entries(True)
                if close_token is None:
                    raise ValueError(tr("Nieukończony blok VDF."))
                entries.append(
                    _VdfEntry(
                        key=key_token.value,
                        key_start=key_token.start,
                        key_end=key_token.end,
                        value=None,
                        value_start=-1,
                        value_end=-1,
                        children=children,
                        open_start=value_token.start,
                        close_start=close_token.start,
                        close_end=close_token.end,
                    )
                )
                continue
            if value_token.kind == "string":
                position += 1
                entries.append(
                    _VdfEntry(
                        key=key_token.value,
                        key_start=key_token.start,
                        key_end=key_token.end,
                        value=value_token.value,
                        value_start=value_token.start,
                        value_end=value_token.end,
                        children=[],
                        open_start=-1,
                        close_start=-1,
                        close_end=-1,
                    )
                )
                continue
            raise ValueError(tr("Oczekiwano wartości lub bloku VDF."))
        if expect_close:
            raise ValueError(tr("Nieukończony blok VDF."))
        return entries, None

    entries, _ = parse_entries(False)
    return entries


def _vdf_find(entries: list[_VdfEntry], key: str) -> _VdfEntry | None:
    for entry in entries:
        if entry.key == key:
            return entry
    for entry in entries:
        if entry.key.lower() == key.lower():
            return entry
    return None


def _vdf_path(entries: list[_VdfEntry], *keys: str) -> _VdfEntry | None:
    current: _VdfEntry | None = None
    scope = entries
    for key in keys:
        current = _vdf_find(scope, key)
        if current is None or not current.is_block:
            return None
        scope = current.children
    return current


def _vdf_value(entries: list[_VdfEntry], key: str) -> str | None:
    entry = _vdf_find(entries, key)
    return entry.value if entry is not None else None


def _steam_apps_entry(entries: list[_VdfEntry]) -> _VdfEntry | None:
    for path in (
        ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps"),
        ("Software", "Valve", "Steam", "apps"),
    ):
        apps = _vdf_path(entries, *path)
        if apps is not None:
            return apps
    return None


def _vdf_quote(value: str) -> str:
    cleaned = value.replace("\r", " ").replace("\n", " ")
    return '"' + cleaned.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _vdf_line_indent(text: str, offset: int) -> tuple[int, str]:
    line_start = text.rfind("\n", 0, offset) + 1
    line = text[line_start:offset]
    if line.strip() == "":
        return line_start, line
    return offset, ""


def _vdf_set_launch_options(text: str, appid: str, value: str) -> tuple[str, str]:
    entries = _vdf_parse(text)
    apps = _steam_apps_entry(entries)
    if apps is None:
        raise ValueError(
            tr("Nie znaleziono gałęzi UserLocalConfigStore/Software/Valve/Steam/apps "
            "w localconfig.vdf."))

    app = _vdf_find(apps.children, str(appid))
    newline = "\r\n" if "\r\n" in text else "\n"
    if app is None:
        insert_at, indent = _vdf_line_indent(text, apps.close_start)
        if indent == "":
            insert_at = apps.close_start
            child = "\t"
            prefix = newline
        else:
            child = indent + "\t"
            prefix = ""
        payload = (
            f'{prefix}{child}{_vdf_quote(str(appid))}{newline}'
            f"{child}{{{newline}"
            f'{child}\t"LaunchOptions"\t\t{_vdf_quote(value)}{newline}'
            f"{child}}}{newline}"
        )
        return text[:insert_at] + payload + text[insert_at:], "insert"
    if not app.is_block:
        raise ValueError(tr("AppID {appid} nie jest blokiem w localconfig.vdf.", appid=appid))
    launch = _vdf_find(app.children, "LaunchOptions")
    if launch is not None:
        if launch.value is None:
            raise ValueError(tr("LaunchOptions AppID {appid} nie jest stringiem.", appid=appid))
        new_text = (
            text[: launch.value_start]
            + _vdf_quote(value)
            + text[launch.value_end :]
        )
        return new_text, "replace"
    insert_at, indent = _vdf_line_indent(text, app.close_start)
    if indent == "":
        insert_at = app.close_start
        entry_indent = "\t"
        prefix = newline
    else:
        entry_indent = indent + "\t"
        prefix = ""
    payload = (
        f'{prefix}{entry_indent}"LaunchOptions"\t\t{_vdf_quote(value)}{newline}'
    )
    return text[:insert_at] + payload + text[insert_at:], "insert"


def get_steam_launch_options(text: str, appid: str) -> str | None:
    entries = _vdf_parse(text)
    apps = _steam_apps_entry(entries)
    if apps is None:
        return None
    app = _vdf_find(apps.children, str(appid))
    if app is None or not app.is_block:
        return None
    return _vdf_value(app.children, "LaunchOptions")


def steam_launch_action(existing: str | None, wrapper: Path | None = None) -> str:
    wrapper_path = wrapper or steam_wrapper_path()
    wrapper_option = steam_launch_option(wrapper_path)
    if existing is None:
        return "insert"
    if existing.strip().startswith(wrapper_option):
        return "ok"
    if "%command%" in existing:
        return "complex"
    if existing.strip():
        return "prepend"
    return "set"


def update_steam_launch_options(
    text: str, appid: str, wrapper: Path | None = None
) -> tuple[str, str]:
    existing = get_steam_launch_options(text, appid)
    action = steam_launch_action(existing, wrapper)
    if action == "ok":
        return text, action
    if action == "complex":
        return text, action
    wrapper_option = steam_launch_option(wrapper)
    if action == "prepend":
        desired = f"{wrapper_option} {existing.strip()}"
    else:
        desired = wrapper_option
    new_text, write_action = _vdf_set_launch_options(text, appid, desired)
    return new_text, action if action != "insert" else write_action


def _steam_process_running() -> bool:
    proc = Path("/proc")
    try:
        entries = proc.iterdir()
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            comm = ""
        if comm == "steam":
            return True
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except OSError:
            continue
        if "com.valvesoftware.Steam" in cmdline:
            return True
    return False


def steam_is_running() -> bool:
    return _steam_process_running()


def steam_shutdown(timeout: int = 20) -> bool:
    client = steam_client_command()
    if not client:
        return False
    try:
        subprocess.run(
            client + ["-shutdown"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def wait_for_steam_exit(timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not steam_is_running():
            return True
        time.sleep(0.5)
    return not steam_is_running()


@dataclass(frozen=True)
class SteamAccount:
    account_id: str
    account_name: str
    userdata: Path
    localconfig: Path
    steam_id64: str = ""


def steam_account(root: Path | None = None) -> SteamAccount | None:
    root = root or detect_steam_root()
    if root is None:
        return None
    candidates: list[tuple[bool, int, float, str, str, str, Path]] = []
    loginusers = root / "config" / "loginusers.vdf"
    if loginusers.is_file():
        try:
            text = loginusers.read_text(encoding="utf-8", errors="replace")
            entries = _vdf_parse(text)
            users = _vdf_find(entries, "users")
            if users is not None and users.is_block:
                for entry in users.children:
                    if not entry.is_block:
                        continue
                    try:
                        steam_id64 = str(entry.key).strip()
                        account_id = str(int(steam_id64) & 0xFFFFFFFF)
                    except ValueError:
                        continue
                    localconfig = (
                        root / "userdata" / account_id / "config" / "localconfig.vdf"
                    )
                    if not localconfig.is_file():
                        continue
                    auto_login = _vdf_value(entry.children, "AutoLogin") == "1"
                    try:
                        timestamp = int(_vdf_value(entry.children, "timestamp") or 0)
                    except ValueError:
                        timestamp = 0
                    try:
                        mtime = localconfig.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    name = _vdf_value(entry.children, "AccountName") or account_id
                    candidates.append(
                        (
                            auto_login,
                            timestamp,
                            mtime,
                            account_id,
                            steam_id64,
                            name,
                            localconfig,
                        )
                    )
        except (OSError, ValueError):
            pass
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        (
            auto_login,
            timestamp,
            mtime,
            account_id,
            steam_id64,
            name,
            localconfig,
        ) = candidates[0]
        return SteamAccount(
            account_id,
            name,
            localconfig.parent.parent,
            localconfig,
            steam_id64,
        )
    userdata = root / "userdata"
    if userdata.is_dir():
        discovered: list[tuple[float, str, Path]] = []
        for localconfig in userdata.glob("*/config/localconfig.vdf"):
            try:
                discovered.append(
                    (localconfig.stat().st_mtime, localconfig.parent.parent.name, localconfig)
                )
            except OSError:
                continue
        if discovered:
            discovered.sort(reverse=True)
            mtime, account_id, localconfig = discovered[0]
            return SteamAccount(
                account_id,
                account_id,
                localconfig.parent.parent,
                localconfig,
            )
    return None


def steam_launch_action_for_appid(appid: str, wrapper: Path | None = None) -> str:
    account = steam_account()
    if account is None:
        return "no_account"
    try:
        text = account.localconfig.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "no_config"
    try:
        existing = get_steam_launch_options(text, str(appid))
    except ValueError:
        return "parse_error"
    return steam_launch_action(existing, wrapper)


def _backup_localconfig(localconfig: Path) -> Path:
    backup_dir = db.CONFIG_DIR / "steam-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        backup_dir.chmod(0o700)
    except OSError:
        pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    account_id = localconfig.parent.parent.name or "unknown"
    destination = backup_dir / f"localconfig.vdf.{account_id}.{stamp}"
    counter = 1
    while destination.exists():
        destination = backup_dir / f"localconfig.vdf.{account_id}.{stamp}-{counter}"
        counter += 1
    shutil.copy2(localconfig, destination)
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    return destination


def latest_steam_backup(account_id: str | None = None) -> Path | None:
    backup_dir = db.CONFIG_DIR / "steam-backups"
    pattern = (
        f"localconfig.vdf.{account_id}.*"
        if account_id
        else "localconfig.vdf.*"
    )
    try:
        backups = sorted(
            backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime
        )
    except OSError:
        return None
    return backups[-1] if backups else None


def _write_localconfig_atomic(localconfig: Path, text: str) -> None:
    temporary = localconfig.with_name(localconfig.name + ".boostlayer.tmp")
    mode = localconfig.stat().st_mode & 0o777
    temporary.write_text(text, encoding="utf-8")
    try:
        temporary.chmod(mode)
    except OSError:
        pass
    os.replace(temporary, localconfig)


class SteamOptionsWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(
        self,
        appids: list[str],
        wrapper: Path,
        *,
        close_steam: bool = True,
        restore: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.appids = [str(appid) for appid in appids]
        self.wrapper = wrapper
        self.close_steam = close_steam
        self.restore = restore

    def run(self) -> None:
        try:
            root = detect_steam_root()
            account = steam_account(root)
            if account is None:
                self.result.emit(
                    {"ok": False, "error": tr("Nie znaleziono aktywnego profilu Steam.")}
                )
                return
            if self.restore and latest_steam_backup(account.account_id) is None:
                self.result.emit(
                    {"ok": False, "error": tr("Brak backupu localconfig.vdf.")}
                )
                return
            if steam_is_running():
                if not self.close_steam:
                    self.result.emit(
                        {
                            "ok": False,
                            "error": tr(
                                "Steam działa. Zamknij go przed edycją "
                                "localconfig.vdf."
                            ),
                        }
                    )
                    return
                self.status.emit(tr("Zamykam Steam..."))
                if not steam_shutdown():
                    self.result.emit(
                        {
                            "ok": False,
                            "error": tr(
                                "Nie udało się wysłać polecenia zamknięcia "
                                "Steama. Zamknij go ręcznie."
                            ),
                        }
                    )
                    return
                if not wait_for_steam_exit():
                    self.result.emit(
                        {
                            "ok": False,
                            "error": tr(
                                "Steam nadal działa. Zamknij go ręcznie i "
                                "spróbuj ponownie."
                            ),
                        }
                    )
                    return

            if self.restore:
                backup = latest_steam_backup(account.account_id)
                if backup is None:
                    self.result.emit(
                        {"ok": False, "error": tr("Brak backupu localconfig.vdf.")}
                    )
                    return
                text = backup.read_text(encoding="utf-8", errors="replace")
                _vdf_parse(text)
                _write_localconfig_atomic(account.localconfig, text)
                self.result.emit(
                    {
                        "ok": True,
                        "restored": str(backup),
                        "account": account.account_name,
                    }
                )
                return

            text = account.localconfig.read_text(encoding="utf-8", errors="replace")
            original = text
            updated = skipped = unchanged = 0
            for appid in self.appids:
                self.status.emit(tr("Dopisuję LaunchOptions dla AppID {appid}...", appid=appid))
                try:
                    text, action = update_steam_launch_options(
                        text, appid, self.wrapper
                    )
                except ValueError as exc:
                    log.warning("Steam launch options AppID %s: %s", appid, exc)
                    skipped += 1
                    continue
                if action == "complex":
                    skipped += 1
                elif action == "ok":
                    unchanged += 1
                else:
                    updated += 1

            if updated:
                _vdf_parse(text)
                backup = _backup_localconfig(account.localconfig)
                try:
                    _write_localconfig_atomic(account.localconfig, text)
                    check = account.localconfig.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    _vdf_parse(check)
                    for appid in self.appids:
                        current = get_steam_launch_options(check, appid)
                        if current is None or str(self.wrapper) not in current:
                            if steam_launch_action(current, self.wrapper) != "complex":
                                raise ValueError(
                                    tr("Weryfikacja LaunchOptions nie powiodła się dla {appid}.", appid=appid)
                                )
                except Exception:
                    _write_localconfig_atomic(account.localconfig, original)
                    raise
                self.result.emit(
                    {
                        "ok": True,
                        "account": account.account_name,
                        "updated": updated,
                        "skipped": skipped,
                        "unchanged": unchanged,
                        "backup": str(backup),
                        "path": str(account.localconfig),
                    }
                )
            else:
                self.result.emit(
                    {
                        "ok": True,
                        "account": account.account_name,
                        "updated": 0,
                        "skipped": skipped,
                        "unchanged": unchanged,
                        "path": str(account.localconfig),
                    }
                )
        except Exception as exc:
            log.error("Steam launch options failed: %s", traceback.format_exc())
            self.result.emit({"ok": False, "error": str(exc)})


def detect_steam_root(preferred: str = "") -> Path | None:
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(preferred).expanduser())
    home = Path.home()
    candidates.extend(
        [
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / ".steam" / "root",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
        ]
    )
    for candidate in candidates:
        try:
            if (candidate / "steamapps").is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return None


def steam_libraries(root: Path) -> list[Path]:
    libraries: list[Path] = [root.resolve()]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for match in re.finditer(r'"path"\s+"((?:[^"\\]|\\.)*)"', text):
            path = Path(_vdf_unescape(match.group(1))).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if (resolved / "steamapps").is_dir() and resolved not in libraries:
                libraries.append(resolved)
    return libraries


@dataclass
class SteamManifest:
    appid: str
    name: str
    installdir: str
    library: Path
    state_flags: int = 0


def read_steam_manifests(root: Path) -> list[SteamManifest]:
    manifests: list[SteamManifest] = []
    ignored = (
        "steam linux runtime",
        "steamworks common",
        "proton ",
        "steam controller",
        "steamvr",
    )
    for library in steam_libraries(root):
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            continue
        try:
            files = sorted(steamapps.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest_path in files:
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            appid = _acf_value(text, "appid")
            name = _acf_value(text, "name").strip()
            installdir = _acf_value(text, "installdir").strip()
            if not appid or not name or not installdir:
                continue
            if any(fragment in name.lower() for fragment in ignored):
                continue
            try:
                state_flags = int(_acf_value(text, "StateFlags") or 0)
            except ValueError:
                state_flags = 0
            manifests.append(
                SteamManifest(appid, name, installdir, library, state_flags)
            )
    return manifests


def steam_installed_appids(root: Path | None = None) -> set[str]:
    root = root or detect_steam_root()
    if root is None:
        return set()
    return {
        manifest.appid
        for manifest in read_steam_manifests(root)
        if manifest.state_flags == 0 or manifest.state_flags & 4
    }


def fetch_steam_owned_games(api_key: str, steam_id64: str) -> list[dict[str, Any]]:
    """Fetch every owned Steam game through IPlayerService/GetOwnedGames."""
    api_key = str(api_key or "").strip()
    steam_id64 = str(steam_id64 or "").strip()
    if not api_key:
        raise ValueError(tr("Podaj Steam Web API key w Ustawieniach → Steam."))
    if not steam_id64:
        raise ValueError(tr("Nie wykryto SteamID64. Uzupełnij go w Ustawieniach → Steam."))
    query = urllib.parse.urlencode(
        {
            "key": api_key,
            "steamid": steam_id64,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        }
    )
    url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?{query}"
    try:
        with http_open(url, timeout=35) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError(
                tr("Steam odrzucił klucz API lub SteamID64. Sprawdź ustawienia.")
            ) from exc
        raise OSError(
            tr("Steam API zwróciło błąd HTTP {code}.", code=exc.code)
        ) from exc
    except urllib.error.URLError as exc:
        raise OSError(tr("Błąd sieci: {reason}", reason=exc.reason)) from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(tr("Nieprawidłowa odpowiedź Steam API.")) from exc
    response_data = data.get("response") if isinstance(data, dict) else None
    if not isinstance(response_data, dict):
        raise ValueError(tr("Nieprawidłowa odpowiedź Steam API."))
    games = response_data.get("games")
    if not isinstance(games, list):
        if int(response_data.get("game_count", -1) or 0) == 0:
            return []
        raise ValueError(
            tr(
                "Steam nie zwrócił listy gier. Sprawdź, czy profil Steam "
                "pozwala na dostęp do biblioteki i czy klucz API jest poprawny."
            )
        )
    result: list[dict[str, Any]] = []
    for item in games:
        if not isinstance(item, dict):
            continue
        appid = str(item.get("appid", "") or "").strip()
        name = str(item.get("name", "") or "").strip()
        if not appid or not name:
            continue
        try:
            playtime = int(item.get("playtime_forever", 0) or 0)
        except (TypeError, ValueError):
            playtime = 0
        result.append(
            {
                "appid": appid,
                "name": name,
                "playtime_minutes": max(0, playtime),
            }
        )
    result.sort(key=lambda item: item["name"].lower())
    return result


class SteamOwnedGamesWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(
        self,
        api_key: str,
        steam_id64: str,
        steam_root: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.steam_id64 = steam_id64
        self.steam_root = steam_root

    def run(self) -> None:
        try:
            self.status.emit(tr("Pobieram bibliotekę Steam..."))
            games = fetch_steam_owned_games(self.api_key, self.steam_id64)
            root = detect_steam_root(self.steam_root)
            installed = steam_installed_appids(root)
            for game in games:
                game["installed"] = 1 if game["appid"] in installed else 0
            self.result.emit({"ok": True, "games": games})
        except Exception as exc:
            log.error("Steam library fetch failed: %s", traceback.format_exc())
            self.result.emit({"ok": False, "error": str(exc)})


class SteamCoverWorker(QThread):
    result = pyqtSignal(str, str)

    def __init__(self, appid: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.appid = str(appid)

    def run(self) -> None:
        root = detect_steam_root()
        if root is None:
            self.result.emit(self.appid, "")
            return
        try:
            path = ensure_steam_cover(self.appid, root)
        except Exception:
            path = ""
        self.result.emit(self.appid, path)


def steam_uri_command(uri: str) -> list[str]:
    client = steam_client_command()
    if not client:
        raise RuntimeError(tr("Nie znaleziono klienta Steam."))
    return [*client, uri]


def steam_install_uri(appid: str) -> str:
    return f"steam://install/{str(appid).strip()}"


def steam_run_uri(appid: str) -> str:
    return f"steam://run/{str(appid).strip()}"


def steam_store_uri(appid: str) -> str:
    return f"steam://store/{str(appid).strip()}"


_STEAM_SKIP_DIRS = {
    "_commonredist",
    "redist",
    "redistributables",
    "directx",
    "vcredist",
    "dotnet",
    "installers",
    "support",
    "tools",
    "__installer",
    "crashreport",
}


def find_steam_exe(library: Path, installdir: str, game_name: str) -> str:
    base = library / "steamapps" / "common" / installdir
    if not base.is_dir():
        return ""
    game_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", game_name.lower())
        if len(token) > 2 and token not in {"the", "and", "edition", "game"}
    }
    candidates: list[tuple[int, int, str]] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(base):
        depth = len(Path(dirpath).relative_to(base).parts)
        dirnames[:] = [
            name
            for name in dirnames
            if name.lower() not in _STEAM_SKIP_DIRS and not name.startswith(".")
        ]
        if depth >= 5:
            dirnames[:] = []
        for filename in filenames:
            if not filename.lower().endswith(".exe"):
                continue
            scanned += 1
            if scanned > 6000:
                break
            full = Path(dirpath) / filename
            stem = full.stem.lower()
            norm = re.sub(r"[^a-z0-9]+", "", stem)
            game_norm = re.sub(r"[^a-z0-9]+", "", game_name.lower())
            score = max(0, 24 - depth * 6)
            if game_norm and game_norm in norm:
                score += 60
            score += 22 * len(game_tokens.intersection(set(re.findall(r"[a-z0-9]+", stem))))
            if any(
                marker in stem
                for marker in (
                    "unins",
                    "setup",
                    "crash",
                    "report",
                    "dxsetup",
                    "vcredist",
                    "activation",
                )
            ):
                score -= 140
            try:
                size = full.stat().st_size
                if size > 10 * 1024 * 1024:
                    score += 15
                elif size > 512 * 1024:
                    score += 6
            except OSError:
                size = 0
            candidates.append((score, int(size), str(full)))
        if scanned > 6000:
            break
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def ensure_steam_cover(appid: str, steam_root: Path, force: bool = False) -> str:
    destination = db.COVERS_DIR / f"steam_{appid}.jpg"
    if destination.is_file() and destination.stat().st_size > 1024 and not force:
        return str(destination)
    cache_dirs = [steam_root / "appcache" / "librarycache"]
    cache_dirs.extend(
        library / "appcache" / "librarycache" for library in steam_libraries(steam_root)
    )
    local_names = (
        f"{appid}_library_600x900_2x.jpg",
        f"{appid}_library_600x900.jpg",
        f"{appid}_header.jpg",
        f"{appid}_library_hero.jpg",
    )
    for cache_dir in cache_dirs:
        for name in local_names:
            source = cache_dir / name
            if source.is_file() and source.stat().st_size > 1024:
                try:
                    shutil.copyfile(source, destination)
                    return str(destination)
                except OSError:
                    continue

    for url in (
        f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/header.jpg",
    ):
        try:
            download_file(url, destination, timeout=25)
            if destination.stat().st_size > 1024:
                return str(destination)
        except (OSError, urllib.error.URLError, ValueError):
            continue
    return ""


class RunnerDownloadWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    result = pyqtSignal(bool, str)

    def __init__(
        self,
        repo_key: str,
        release: dict[str, Any] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.repo_key = repo_key
        self.release = release

    def run(self) -> None:
        try:
            label, repo = GITHUB_REPOS[self.repo_key]
            if self.release is not None:
                release = self.release
                self.status.emit(
                    tr("Pobieram {label} {tag}...", label=label, tag=release.get("tag_name", ""))
                )
            else:
                self.status.emit(tr("Pobieram informacje o najnowszym {label}...", label=label))
                release = github_json(f"/repos/{repo}/releases/latest")
            tag = str(release.get("tag_name") or "latest")
            assets = release.get("assets") or []
            asset = choose_runner_asset(assets)
            if not asset:
                self.result.emit(
                    False,
                    tr("Wydanie {label} {tag} nie zawiera archiwum .tar.gz/.tar.xz.", label=label, tag=tag),
                )
                return
            asset_name = str(asset["name"])
            stem = re.sub(
                r"[^A-Za-z0-9._-]+",
                "-",
                re.sub(r"\.tar\.(gz|xz)$", "", Path(asset_name).name),
            ).strip("-")
            target = db.RUNNERS_DIR / stem
            if target.exists():
                self.result.emit(False, tr("Runner {name} jest już zainstalowany.", name=stem))
                return

            archive = db.DOWNLOADS_DIR / asset_name
            self.status.emit(tr("Pobieram {label} {tag} ({asset})...", label=label, tag=tag, asset=asset_name))
            last_percent = -1

            def report(current: int, expected: int) -> None:
                nonlocal last_percent
                if expected > 0:
                    percent = min(100, int(current * 100 / expected))
                    if percent != last_percent:
                        last_percent = percent
                        self.progress.emit(percent)
                else:
                    self.status.emit(tr("Pobrano {size}...", size=human_bytes(current)))

            download_file(str(asset["browser_download_url"]), archive, progress=report, timeout=120)
            self.progress.emit(100)
            self.status.emit(tr("Rozpakowuję archiwum..."))
            try:
                safe_extract_tar(archive, target)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
            finally:
                archive.unlink(missing_ok=True)

            for executable_dir in (target / "files" / "bin", target / "bin"):
                if executable_dir.is_dir():
                    for binary in executable_dir.iterdir():
                        if binary.is_file():
                            try:
                                binary.chmod(binary.stat().st_mode | 0o111)
                            except OSError:
                                pass
            for pattern in (
                "files/bin/wine",
                "bin/wine",
                "wine",
                "*/files/bin/wine",
                "*/bin/wine",
                "*/wine",
            ):
                for binary in target.glob(pattern):
                    if binary.is_file():
                        try:
                            binary.chmod(binary.stat().st_mode | 0o111)
                        except OSError:
                            pass
            for proton_script in (target / "proton", *target.glob("*/proton")):
                if proton_script.is_file():
                    try:
                        proton_script.chmod(proton_script.stat().st_mode | 0o111)
                    except OSError:
                        pass
            wine = find_wine_in_root(target)
            if not wine:
                shutil.rmtree(target, ignore_errors=True)
                self.result.emit(False, tr("Archiwum nie zawiera pliku files/bin/wine."))
                return
            self.result.emit(True, tr("Zainstalowano {name}.", name=stem))
        except urllib.error.HTTPError as exc:
            self.result.emit(False, tr("GitHub API: HTTP {code} ({reason}).", code=exc.code, reason=exc.reason))
        except urllib.error.URLError as exc:
            self.result.emit(False, tr("Błąd sieci: {reason}.", reason=exc.reason))
        except Exception as exc:
            log.error("Runner download failed: %s", traceback.format_exc())
            self.result.emit(False, tr("Nie udało się pobrać runnera: {error}", error=exc))


class SteamSyncWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        database: Database | None = None
        try:
            database = Database()
            preferred = database.get_setting("steam_path")
            root = detect_steam_root(preferred)
            if not root:
                self.result.emit({"ok": False, "error": tr("Nie znaleziono instalacji Steam.")})
                return
            if not preferred:
                database.set_setting("steam_path", str(root))
            manifests = read_steam_manifests(root)
            self.status.emit(tr("Znaleziono {count} wpisów Steam. Synchronizuję...", count=len(manifests)))
            added = updated = skipped = 0
            for index, manifest in enumerate(manifests, 1):
                self.status.emit(tr("[{index}/{total}] {name}", index=index, total=len(manifests), name=manifest.name))
                existing = database.find_steam_game(manifest.appid)
                exe = ""
                if existing:
                    current = Path(existing.get("exe_path", ""))
                    if current.exists():
                        exe = existing["exe_path"]
                if not exe:
                    exe = find_steam_exe(manifest.library, manifest.installdir, manifest.name)
                if not exe:
                    # Steam entries can be launched through Steam even when the
                    # executable cannot be identified.  Keep the install dir as
                    # metadata so the entry is still visible in the library.
                    install_dir = manifest.library / "steamapps" / "common" / manifest.installdir
                    if not install_dir.is_dir():
                        skipped += 1
                        continue
                    exe = str(install_dir)
                cover = ""
                if existing:
                    cover_path = Path(existing.get("cover_path", "") or "")
                    if cover_path.is_file():
                        cover = str(cover_path)
                if not cover:
                    cover = ensure_steam_cover(manifest.appid, root)
                # Steam/Proton owns the compatibility prefix for Steam games.
                # Do not create one Boostlayer prefix per imported game.
                prefix = existing.get("wine_prefix", "") if existing else ""
                runner = existing.get("runner_path", "") if existing else ""
                _game_id, created = database.upsert_steam_game(
                    name=manifest.name,
                    exe_path=exe,
                    runner_path=runner,
                    wine_prefix=prefix,
                    env_vars=existing.get("env_vars", "") if existing else "",
                    launch_args=existing.get("launch_args", "") if existing else "",
                    scaling_mode=existing.get("scaling_mode", "native") if existing else "native",
                    fps_limit=existing.get("fps_limit", 0) if existing else 0,
                    is_steam=1,
                    steam_appid=manifest.appid,
                    cover_path=cover,
                )
                if created:
                    added += 1
                else:
                    updated += 1
            self.result.emit(
                {
                    "ok": True,
                    "root": str(root),
                    "added": added,
                    "updated": updated,
                    "skipped": skipped,
                }
            )
        except Exception as exc:
            log.error("Steam sync failed: %s", traceback.format_exc())
            self.result.emit({"ok": False, "error": str(exc)})
        finally:
            if database is not None:
                database.close()
