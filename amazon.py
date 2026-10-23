"""Amazon Games (Prime Gaming) integration backed by the external ``nile`` CLI.

Boostlayer does not talk to Amazon APIs directly.  ``nile`` handles OAuth
device registration, the entitlement library, downloads and manifests; this
module only wraps it, parses its JSON output and exposes Qt workers for the UI.

The integration deliberately mirrors the nile CLI approach:

* ``nile`` is downloaded from GitHub Releases into the app config directory and
  can be overridden with an explicit path.
* ``NILE_CONFIG_PATH`` points at Boostlayer's own directory so a system-wide or
  The external launcher installation is never modified.
* Launching uses ``nile launch --json <id>`` to obtain the real executable,
  arguments, working directory and Amazon SDK environment.  The game itself is
  then started through Boostlayer's normal Wine/Proton pipeline, which keeps
  per-game prefixes, MangoHud, Gamescope and FPS limits working.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QThread, pyqtSignal

import db
from core import download_file, github_json
from i18n import tr

NILE_REPO = "imLinguin/nile"
NILE_ASSET_PREFIX = "nile_linux_"
NILE_VERSION_FILE = "nile.version"

ProgressCallback = Callable[[int, int], None]
LineCallback = Callable[[str], None]


class NileError(RuntimeError):
    """Raised when nile is missing, fails or returns unexpected output."""


# ---------------------------------------------------------------------------
# Paths and environment
# ---------------------------------------------------------------------------
def tools_dir() -> Path:
    return db.CONFIG_DIR / "tools"


def nile_config_base() -> Path:
    """Directory passed as NILE_CONFIG_PATH (nile appends its own ``nile``)."""
    return db.CONFIG_DIR / "amazon"


def nile_config_dir() -> Path:
    """Actual nile data directory containing library.json / installed.json."""
    return nile_config_base() / "nile"


def nile_env() -> dict[str, str]:
    env = os.environ.copy()
    base = nile_config_base()
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    env["NILE_CONFIG_PATH"] = str(base)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def nile_binary(database: db.Database | None = None) -> Path | None:
    """Return the configured nile binary, the downloaded one, or a PATH hit."""
    override = ""
    if database is not None:
        override = database.get_setting("amazon_nile_path", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate
    local = tools_dir() / "nile"
    if local.is_file():
        return local
    system = shutil.which("nile")
    return Path(system) if system else None


def require_nile(database: db.Database | None = None) -> Path:
    binary = nile_binary(database)
    if binary is None:
        raise NileError(
            tr(
                "Nie znaleziono nile. Pobierz go w Ustawieniach → Amazon Games "
                "albo wskaż własną ścieżkę do binarki."
            )
        )
    return binary


def nile_version(binary: str | Path) -> str:
    try:
        proc = run_nile(["--version"], binary, timeout=20)
    except NileError:
        return ""
    text = (proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0].strip() if text else ""


# ---------------------------------------------------------------------------
# Low level process helpers
# ---------------------------------------------------------------------------
def run_nile(
    args: Iterable[str],
    binary: str | Path,
    *,
    timeout: int = 180,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    binary_path = Path(binary).expanduser()
    if not binary_path.is_file():
        raise NileError(
            tr("Plik nile nie istnieje: {path}", path=str(binary_path))
        )
    env = nile_env()
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})
    try:
        return subprocess.run(
            [str(binary_path), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise NileError(
            tr("nile nie odpowiedział w wyznaczonym czasie ({seconds} s).", seconds=timeout)
        ) from exc
    except OSError as exc:
        raise NileError(
            tr("Nie można uruchomić nile: {error}", error=exc)
        ) from exc


def _json_from_output(text: str) -> Any:
    """Extract the first JSON value from nile output (logs may precede it)."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise NileError(tr("nile nie zwrócił żadnych danych."))
    try:
        return json.loads(cleaned)
    except (TypeError, ValueError):
        pass
    for line in reversed(cleaned.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            continue
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(cleaned[index:])
            return value
        except (TypeError, ValueError):
            continue
    raise NileError(
        tr("Nie można odczytać odpowiedzi nile:\n{output}", output=cleaned[-1200:])
    )


def _proc_error(proc: subprocess.CompletedProcess[str], default: str) -> str:
    text = "\n".join(
        part for part in (proc.stderr or "", proc.stdout or "") if part.strip()
    )
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    tail = "\n".join(lines[-10:])
    return f"{default}\n\n{tail}" if tail else default


# ---------------------------------------------------------------------------
# Tool download
# ---------------------------------------------------------------------------
def select_nile_asset(assets: Iterable[dict[str, Any]], machine: str) -> dict[str, Any] | None:
    """Pick the Linux asset matching the current CPU architecture."""
    normalized = (machine or "").strip().lower()
    arch = "arm64" if normalized in {"aarch64", "arm64", "armv8"} else "x86_64"
    expected = f"{NILE_ASSET_PREFIX}{arch}"
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("name", "")).strip() == expected:
            return asset
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_nile(
    progress: ProgressCallback | None = None,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    """Download/update the latest nile release into the app config directory."""
    release = github_json(f"/repos/{NILE_REPO}/releases/latest")
    tag = str(release.get("tag_name", "") or "").strip()
    asset = select_nile_asset(release.get("assets") or [], platform.machine())
    if asset is None:
        raise NileError(
            tr(
                "Wydanie nile {tag} nie zawiera binarki dla tej architektury.",
                tag=tag or "?",
            )
        )
    url = str(asset.get("browser_download_url", "") or "").strip()
    if not url:
        raise NileError(tr("Wydanie nile nie zawiera adresu pobierania."))
    destination = tools_dir() / "nile"
    tools_dir().mkdir(parents=True, exist_ok=True)
    download_file(url, destination, progress=progress, timeout=300)
    expected_digest = str(asset.get("digest", "") or "").strip()
    if expected_digest.startswith("sha256:"):
        expected = expected_digest.split(":", 1)[1].strip().lower()
        actual = _sha256(destination).lower()
        if expected and actual != expected:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise NileError(
                tr(
                    "Suma kontrolna nile jest nieprawidłowa. Pobieranie przerwane."
                )
            )
    try:
        destination.chmod(0o755)
    except OSError as exc:
        raise NileError(
            tr("Nie można nadać uprawnień wykonywania plikowi nile: {error}", error=exc)
        ) from exc
    try:
        (tools_dir() / NILE_VERSION_FILE).write_text(tag or "?", encoding="utf-8")
    except OSError:
        pass
    return {"version": tag, "path": str(destination)}


def installed_nile_version() -> str:
    try:
        return (tools_dir() / NILE_VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def auth_status(binary: str | Path) -> dict[str, Any]:
    proc = run_nile(["auth", "--status"], binary, timeout=30)
    if proc.returncode != 0:
        raise NileError(
            _proc_error(proc, tr("Nie można odczytać statusu logowania Amazon."))
        )
    data = _json_from_output(proc.stdout)
    if not isinstance(data, dict):
        raise NileError(tr("Nieprawidłowa odpowiedź nile (status logowania)."))
    username = str(data.get("Username", "") or "").strip()
    logged_in = bool(data.get("LoggedIn")) and username not in {"", "<not logged in>"}
    return {"username": username, "logged_in": logged_in}


def current_user() -> dict[str, str]:
    path = nile_config_dir() / "current_user.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "name": str(data.get("name", "") or ""),
        "user_id": str(data.get("user_id", "") or ""),
    }


def begin_login(binary: str | Path) -> dict[str, str]:
    """Start the Amazon device login and return data needed for ``register``."""
    proc = run_nile(
        ["auth", "--login", "--non-interactive"], binary, timeout=90
    )
    if proc.returncode != 0:
        raise NileError(_proc_error(proc, tr("Nie można rozpocząć logowania Amazon.")))
    data = _json_from_output(proc.stdout)
    if not isinstance(data, dict):
        raise NileError(tr("Nieprawidłowa odpowiedź nile (logowanie)."))
    payload = {
        "url": str(data.get("url", "") or "").strip(),
        "client_id": str(data.get("client_id", "") or "").strip(),
        "code_verifier": str(data.get("code_verifier", "") or "").strip(),
        "serial": str(data.get("serial", "") or "").strip(),
    }
    missing = [key for key, value in payload.items() if not value]
    if missing:
        raise NileError(
            tr(
                "Odpowiedź logowania nile nie zawiera wymaganych pól: {fields}",
                fields=", ".join(missing),
            )
        )
    return payload


def parse_login_redirect(text: str) -> str:
    """Extract the Amazon authorization code from a pasted URL (or raw code)."""
    value = (text or "").strip()
    if not value:
        return ""
    match = re.search(r"openid\.oa2\.authorization_code=([^&\s#]+)", value)
    if match:
        return urllib.parse.unquote(match.group(1)).strip()
    if value.lower().startswith(("http://", "https://")):
        query = urllib.parse.urlparse(value).query
        params = urllib.parse.parse_qs(query)
        for key in ("openid.oa2.authorization_code", "authorization_code", "code"):
            values = params.get(key)
            if values:
                return str(values[0]).strip()
        return ""
    return value


def finish_login(
    binary: str | Path, payload: dict[str, str], pasted: str
) -> dict[str, str]:
    code = parse_login_redirect(pasted)
    if not code:
        raise NileError(
            tr(
                "Nie znaleziono kodu autoryzacji w adresie. Wklej pełny URL, "
                "na który przekierowała Cię strona Amazona."
            )
        )
    proc = run_nile(
        [
            "register",
            "--code",
            code,
            "--code-verifier",
            payload.get("code_verifier", ""),
            "--serial",
            payload.get("serial", ""),
            "--client-id",
            payload.get("client_id", ""),
        ],
        binary,
        timeout=300,
    )
    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    registered = bool(
        re.search(r"Succesfully registered a device", combined, re.IGNORECASE)
        or re.search(r"Successfully registered a device", combined, re.IGNORECASE)
    )
    user = current_user()
    if not registered and not user:
        raise NileError(
            _proc_error(proc, tr("Rejestracja urządzenia w Amazon nie powiodła się."))
        )
    if not user:
        status = auth_status(binary)
        user = {"name": status.get("username", ""), "user_id": ""}
    return user


def logout(binary: str | Path) -> None:
    try:
        run_nile(["auth", "--logout"], binary, timeout=60)
    except NileError:
        pass
    for name in ("current_user.json",):
        try:
            (nile_config_dir() / name).unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------
def read_installed() -> list[dict[str, Any]]:
    path = nile_config_dir() / "installed.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def installed_map() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in read_installed():
        product_id = str(item.get("id", "") or "").strip()
        if product_id:
            result[product_id] = item
    return result


def normalize_library(
    entries: Iterable[dict[str, Any]],
    installed: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Turn ``nile library list --json`` entries into Boostlayer records."""
    installed = installed or {}
    games: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        product = entry.get("product")
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("id", "") or "").strip()
        title = str(product.get("title", "") or "").strip()
        if not product_id or not title:
            continue
        detail = product.get("productDetail")
        if not isinstance(detail, dict):
            detail = {}
        details = detail.get("details")
        if not isinstance(details, dict):
            details = {}
        icon_url = str(detail.get("iconUrl") or details.get("iconUrl") or "").strip()
        cover_url = str(
            details.get("backgroundUrl2")
            or icon_url
            or details.get("backgroundUrl1")
            or ""
        ).strip()
        meta = installed.get(product_id) or {}
        try:
            size = int(meta.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        games.append(
            {
                "product_id": product_id,
                "entitlement_id": str(entry.get("id", "") or "").strip(),
                "title": title,
                "description": str(details.get("shortDescription", "") or "").strip(),
                "developer": str(details.get("developer", "") or "").strip(),
                "icon_url": icon_url,
                "cover_url": cover_url,
                "installed": 1 if product_id in installed else 0,
                "install_path": str(meta.get("path", "") or "").strip(),
                "version": str(meta.get("version", "") or "").strip(),
                "size": max(0, size),
            }
        )
    games.sort(key=lambda item: item["title"].lower())
    return games


def sync_library(
    binary: str | Path,
    *,
    force: bool = False,
    status: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    if status:
        status(tr("Synchronizuję bibliotekę Amazon..."))
    args = ["library", "sync"]
    if force:
        args.append("--force")
    proc = run_nile(args, binary, timeout=300)
    if proc.returncode != 0:
        raise NileError(
            _proc_error(proc, tr("Synchronizacja biblioteki Amazon nie powiodła się."))
        )
    if status:
        status(tr("Odczytuję bibliotekę Amazon..."))
    proc = run_nile(["library", "list", "--json"], binary, timeout=90)
    if proc.returncode != 0:
        raise NileError(
            _proc_error(proc, tr("Nie można odczytać biblioteki Amazon."))
        )
    entries = _json_from_output(proc.stdout)
    if not isinstance(entries, list):
        raise NileError(tr("Nieprawidłowa odpowiedź nile (biblioteka)."))
    return normalize_library(entries, installed_map())


# ---------------------------------------------------------------------------
# Downloads / maintenance
# ---------------------------------------------------------------------------
def _max_workers_args(max_workers: int) -> list[str]:
    if max_workers and max_workers > 0:
        return ["--max-workers", str(int(max_workers))]
    return []


def _run_streaming(
    args: list[str],
    binary: str | Path,
    *,
    on_line: LineCallback | None = None,
    cancel_event: Any | None = None,
    timeout: int = 0,
) -> dict[str, Any]:
    binary_path = Path(binary).expanduser()
    if not binary_path.is_file():
        raise NileError(tr("Plik nile nie istnieje: {path}", path=str(binary_path)))
    env = nile_env()
    try:
        process = subprocess.Popen(
            [str(binary_path), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        raise NileError(tr("Nie można uruchomić nile: {error}", error=exc)) from exc
    output: list[str] = []
    cancelled = False
    started = time.monotonic()
    assert process.stdout is not None
    try:
        for raw_line in iter(process.stdout.readline, ""):
            line = raw_line.rstrip("\r\n")
            if line:
                output.append(line)
                if len(output) > 4000:
                    del output[:1000]
                if on_line:
                    on_line(line)
            if cancel_event is not None and cancel_event.is_set() and not cancelled:
                cancelled = True
                _terminate_process(process)
            if timeout and time.monotonic() - started > timeout:
                _terminate_process(process)
                raise NileError(
                    tr("Operacja nile przekroczyła limit czasu ({seconds} s).", seconds=timeout)
                )
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        raise NileError(tr("Operacja nile nie zakończyła się w wyznaczonym czasie."))
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
    tail = "\n".join(output[-12:])
    if cancelled:
        return {"ok": False, "cancelled": True, "error": tr("Anulowano."), "output": tail}
    if process.returncode != 0:
        return {
            "ok": False,
            "cancelled": False,
            "error": tail or tr("nile zakończył się kodem {code}.", code=process.returncode),
            "output": tail,
        }
    return {"ok": True, "cancelled": False, "error": "", "output": tail}


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=8)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def install_size(binary: str | Path, product_id: str) -> int:
    proc = run_nile(
        ["install", "--info", "--json", str(product_id)], binary, timeout=120
    )
    if proc.returncode != 0:
        raise NileError(
            _proc_error(proc, tr("Nie można odczytać rozmiaru gry Amazon."))
        )
    data = _json_from_output(proc.stdout)
    if not isinstance(data, dict):
        return 0
    try:
        return max(0, int(data.get("download_size", 0) or 0))
    except (TypeError, ValueError):
        return 0


def install_game(
    binary: str | Path,
    product_id: str,
    base_path: str | Path = "",
    *,
    exact_path: str | Path = "",
    max_workers: int = 0,
    on_line: LineCallback | None = None,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    args = ["install"]
    if exact_path:
        target = Path(exact_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        args += ["--path", str(target)]
    else:
        base = Path(base_path).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        args += ["--base-path", str(base)]
    args += [*_max_workers_args(max_workers), str(product_id)]
    return _run_streaming(
        args, binary, on_line=on_line, cancel_event=cancel_event
    )


def update_game(
    binary: str | Path,
    product_id: str,
    *,
    max_workers: int = 0,
    on_line: LineCallback | None = None,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    args = ["update", *_max_workers_args(max_workers), str(product_id)]
    return _run_streaming(
        args, binary, on_line=on_line, cancel_event=cancel_event
    )


def verify_game(
    binary: str | Path,
    product_id: str,
    install_path: str | Path,
    *,
    on_line: LineCallback | None = None,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    args = ["verify", "--path", str(Path(install_path).expanduser()), str(product_id)]
    return _run_streaming(
        args, binary, on_line=on_line, cancel_event=cancel_event
    )


def uninstall_game(
    binary: str | Path,
    product_id: str,
    *,
    on_line: LineCallback | None = None,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    args = ["uninstall", str(product_id)]
    return _run_streaming(
        args, binary, on_line=on_line, cancel_event=cancel_event
    )


def check_updates(binary: str | Path) -> list[str]:
    proc = run_nile(["list-updates", "--json"], binary, timeout=120)
    if proc.returncode != 0:
        return []
    try:
        data = _json_from_output(proc.stdout)
    except NileError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


# ---------------------------------------------------------------------------
# Launch specification
# ---------------------------------------------------------------------------
def _json5_lite(text: str) -> Any:
    """Best-effort JSON5 reader for Amazon's fuel.json (comments/trailing commas)."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"(^|[^:])//.*$", r"\1", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except (TypeError, ValueError):
        return None


def fuel_working_dir(install_path: str | Path) -> str:
    """Read ``WorkingSubdirOverride`` from fuel.json when present."""
    root = Path(install_path).expanduser()
    if not root.is_dir():
        return ""
    fuel = root / "fuel.json"
    try:
        data = _json5_lite(fuel.read_text(encoding="utf-8"))
    except OSError:
        return ""
    if not isinstance(data, dict):
        return ""
    main = data.get("Main")
    if not isinstance(main, dict):
        return ""
    override = str(main.get("WorkingSubdirOverride", "") or "").strip()
    if not override:
        return ""
    candidate = root / override.replace("\\", os.sep).replace("/", os.sep)
    return str(candidate) if candidate.is_dir() else ""


def parse_launch_spec(
    payload: Any, install_path: str | Path = ""
) -> dict[str, Any]:
    """Parse the JSON printed by ``nile launch --json``."""
    if not isinstance(payload, dict):
        raise NileError(tr("Nieprawidłowa odpowiedź nile (uruchamianie)."))
    command = payload.get("command")
    if not isinstance(command, dict):
        raise NileError(tr("Odpowiedź nile nie zawiera komendy gry."))
    instruction = str(command.get("instruction", "") or "").strip()
    if not instruction:
        raise NileError(tr("Odpowiedź nile nie zawiera ścieżki EXE gry."))
    raw_arguments = command.get("arguments") or []
    if not isinstance(raw_arguments, list):
        raw_arguments = []
    arguments = [str(item) for item in raw_arguments]
    env_raw = payload.get("env") or {}
    env: dict[str, str] = {}
    if isinstance(env_raw, dict):
        for key, value in env_raw.items():
            if key is None or value is None:
                continue
            env[str(key)] = str(value)
    cwd = str(payload.get("game_directory", "") or "").strip()
    override = fuel_working_dir(install_path) if install_path else ""
    if override:
        cwd = override
    if not cwd:
        cwd = str(Path(instruction).parent)
    return {
        "command": instruction,
        "arguments": arguments,
        "cwd": cwd,
        "env": env,
    }


def launch_spec(
    binary: str | Path,
    product_id: str,
    *,
    install_path: str | Path = "",
) -> dict[str, Any]:
    proc = run_nile(
        ["launch", "--json", str(product_id)], binary, timeout=180
    )
    if proc.returncode != 0:
        raise NileError(
            _proc_error(proc, tr("Nie można przygotować uruchomienia gry Amazon."))
        )
    payload = _json_from_output(proc.stdout)
    return parse_launch_spec(payload, install_path)


_PROGRESS_PATTERNS = {
    "percent": re.compile(r"Progress:\s*([0-9]+(?:[.,][0-9]+)?)\s*%?"),
    "eta": re.compile(r"ETA:\s*(\d{2}:\d{2}:\d{2})"),
    "downloaded": re.compile(r"Downloaded:\s*([0-9]+(?:[.,][0-9]+)?)\s*([KMG]i?B)"),
    "download_speed": re.compile(r"Download\s*-\s*([0-9]+(?:[.,][0-9]+)?)\s*([KMG]i?B)"),
    "disk_speed": re.compile(r"Disk\s*-\s*([0-9]+(?:[.,][0-9]+)?)\s*([KMG]i?B)"),
}


def parse_progress(line: str) -> dict[str, Any]:
    """Extract nile download progress fields from one log line."""
    result: dict[str, Any] = {}
    text = line or ""
    match = _PROGRESS_PATTERNS["percent"].search(text)
    if match:
        try:
            result["percent"] = max(0.0, min(100.0, float(match.group(1).replace(",", "."))))
        except ValueError:
            pass
    match = _PROGRESS_PATTERNS["eta"].search(text)
    if match:
        result["eta"] = match.group(1)
    for key in ("downloaded", "download_speed", "disk_speed"):
        match = _PROGRESS_PATTERNS[key].search(text)
        if match:
            try:
                amount = float(match.group(1).replace(",", "."))
            except ValueError:
                continue
            result[key] = f"{amount:g} {match.group(2)}"
    return result


# ---------------------------------------------------------------------------
# Covers
# ---------------------------------------------------------------------------
def fetch_cover(url: str, product_id: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    db.ensure_app_dirs()
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    destination = db.COVERS_DIR / f"amazon-{db.slugify(product_id)}{suffix}"
    if destination.is_file() and destination.stat().st_size > 0:
        return str(destination)
    try:
        download_file(url, destination, timeout=60)
    except Exception:
        return ""
    return str(destination)


# ---------------------------------------------------------------------------
# Qt workers
# ---------------------------------------------------------------------------
class NileSetupWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.status.emit(tr("Pobieram nile..."))
            outcome = download_nile(
                progress=lambda done, total: self.status.emit(
                    tr("Pobieram nile... {done}/{total}", done=_mb(done), total=_mb(total))
                    if total
                    else tr("Pobieram nile... {done}", done=_mb(done))
                )
            )
            self.result.emit({"ok": True, **outcome})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class NileBeginLoginWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, binary: str, parent=None) -> None:
        super().__init__(parent)
        self.binary = binary

    def run(self) -> None:
        try:
            self.result.emit({"ok": True, "data": begin_login(self.binary)})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class NileFinishLoginWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, binary: str, payload: dict[str, str], pasted: str, parent=None) -> None:
        super().__init__(parent)
        self.binary = binary
        self.payload = payload
        self.pasted = pasted

    def run(self) -> None:
        try:
            user = finish_login(self.binary, self.payload, self.pasted)
            self.result.emit({"ok": True, "user": user})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class NileLogoutWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, binary: str, parent=None) -> None:
        super().__init__(parent)
        self.binary = binary

    def run(self) -> None:
        try:
            logout(self.binary)
            self.result.emit({"ok": True})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class NileSyncWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(self, binary: str, force: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.binary = binary
        self.force = force

    def run(self) -> None:
        try:
            status = auth_status(self.binary)
            if not status["logged_in"]:
                self.result.emit(
                    {"ok": False, "error": tr("Nie jesteś zalogowany do Amazon Games.")}
                )
                return
            games = sync_library(
                self.binary, force=self.force, status=self.status.emit
            )
            for game in games:
                if not game.get("installed") or not game.get("install_path"):
                    continue
                try:
                    game["spec"] = launch_spec(
                        self.binary,
                        str(game["product_id"]),
                        install_path=str(game["install_path"]),
                    )
                except Exception:
                    game["spec"] = {}
            updates = check_updates(self.binary)
            self.result.emit(
                {
                    "ok": True,
                    "games": games,
                    "username": status["username"],
                    "installed": installed_map(),
                    "updates": updates,
                }
            )
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class NileJobWorker(QThread):
    """Run install/update/verify/uninstall with streaming output."""

    output = pyqtSignal(str)
    progress = pyqtSignal(object)
    result = pyqtSignal(object)

    def __init__(
        self,
        binary: str,
        action: str,
        product_id: str,
        *,
        base_path: str = "",
        install_path: str = "",
        max_workers: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.binary = binary
        self.action = action
        self.product_id = product_id
        self.base_path = base_path
        self.install_path = install_path
        self.max_workers = max_workers
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _on_line(self, line: str) -> None:
        self.output.emit(line)
        parsed = parse_progress(line)
        if parsed:
            self.progress.emit(parsed)

    def run(self) -> None:
        try:
            if self.action == "install":
                outcome = install_game(
                    self.binary,
                    self.product_id,
                    self.base_path,
                    max_workers=self.max_workers,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            elif self.action == "update":
                outcome = update_game(
                    self.binary,
                    self.product_id,
                    max_workers=self.max_workers,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            elif self.action == "verify":
                outcome = verify_game(
                    self.binary,
                    self.product_id,
                    self.install_path,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            elif self.action == "uninstall":
                outcome = uninstall_game(
                    self.binary,
                    self.product_id,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            else:
                raise NileError(tr("Nieznana operacja Amazon: {action}", action=self.action))
            metadata = installed_map().get(self.product_id, {})
            self.result.emit(
                {
                    **outcome,
                    "action": self.action,
                    "product_id": self.product_id,
                    "metadata": metadata,
                }
            )
        except Exception as exc:
            self.result.emit(
                {
                    "ok": False,
                    "cancelled": False,
                    "error": str(exc),
                    "action": self.action,
                    "product_id": self.product_id,
                }
            )


class NileSpecWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, binary: str, product_id: str, install_path: str = "", parent=None) -> None:
        super().__init__(parent)
        self.binary = binary
        self.product_id = product_id
        self.install_path = install_path

    def run(self) -> None:
        try:
            spec = launch_spec(
                self.binary, self.product_id, install_path=self.install_path
            )
            self.result.emit({"ok": True, "spec": spec})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class NileCoverWorker(QThread):
    result = pyqtSignal(str, str)

    def __init__(self, product_id: str, url: str, parent=None) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.url = url

    def run(self) -> None:
        try:
            path = fetch_cover(self.url, self.product_id)
        except Exception:
            path = ""
        self.result.emit(self.product_id, path)


def _mb(value: int) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "?"
