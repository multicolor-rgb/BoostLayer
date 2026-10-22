"""Shared storefront integration layer for Boostlayer.

Adapters wrap the external CLIs used by Heroic (nile, gogdl, legendary) and
normalise their libraries, installs and launch information for the UI.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QThread, pyqtSignal

import amazon
import db
from core import download_file, github_json
from i18n import tr

LineCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]

GOG_AUTH_URL = (
    "https://auth.gog.com/auth?client_id=46899977096215655"
    "&redirect_uri=https%3A%2F%2Fembed.gog.com%2Fon_login_success%3Forigin%3Dclient"
    "&response_type=code&layout=client2"
)
EPIC_LOGIN_URL = "https://legendary.gl/epiclogin"
USER_AGENT = "Boostlayer/0.1 (+https://github.com/boostlayer)"
log = logging.getLogger("boostlayer.stores")


class StoreError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def tools_dir() -> Path:
    return db.CONFIG_DIR / "tools"


def _arch_names(machine: str | None = None) -> tuple[str, str]:
    normalized = (machine or os.uname().machine or "").lower()
    if normalized in {"aarch64", "arm64", "armv8"}:
        return "arm64", "aarch64"
    return "x86_64", "x86_64"


def generic_tool_binary(
    database: db.Database | None,
    setting_key: str,
    tool_name: str,
) -> Path | None:
    override = ""
    if database is not None:
        override = database.get_setting(setting_key, "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate
    local = tools_dir() / tool_name
    if local.is_file():
        return local
    system = shutil.which(tool_name)
    return Path(system) if system else None


def download_store_tool(
    *,
    repo: str,
    asset_names: dict[str, str],
    destination_name: str,
    version_name: str,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    release = github_json(f"/repos/{repo}/releases/latest")
    tag = str(release.get("tag_name", "") or "").strip()
    arch, _ = _arch_names()
    wanted = asset_names.get(arch) or asset_names.get("x86_64", "")
    asset = None
    for item in release.get("assets") or []:
        if isinstance(item, dict) and str(item.get("name", "")).strip() == wanted:
            asset = item
            break
    if asset is None:
        raise StoreError(
            tr(
                "Wydanie {repo} {tag} nie zawiera binarki dla tej architektury.",
                repo=repo,
                tag=tag or "?",
            )
        )
    url = str(asset.get("browser_download_url", "") or "").strip()
    if not url:
        raise StoreError(tr("Wydanie nie zawiera adresu pobierania."))
    tools_dir().mkdir(parents=True, exist_ok=True)
    destination = tools_dir() / destination_name
    download_file(url, destination, progress=progress, timeout=300)
    digest = str(asset.get("digest", "") or "").strip()
    if digest.startswith("sha256:"):
        import hashlib

        hasher = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest().lower() != digest.split(":", 1)[1].strip().lower():
            destination.unlink(missing_ok=True)
            raise StoreError(tr("Suma kontrolna narzędzia jest nieprawidłowa."))
    destination.chmod(0o755)
    try:
        (tools_dir() / version_name).write_text(tag or "?", encoding="utf-8")
    except OSError:
        pass
    return {"version": tag, "path": str(destination)}


def tool_version(version_name: str) -> str:
    try:
        return (tools_dir() / version_name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def run_tool(
    binary: str | Path,
    args: Iterable[str],
    *,
    env_extra: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    binary_path = Path(binary).expanduser()
    if not binary_path.is_file():
        raise StoreError(tr("Plik narzędzia nie istnieje: {path}", path=binary_path))
    env = os.environ.copy()
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
        raise StoreError(
            tr("Narzędzie nie odpowiedziało w czasie {seconds} s.", seconds=timeout)
        ) from exc
    except OSError as exc:
        raise StoreError(tr("Nie można uruchomić narzędzia: {error}", error=exc)) from exc


def json_from_output(text: str) -> Any:
    cleaned = (text or "").strip()
    if not cleaned:
        raise StoreError(tr("Narzędzie nie zwróciło danych."))
    try:
        return json.loads(cleaned)
    except (TypeError, ValueError):
        pass
    for line in reversed(cleaned.splitlines()):
        try:
            return json.loads(line.strip())
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
    raise StoreError(
        tr("Nie można odczytać odpowiedzi narzędzia:\n{output}", output=cleaned[-1200:])
    )


def proc_error(proc: subprocess.CompletedProcess[str], default: str) -> str:
    text = "\n".join(
        part for part in (proc.stderr or "", proc.stdout or "") if part.strip()
    )
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    tail = "\n".join(lines[-10:])
    return f"{default}\n\n{tail}" if tail else default


def run_streaming(
    binary: str | Path,
    args: Iterable[str],
    *,
    env_extra: dict[str, str] | None = None,
    on_line: LineCallback | None = None,
    cancel_event: Any | None = None,
    timeout: int = 0,
) -> dict[str, Any]:
    binary_path = Path(binary).expanduser()
    if not binary_path.is_file():
        raise StoreError(tr("Plik narzędzia nie istnieje: {path}", path=binary_path))
    env = os.environ.copy()
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})
    try:
        process = subprocess.Popen(
            [str(binary_path), *[str(arg) for arg in args]],
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
        raise StoreError(tr("Nie można uruchomić narzędzia: {error}", error=exc)) from exc
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
                raise StoreError(
                    tr("Operacja przekroczyła limit czasu ({seconds} s).", seconds=timeout)
                )
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        raise StoreError(tr("Operacja nie zakończyła się w wyznaczonym czasie."))
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
            "error": tail or tr("Narzędzie zakończyło się kodem {code}.", code=process.returncode),
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


def safe_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "", value or "").strip()
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "Game"


def case_insensitive_path(base: Path, relative: str) -> Path:
    """Resolve a Windows-style relative path on a case-sensitive filesystem."""
    current = base
    for part in (relative or "").replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            matches = [
                item for item in current.iterdir()
                if item.name.lower() == part.lower()
            ]
        except OSError:
            matches = []
        current = matches[0] if matches else candidate
    return current


def safe_remove_game_dir(path: str | Path) -> None:
    target = Path(path).expanduser()
    if not target.exists():
        return
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    forbidden = {
        Path("/"),
        Path.home().resolve(),
        db.CONFIG_DIR.resolve(),
    }
    if resolved in forbidden or len(resolved.parts) < 3:
        raise StoreError(tr("Odmowa usunięcia niebezpiecznej ścieżki: {path}", path=resolved))
    if resolved.is_symlink():
        raise StoreError(tr("Katalog gry jest dowiązaniem symbolicznym: {path}", path=resolved))
    shutil.rmtree(resolved)


def download_cover(url: str, store: str, game_id: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    db.ensure_app_dirs()
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    destination = db.COVERS_DIR / f"{store}-{db.slugify(game_id)}{suffix}"
    if destination.is_file() and destination.stat().st_size > 0:
        return str(destination)
    try:
        download_file(url, destination, timeout=60)
    except Exception:
        return ""
    return str(destination)


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 45) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise StoreError(tr("Serwer zwrócił błąd HTTP {code}.", code=exc.code)) from exc
    except urllib.error.URLError as exc:
        raise StoreError(tr("Błąd sieci: {reason}", reason=exc.reason)) from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise StoreError(tr("Nieprawidłowa odpowiedź serwera.")) from exc


def _parse_progress(line: str) -> dict[str, Any]:
    return amazon.parse_progress(line)


def _generic_progress(line: str) -> dict[str, Any]:
    data = _parse_progress(line)
    if data:
        return data
    result: dict[str, Any] = {}
    match = re.search(r"ETA:\s*(\d\d:\d\d:\d\d)", line)
    if match:
        result["eta"] = match.group(1)
    match = re.search(r"Downloaded:\s*([0-9.]+)\s*MiB", line)
    if match:
        result["downloaded"] = f"{match.group(1)} MiB"
    match = re.search(r"Download\s*-\s*([0-9.]+)\s*MiB", line)
    if match:
        result["download_speed"] = f"{match.group(1)} MiB"
    match = re.search(r"Disk\s*-\s*([0-9.]+)\s*MiB", line)
    if match:
        result["disk_speed"] = f"{match.group(1)} MiB"
    return result


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------
class StoreAdapter:
    id = ""
    label = ""
    install_setting = ""
    tool_setting = ""
    tool_name = ""
    version_name = ""
    login_url = ""
    login_help = ""

    def tool_binary(self, database: db.Database | None) -> Path | None:
        return generic_tool_binary(database, self.tool_setting, self.tool_name)

    def download_tool(self, progress: ProgressCallback | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def auth_status(self, binary: str | Path) -> dict[str, Any]:
        raise NotImplementedError

    def begin_login(self, binary: str | Path) -> dict[str, Any]:
        return {"url": self.login_url, "help": self.login_help}

    def finish_login(
        self, binary: str | Path, payload: dict[str, Any], pasted: str
    ) -> dict[str, str]:
        raise NotImplementedError

    def logout(self, binary: str | Path) -> None:
        raise NotImplementedError

    def current_user(self) -> dict[str, str]:
        return {}

    def sync(
        self,
        binary: str | Path,
        installed: dict[str, dict[str, Any]] | None = None,
        status: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def install(
        self,
        binary: str | Path,
        game_id: str,
        target_path: str | Path,
        *,
        max_workers: int = 0,
        on_line: LineCallback | None = None,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def update(self, binary, game_id, install_path, **kwargs) -> dict[str, Any]:
        raise NotImplementedError

    def verify(self, binary, game_id, install_path, **kwargs) -> dict[str, Any]:
        raise NotImplementedError

    def uninstall(self, binary, game_id, install_path, **kwargs) -> dict[str, Any]:
        raise NotImplementedError

    def launch_spec(
        self, binary: str | Path, game_id: str, install_path: str | Path = ""
    ) -> dict[str, Any]:
        raise NotImplementedError

    def fetch_cover(self, game: dict[str, Any]) -> str:
        return download_cover(
            str(game.get("cover_url", "") or ""), self.id, str(game.get("store_id", ""))
        )

    def fetch_size(
        self, binary: str | Path, game_id: str, install_path: str = ""
    ) -> int:
        return 0

    def installed_metadata(
        self, game_id: str, install_path: str = "", binary: str | Path | None = None
    ) -> dict[str, Any]:
        return {}

    def default_install_dir(self, database: db.Database) -> Path:
        raw = database.get_setting(self.install_setting, "").strip()
        if raw:
            return Path(raw).expanduser()
        return Path.home() / "Games" / self.id


# ---------------------------------------------------------------------------
# Amazon adapter
# ---------------------------------------------------------------------------
class AmazonStore(StoreAdapter):
    id = "amazon"
    label = "AMAZON"
    install_setting = "amazon_install_dir"
    tool_setting = "amazon_nile_path"
    tool_name = "nile"
    version_name = amazon.NILE_VERSION_FILE
    login_help = tr(
        "1. Otwórz stronę logowania i zaloguj się na konto Amazon.\n"
        "2. Po przekierowaniu skopiuj pełny adres URL z paska przeglądarki "
        "(zawiera parametr openid.oa2.authorization_code).\n"
        "3. Wklej go poniżej i zatwierdź. Amazon nie przekierowuje na "
        "localhost, dlatego ten krok jest ręczny."
    )

    def tool_binary(self, database):
        return amazon.nile_binary(database)

    def download_tool(self, progress=None):
        return amazon.download_nile(progress=progress)

    def auth_status(self, binary):
        return amazon.auth_status(binary)

    def begin_login(self, binary):
        return amazon.begin_login(binary)

    def finish_login(self, binary, payload, pasted):
        return amazon.finish_login(binary, payload, pasted)

    def logout(self, binary):
        amazon.logout(binary)

    def current_user(self):
        return amazon.current_user()

    def sync(self, binary, installed=None, status=None):
        games = amazon.sync_library(binary, force=True, status=status)
        result = []
        for game in games:
            item = dict(game)
            item["store"] = self.id
            item["store_id"] = str(item.pop("product_id", ""))
            item["extra_json"] = json.dumps(
                {"entitlement_id": item.get("entitlement_id", "")}
            )
            if item.get("installed") and item.get("install_path"):
                try:
                    item["spec_json"] = json.dumps(
                        amazon.launch_spec(
                            binary,
                            item["store_id"],
                            install_path=item["install_path"],
                        )
                    )
                except Exception:
                    pass
            result.append(item)
        return result

    def install(self, binary, game_id, target_path, *, max_workers=0, on_line=None, cancel_event=None):
        return amazon.install_game(
            binary,
            game_id,
            exact_path=target_path,
            max_workers=max_workers,
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def update(self, binary, game_id, install_path, *, max_workers=0, on_line=None, cancel_event=None):
        return amazon.update_game(
            binary,
            game_id,
            max_workers=max_workers,
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def verify(self, binary, game_id, install_path, *, on_line=None, cancel_event=None, **kwargs):
        return amazon.verify_game(
            binary,
            game_id,
            install_path,
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def uninstall(self, binary, game_id, install_path="", *, on_line=None, cancel_event=None, **kwargs):
        return amazon.uninstall_game(
            binary, game_id, on_line=on_line, cancel_event=cancel_event
        )

    def launch_spec(self, binary, game_id, install_path=""):
        return amazon.launch_spec(binary, game_id, install_path=install_path)

    def installed_metadata(self, game_id, install_path="", binary=None):
        return amazon.installed_map().get(str(game_id), {})

    def fetch_size(self, binary, game_id, install_path=""):
        try:
            return amazon.install_size(binary, game_id)
        except Exception:
            return 0

    def default_install_dir(self, database):
        raw = database.get_setting(self.install_setting, "").strip()
        return Path(raw).expanduser() if raw else Path.home() / "Games" / "nile"


# ---------------------------------------------------------------------------
# GOG adapter
# ---------------------------------------------------------------------------
class GogStore(StoreAdapter):
    id = "gog"
    label = "GOG"
    install_setting = "gog_install_dir"
    tool_setting = "gog_tool_path"
    tool_name = "gogdl"
    version_name = "gogdl.version"
    login_url = GOG_AUTH_URL
    login_help = tr(
        "Zaloguj się na stronie GOG, a następnie wklej pełny URL przekierowania "
        "(zawiera parametr code)."
    )

    def _config_dir(self) -> Path:
        directory = db.CONFIG_DIR / "gog"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        return directory

    def _auth_path(self) -> Path:
        return self._config_dir() / "auth.json"

    def _user_path(self) -> Path:
        return self._config_dir() / "user.json"

    def _env(self) -> dict[str, str]:
        return {"GOGDL_CONFIG_PATH": str(self._config_dir())}

    def _run(self, binary, args, *, timeout=180):
        return run_tool(
            binary,
            ["--auth-config-path", str(self._auth_path()), *args],
            env_extra=self._env(),
            timeout=timeout,
        )

    def download_tool(self, progress=None):
        return download_store_tool(
            repo="Heroic-Games-Launcher/heroic-gogdl",
            asset_names={
                "x86_64": "gogdl_linux_x86_64",
                "arm64": "gogdl_linux_arm64",
            },
            destination_name="gogdl",
            version_name=self.version_name,
            progress=progress,
        )

    def _credentials(self, binary) -> dict[str, Any]:
        proc = self._run(binary, ["auth"], timeout=60)
        if proc.returncode != 0:
            raise StoreError(proc_error(proc, tr("Nie można odświeżyć tokena GOG.")))
        data = json_from_output(proc.stdout)
        if not isinstance(data, dict) or not data.get("access_token"):
            raise StoreError(tr("Nie jesteś zalogowany do GOG."))
        return data

    def auth_status(self, binary):
        try:
            data = self._credentials(binary)
        except Exception:
            return {"username": "", "logged_in": False}
        user = self.current_user()
        return {
            "username": user.get("name") or str(data.get("user_id", "")),
            "logged_in": True,
        }

    def finish_login(self, binary, payload, pasted):
        value = (pasted or "").strip()
        code = ""
        match = re.search(r"[?&]code=([^&\s#]+)", value)
        if match:
            code = urllib.parse.unquote(match.group(1))
        elif value and not value.lower().startswith(("http://", "https://")):
            code = value
        if not code:
            raise StoreError(
                tr("Nie znaleziono kodu w adresie przekierowania GOG.")
            )
        proc = self._run(binary, ["auth", "--code", code], timeout=120)
        if proc.returncode != 0:
            raise StoreError(proc_error(proc, tr("Logowanie GOG nie powiodło się.")))
        data = json_from_output(proc.stdout)
        if not isinstance(data, dict) or data.get("error"):
            raise StoreError(tr("Logowanie GOG nie powiodło się."))
        user_id = str(data.get("user_id", "") or "")
        name = user_id
        try:
            profile = _http_json(
                f"https://users.gog.com/users/{user_id}",
                headers={"Authorization": f"Bearer {data.get('access_token', '')}"},
            )
            if isinstance(profile, dict):
                name = str(
                    profile.get("username")
                    or profile.get("name")
                    or profile.get("id")
                    or user_id
                )
        except Exception:
            pass
        user = {"name": name, "user_id": user_id}
        try:
            self._user_path().write_text(json.dumps(user), encoding="utf-8")
            self._user_path().chmod(0o600)
        except OSError:
            pass
        return user

    def logout(self, binary):
        for path in (self._auth_path(), self._user_path()):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def current_user(self):
        try:
            data = json.loads(self._user_path().read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            "name": str(data.get("name", "") or ""),
            "user_id": str(data.get("user_id", "") or ""),
        }

    def _fetch_gog_library(self, token: str, user_id: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        page_token = ""
        while True:
            url = f"https://galaxy-library.gog.com/users/{user_id}/releases"
            if page_token:
                url += "?page_token=" + urllib.parse.quote(page_token)
            data = _http_json(url, headers={"Authorization": f"Bearer {token}"})
            if not isinstance(data, dict):
                break
            items = data.get("items")
            if isinstance(items, list):
                entries.extend(item for item in items if isinstance(item, dict))
            page_token = str(data.get("next_page_token", "") or "")
            if not page_token:
                break
        return entries

    def _fetch_gog_metadata(
        self, external_id: str, certificate: str, token: str
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        if certificate:
            headers["X-GOG-Library-Cert"] = certificate
        data = _http_json(
            f"https://gamesdb.gog.com/platforms/gog/external_releases/{external_id}",
            headers=headers,
        )
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _localized(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("*") or next((v for v in value.values() if v), "") or "")
        return str(value or "")

    def sync(self, binary, installed=None, status=None):
        if status:
            status(tr("Odświeżam token GOG..."))
        credentials = self._credentials(binary)
        token = str(credentials.get("access_token", "") or "")
        user_id = str(credentials.get("user_id", "") or "")
        if status:
            status(tr("Pobieram bibliotekę GOG..."))
        entries = self._fetch_gog_library(token, user_id)
        installed = installed or {}
        games: list[dict[str, Any]] = []

        def fetch(entry: dict[str, Any]) -> dict[str, Any] | None:
            external_id = str(entry.get("external_id", "") or "").strip()
            if not external_id:
                return None
            platform_id = str(entry.get("platform_id", "") or "").strip().lower()
            if platform_id and platform_id != "gog":
                return None
            try:
                meta = self._fetch_gog_metadata(
                    external_id, str(entry.get("certificate", "") or ""), token
                )
            except Exception:
                meta = {}
            if isinstance(meta, dict):
                if meta.get("visible_in_library") is False:
                    return None
                if str(meta.get("type", "") or "").lower() not in {"", "game", "mod"}:
                    return None
            game = meta.get("game") if isinstance(meta, dict) else None
            if not isinstance(game, dict):
                game = {}
            title = self._localized(meta.get("title") if isinstance(meta, dict) else "")
            if not title:
                title = self._localized(game.get("title"))
            if not title:
                return None
            cover = ""
            for key in ("vertical_cover", "cover", "logo", "background"):
                value = game.get(key)
                if isinstance(value, dict) and value.get("url_format"):
                    cover = str(value["url_format"]).replace("{formatter}", "").replace("{ext}", "jpg")
                    break
            icon = ""
            icon_data = game.get("square_icon") or game.get("icon")
            if isinstance(icon_data, dict) and icon_data.get("url_format"):
                icon = str(icon_data["url_format"]).replace("{formatter}", "").replace("{ext}", "jpg")
            summary = self._localized(meta.get("summary") if isinstance(meta, dict) else "")
            developers = game.get("developers")
            developer = ""
            if isinstance(developers, list):
                developer = ", ".join(
                    self._localized(dev.get("name"))
                    for dev in developers
                    if isinstance(dev, dict)
                )
            installed_info = installed.get(external_id) or {}
            install_path = str(installed_info.get("install_path", "") or "")
            if install_path:
                install_path = str(
                    self._resolve_install_path(
                        external_id, install_path, binary=binary
                    )
                )
            game_data = {
                "store": self.id,
                "store_id": external_id,
                "title": title,
                "description": summary,
                "developer": developer,
                "icon_url": icon,
                "cover_url": cover,
                "installed": 1 if install_path and Path(install_path).is_dir() else 0,
                "install_path": install_path,
                "version": str(installed_info.get("version", "") or ""),
                "size": int(installed_info.get("size", 0) or 0),
                "extra_json": json.dumps(
                    {"certificate": entry.get("certificate", "")}
                ),
            }
            if game_data["installed"]:
                try:
                    game_data["spec_json"] = json.dumps(
                        self.launch_spec(binary, external_id, install_path)
                    )
                except Exception:
                    pass
            return game_data

        if status:
            status(tr("Pobieram metadane gier GOG..."))
        with ThreadPoolExecutor(max_workers=6) as pool:
            for game in pool.map(fetch, entries):
                if game is not None:
                    games.append(game)
        games.sort(key=lambda item: item["title"].lower())
        return games

    def _find_info_dir(
        self,
        base: str | Path,
        game_id: str = "",
        max_depth: int = 4,
        allow_any: bool = True,
    ) -> Path | None:
        """Locate a goggame-*.info file (exact id preferred, any id fallback)."""
        root = Path(base).expanduser()
        if not root.is_dir():
            return None
        exact = f"goggame-{game_id}.info" if game_id else ""
        exact_hit: Path | None = None
        any_hit: Path | None = None
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - base_depth
            if depth >= max_depth:
                dirs[:] = []
            if exact and exact in files:
                exact_hit = current_path
                break
            if allow_any and any_hit is None:
                for name in files:
                    if name.startswith("goggame-") and name.endswith(".info"):
                        any_hit = current_path
                        break
        return exact_hit or any_hit

    def find_game_dir(
        self, base: str | Path, game_id: str = ""
    ) -> Path | None:
        """Public helper used by the UI to validate a manually chosen folder."""
        return self._find_info_dir(base, game_id)

    def _gogdl_folder_name(self, binary, game_id: str) -> str:
        cache = getattr(self, "_folder_cache", None)
        if cache is None:
            cache = {}
            self._folder_cache = cache
        if game_id in cache:
            return cache[game_id]
        try:
            proc = self._run(
                binary,
                ["info", str(game_id), "--os", "windows"],
                timeout=120,
            )
            if proc.returncode != 0:
                return ""
            data = json_from_output(proc.stdout)
        except Exception:
            return ""
        folder = ""
        if isinstance(data, dict):
            folder = str(data.get("folder_name", "") or "").strip()
        cache[game_id] = folder
        return folder

    def _log_install(self, message: str) -> None:
        log.info("GOG: %s", message)
        try:
            path = self._config_dir() / "install.log"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass

    def _resolve_install_path(
        self,
        game_id: str,
        install_path: str | Path,
        binary: str | Path | None = None,
    ) -> Path:
        """Find the real GOG game directory (gogdl may append its folder name)."""
        root = Path(install_path).expanduser()
        for base in (root, root.parent):
            found = self._find_info_dir(base, game_id, allow_any=False)
            if found is not None:
                return found
        if binary is not None:
            folder_name = self._gogdl_folder_name(binary, game_id)
            if folder_name:
                folder = Path(folder_name)
                candidates = (
                    [folder]
                    if folder.is_absolute()
                    else [root / folder_name, root.parent / folder_name]
                )
                for candidate in candidates:
                    found = self._find_info_dir(candidate, game_id)
                    if found is not None:
                        return found
        for base in (root, root.parent):
            found = self._find_info_dir(base, game_id)
            if found is not None:
                return found
        return root

    def _find_installed_dir(self, base: Path, game_id: str) -> Path | None:
        return self._find_info_dir(base, game_id)

    def _manifest_path(self, game_id: str) -> Path:
        return (
            self._config_dir()
            / "heroic_gogdl"
            / "manifests"
            / str(game_id)
        )

    def install(self, binary, game_id, target_path, *, max_workers=0, on_line=None, cancel_event=None):
        target = Path(target_path).expanduser()
        parent = target.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=parent, prefix=".boostlayer-write-", delete=True
            ):
                pass
        except OSError as exc:
            message = tr(
                "Brak uprawnień do zapisu w {path}: {error}",
                path=parent,
                error=exc,
            )
            self._log_install(f"install preflight failed target={target}: {exc}")
            return {
                "ok": False,
                "cancelled": False,
                "error": message,
                "output": "",
            }
        existing_info = self._find_info_dir(target, game_id)
        if existing_info is not None:
            self._log_install(
                f"install skipped id={game_id} already present at {existing_info}"
            )
            return {
                "ok": True,
                "cancelled": False,
                "error": "",
                "output": "",
                "install_path": str(existing_info),
            }
        folder_name = self._gogdl_folder_name(binary, game_id)
        manifest_path = self._manifest_path(game_id)
        backup_path = manifest_path.with_name(manifest_path.name + ".boostlayer-backup")
        moved_manifest = False
        if manifest_path.is_file():
            try:
                manifest_path.replace(backup_path)
                moved_manifest = True
                self._log_install(
                    f"temporarily moved stale manifest id={game_id} to {backup_path}"
                )
            except OSError as exc:
                self._log_install(
                    f"cannot move stale manifest id={game_id}: {exc}"
                )
        # gogdl download appends the game's installDirectory to --path, so the
        # parent directory is passed and the resulting folder is moved to the
        # exact directory chosen by the user.
        args = ["download", str(game_id), "--path", str(parent), "--os", "windows"]
        if max_workers > 0:
            args += ["--max-workers", str(int(max_workers))]
        self._log_install(
            f"install id={game_id} target={target} parent={parent} folder_name={folder_name!r}"
        )
        outcome = run_streaming(
            binary,
            ["--auth-config-path", str(self._auth_path()), *args],
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )
        actual: Path | None = None
        candidates: list[Path] = [target]
        if folder_name:
            folder = Path(folder_name)
            if folder.is_absolute():
                candidates.append(folder)
            else:
                candidates.extend([parent / folder_name, target / folder_name])
        for candidate in candidates:
            found = self._find_info_dir(candidate, game_id)
            if found is not None:
                actual = found
                break
        if actual is None:
            actual = self._find_info_dir(parent, game_id, allow_any=False)
        if actual is None:
            actual = self._find_info_dir(parent, game_id)
        self._log_install(
            f"install result id={game_id} found={actual} outcome={outcome.get('ok')}"
        )
        if actual is None and outcome.get("ok"):
            tail = str(outcome.get("output", "") or "")
            message = tr(
                "gogdl nie utworzył folderu gry w {path}. Sprawdź log poniżej.",
                path=parent,
            )
            if tail:
                message += "\n\n" + tail[-1500:]
            self._log_install(
                f"install failed id={game_id} target={target} parent={parent} output={tail[-1500:]}"
            )
            if moved_manifest:
                try:
                    if manifest_path.exists():
                        manifest_path.unlink()
                    backup_path.replace(manifest_path)
                    self._log_install(
                        f"restored manifest id={game_id} after failed install"
                    )
                except OSError as exc:
                    self._log_install(
                        f"cannot restore manifest id={game_id}: {exc}"
                    )
            return {
                **outcome,
                "ok": False,
                "error": message,
                "install_path": "",
            }
        if moved_manifest:
            try:
                if outcome.get("ok") and actual is not None:
                    backup_path.unlink(missing_ok=True)
                    self._log_install(
                        f"removed stale manifest backup id={game_id}"
                    )
                else:
                    if manifest_path.exists():
                        manifest_path.unlink()
                    backup_path.replace(manifest_path)
                    self._log_install(
                        f"restored manifest id={game_id} after aborted install"
                    )
            except OSError as exc:
                self._log_install(
                    f"cannot finalize manifest id={game_id}: {exc}"
                )
        if actual is not None and actual != target and actual != parent:
            try:
                if target.exists() and target.is_dir() and not any(target.iterdir()):
                    target.rmdir()
                if not target.exists():
                    shutil.move(str(actual), str(target))
                    actual = target
                    self._log_install(
                        f"moved id={game_id} to {target}"
                    )
            except OSError as exc:
                self._log_install(
                    f"move failed id={game_id} to {target}: {exc}"
                )
        if actual is None:
            actual = target
        return {**outcome, "install_path": str(actual)}

    def update(self, binary, game_id, install_path, *, max_workers=0, on_line=None, cancel_event=None):
        actual = self._resolve_install_path(game_id, install_path, binary=binary)
        args = ["update", str(game_id), "--path", str(actual), "--os", "windows"]
        if max_workers > 0:
            args += ["--max-workers", str(int(max_workers))]
        return run_streaming(
            binary,
            ["--auth-config-path", str(self._auth_path()), *args],
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def verify(self, binary, game_id, install_path, *, on_line=None, cancel_event=None, **kwargs):
        actual = self._resolve_install_path(game_id, install_path, binary=binary)
        args = ["repair", str(game_id), "--path", str(actual), "--os", "windows"]
        return run_streaming(
            binary,
            ["--auth-config-path", str(self._auth_path()), *args],
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def uninstall(self, binary, game_id, install_path="", *, on_line=None, cancel_event=None, **kwargs):
        if not install_path:
            return {"ok": False, "cancelled": False, "error": tr("Brak ścieżki instalacji GOG."), "output": ""}
        actual = self._resolve_install_path(game_id, install_path, binary=binary)
        try:
            safe_remove_game_dir(actual)
        except Exception as exc:
            return {"ok": False, "cancelled": False, "error": str(exc), "output": ""}
        return {"ok": True, "cancelled": False, "error": "", "output": ""}

    def launch_spec(self, binary, game_id, install_path=""):
        root = self._resolve_install_path(game_id, install_path, binary=binary)
        info_dir = self._find_info_dir(root, game_id)
        if info_dir is None:
            raise StoreError(
                tr(
                    "Brak pliku goggame-*.info w katalogu gry ({path}). "
                    "Wskaż folder gry ręcznie w menu kontekstowym.",
                    path=root,
                )
            )
        info_path = info_dir / f"goggame-{game_id}.info"
        if not info_path.is_file():
            candidates = sorted(info_dir.glob("goggame-*.info"))
            if not candidates:
                raise StoreError(
                    tr(
                        "Brak pliku goggame-*.info w katalogu gry ({path}).",
                        path=root,
                    )
                )
            info_path = candidates[0]
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise StoreError(
                tr("Brak pliku goggame-{id}.info w katalogu gry.", id=game_id)
            ) from exc
        root = info_dir
        tasks = data.get("playTasks") if isinstance(data, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise StoreError(tr("Gra GOG nie ma zadania uruchamiania."))
        task = next(
            (item for item in tasks if isinstance(item, dict) and item.get("isPrimary")),
            tasks[0],
        )
        if not isinstance(task, dict) or task.get("type") not in (None, "FileTask"):
            raise StoreError(tr("Nieobsługiwany typ zadania uruchamiania GOG."))
        relative = str(task.get("path", "") or "").strip()
        if not relative:
            raise StoreError(tr("Zadanie GOG nie zawiera ścieżki EXE."))
        working = str(task.get("workingDir", "") or "").replace("\\", os.sep)
        command = case_insensitive_path(root, os.path.join(working, relative))
        args = task.get("arguments") or []
        if isinstance(args, str):
            try:
                args = shlex.split(args.replace("\\", "/"))
            except ValueError:
                args = [args]
        cwd = command.parent
        if not cwd.is_dir():
            cwd = case_insensitive_path(root, working) if working else root
        return {
            "command": str(command),
            "arguments": [str(item) for item in args],
            "cwd": str(cwd),
            "env": {},
            "install_path": str(root),
        }

    def installed_metadata(self, game_id, install_path="", binary=None):
        path = self._resolve_install_path(game_id, install_path, binary=binary)
        info_dir = self._find_info_dir(path, game_id) or path
        info = info_dir / f"goggame-{game_id}.info"
        if not info.is_file():
            candidates = sorted(info_dir.glob("goggame-*.info"))
            if candidates:
                info = candidates[0]
        version = ""
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
            version = str(data.get("buildId", "") or "")
        except (OSError, TypeError, ValueError):
            pass
        return {"path": str(info_dir), "version": version, "size": 0}

    def fetch_size(self, binary, game_id, install_path=""):
        try:
            proc = self._run(
                binary,
                ["info", str(game_id), "--os", "windows"],
                timeout=120,
            )
            if proc.returncode != 0:
                return 0
            data = json_from_output(proc.stdout)
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        for key in ("disk_size", "download_size"):
            try:
                value = int(data.get(key, 0) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        size = data.get("size")
        if isinstance(size, dict):
            entry = size.get("*")
            if isinstance(entry, dict):
                for key in ("disk_size", "download_size"):
                    try:
                        value = int(entry.get(key, 0) or 0)
                    except (TypeError, ValueError):
                        value = 0
                    if value > 0:
                        return value
        return 0


# ---------------------------------------------------------------------------
# Epic adapter
# ---------------------------------------------------------------------------
class EpicStore(StoreAdapter):
    id = "epic"
    label = "EPIC"
    install_setting = "epic_install_dir"
    tool_setting = "epic_tool_path"
    tool_name = "legendary"
    version_name = "legendary.version"
    login_url = EPIC_LOGIN_URL
    login_help = tr(
        "Zaloguj się na stronie Epic, skopiuj wartość authorizationCode "
        "(lub cały JSON) i wklej ją poniżej."
    )

    def _config_home(self) -> Path:
        directory = db.CONFIG_DIR / "epic"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        return directory

    def _env(self) -> dict[str, str]:
        return {"XDG_CONFIG_HOME": str(self._config_home())}

    def _user_path(self) -> Path:
        return self._config_home() / "legendary" / "user.json"

    def _run(self, binary, args, *, timeout=180):
        return run_tool(binary, args, env_extra=self._env(), timeout=timeout)

    def download_tool(self, progress=None):
        return download_store_tool(
            repo="legendary-gl/legendary",
            asset_names={
                "x86_64": "legendary_linux_x64",
                "arm64": "legendary_linux_arm64",
            },
            destination_name="legendary",
            version_name=self.version_name,
            progress=progress,
        )

    def auth_status(self, binary):
        user = self.current_user()
        return {
            "username": user.get("name", ""),
            "logged_in": bool(user.get("name")),
        }

    def finish_login(self, binary, payload, pasted):
        value = (pasted or "").strip()
        code = ""
        if value.startswith("{"):
            try:
                data = json.loads(value)
                code = str(data.get("authorizationCode", "") or "")
            except (TypeError, ValueError):
                code = ""
        if not code:
            match = re.search(r"authorizationCode=([^&\s#]+)", value)
            if match:
                code = urllib.parse.unquote(match.group(1))
        if not code and value and not value.lower().startswith(("http://", "https://")):
            code = value.strip('"')
        if not code:
            raise StoreError(tr("Nie znaleziono authorizationCode."))
        proc = self._run(binary, ["auth", "--code", code], timeout=180)
        if proc.returncode != 0:
            raise StoreError(proc_error(proc, tr("Logowanie Epic nie powiodło się.")))
        user = self.current_user()
        if not user.get("name"):
            raise StoreError(tr("Logowanie Epic nie powiodło się."))
        return user

    def logout(self, binary):
        try:
            self._run(binary, ["auth", "--delete"], timeout=60)
        except Exception:
            pass
        try:
            self._user_path().unlink(missing_ok=True)
        except OSError:
            pass

    def current_user(self):
        try:
            data = json.loads(self._user_path().read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            "name": str(data.get("displayName", "") or data.get("account_id", "")),
            "user_id": str(data.get("account_id", "") or ""),
        }

    @staticmethod
    def _epic_cover(metadata: Any) -> str:
        if not isinstance(metadata, dict):
            return ""
        images = metadata.get("keyImages")
        if not isinstance(images, list):
            return ""
        preferred = ("DieselStoreFrontWide", "OfferImageTall", "Thumbnail", "DieselGameBox")
        for kind in preferred:
            for image in images:
                if isinstance(image, dict) and image.get("type") == kind and image.get("url"):
                    return str(image["url"])
        for image in images:
            if isinstance(image, dict) and image.get("url"):
                return str(image["url"])
        return ""

    def sync(self, binary, installed=None, status=None):
        if status:
            status(tr("Pobieram bibliotekę Epic..."))
        proc = self._run(binary, ["list", "--json"], timeout=300)
        if proc.returncode != 0:
            raise StoreError(proc_error(proc, tr("Nie można pobrać biblioteki Epic.")))
        owned = json_from_output(proc.stdout)
        if not isinstance(owned, list):
            raise StoreError(tr("Nieprawidłowa odpowiedź legendary (biblioteka)."))
        installed_proc = self._run(binary, ["list-installed", "--json"], timeout=120)
        installed_list = []
        if installed_proc.returncode == 0:
            try:
                parsed = json_from_output(installed_proc.stdout)
                if isinstance(parsed, list):
                    installed_list = parsed
            except Exception:
                installed_list = []
        installed_map = {
            str(item.get("app_name", "")): item
            for item in installed_list
            if isinstance(item, dict) and item.get("app_name")
        }
        installed = installed or {}
        games: list[dict[str, Any]] = []
        for item in owned:
            if not isinstance(item, dict):
                continue
            app_name = str(item.get("app_name", "") or "").strip()
            title = str(item.get("app_title", "") or "").strip()
            if not app_name or not title:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            inst = installed_map.get(app_name) or installed.get(app_name) or {}
            third_party = str(
                item.get("third_party_store", "")
                or ("ubisoft" if item.get("is_ubisoft_game") else "")
                or ("ea" if item.get("is_origin_game") else "")
            )
            games.append(
                {
                    "store": self.id,
                    "store_id": app_name,
                    "title": title,
                    "description": str(metadata.get("description", "") or ""),
                    "developer": str(metadata.get("developer", "") or ""),
                    "icon_url": self._epic_cover(metadata),
                    "cover_url": self._epic_cover(metadata),
                    "installed": 1 if inst else 0,
                    "install_path": str(inst.get("install_path", "") or ""),
                    "version": str(inst.get("version", "") or ""),
                    "size": int(inst.get("install_size", 0) or 0),
                    "extra_json": json.dumps({"third_party_store": third_party}),
                }
            )
            if inst:
                try:
                    games[-1]["spec_json"] = json.dumps(
                        self.launch_spec(
                            binary,
                            app_name,
                            str(inst.get("install_path", "") or ""),
                        )
                    )
                except Exception:
                    pass
        games.sort(key=lambda item: item["title"].lower())
        return games

    def install(self, binary, game_id, target_path, *, max_workers=0, on_line=None, cancel_event=None):
        target = Path(target_path).expanduser()
        args = [
            "install",
            str(game_id),
            "--platform",
            "Windows",
            "--base-path",
            str(target.parent),
            "--game-folder",
            target.name,
            "--skip-sdl",
            "--skip-dlcs",
            "-y",
        ]
        if max_workers > 0:
            args += ["--max-workers", str(int(max_workers))]
        return run_streaming(
            binary,
            args,
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def update(self, binary, game_id, install_path, *, max_workers=0, on_line=None, cancel_event=None):
        args = ["update", str(game_id), "-y", "--skip-sdl"]
        if max_workers > 0:
            args += ["--max-workers", str(int(max_workers))]
        return run_streaming(
            binary,
            args,
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def verify(self, binary, game_id, install_path, *, on_line=None, cancel_event=None, **kwargs):
        return run_streaming(
            binary,
            ["repair", str(game_id), "-y", "--skip-sdl"],
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def uninstall(self, binary, game_id, install_path="", *, on_line=None, cancel_event=None, **kwargs):
        return run_streaming(
            binary,
            ["uninstall", str(game_id), "-y"],
            env_extra=self._env(),
            on_line=on_line,
            cancel_event=cancel_event,
        )

    def launch_spec(self, binary, game_id, install_path=""):
        proc = self._run(
            binary,
            ["launch", str(game_id), "--json", "--no-wine", "--skip-version-check"],
            timeout=180,
        )
        if proc.returncode != 0:
            raise StoreError(proc_error(proc, tr("Nie można przygotować uruchomienia Epic.")))
        data = json_from_output(proc.stdout)
        if not isinstance(data, dict):
            raise StoreError(tr("Nieprawidłowa odpowiedź legendary (launch)."))
        game_dir = str(data.get("game_directory", "") or "").strip()
        executable = str(data.get("game_executable", "") or "").strip()
        if not executable:
            raise StoreError(tr("Legendary nie zwrócił ścieżki EXE gry."))
        command = executable if os.path.isabs(executable) else str(Path(game_dir) / executable)
        args: list[str] = []
        for key in ("game_parameters", "user_parameters", "egl_parameters"):
            value = data.get(key) or []
            if isinstance(value, list):
                args.extend(str(item) for item in value)
            elif isinstance(value, str) and value.strip():
                args.extend(shlex.split(value))
        env_raw = data.get("environment") or {}
        env = {}
        if isinstance(env_raw, dict):
            env = {str(k): str(v) for k, v in env_raw.items() if v is not None}
        cwd = str(data.get("working_directory", "") or "") or game_dir or str(Path(command).parent)
        return {"command": command, "arguments": args, "cwd": cwd, "env": env}

    def installed_metadata(self, game_id, install_path="", binary=None):
        if binary is None:
            return {}
        try:
            proc = self._run(
                binary, ["list-installed", "--json"], timeout=120
            )
        except Exception:
            return {}
        if proc.returncode != 0:
            return {}
        try:
            data = json_from_output(proc.stdout)
        except Exception:
            return {}
        if not isinstance(data, list):
            return {}
        for item in data:
            if isinstance(item, dict) and str(item.get("app_name", "")) == str(game_id):
                return item
        return {}

    def fetch_size(self, binary, game_id, install_path=""):
        try:
            proc = self._run(
                binary,
                ["info", str(game_id), "--json", "--platform", "Windows"],
                timeout=120,
            )
            if proc.returncode != 0:
                return 0
            data = json_from_output(proc.stdout)
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        manifest = data.get("manifest")
        if isinstance(manifest, dict):
            for key in ("disk_size", "download_size"):
                try:
                    value = int(manifest.get(key, 0) or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > 0:
                    return value
        return 0


STORES: dict[str, StoreAdapter] = {
    "amazon": AmazonStore(),
    "gog": GogStore(),
    "epic": EpicStore(),
}


# ---------------------------------------------------------------------------
# Qt workers
# ---------------------------------------------------------------------------
class StoreSetupWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(self, adapter: StoreAdapter, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter

    def run(self) -> None:
        try:
            self.status.emit(tr("Pobieram narzędzie {store}...", store=self.adapter.label))
            outcome = self.adapter.download_tool(
                progress=lambda done, total: self.status.emit(
                    tr("Pobieram {store}... {done}", store=self.adapter.label, done=_human(done))
                )
            )
            self.result.emit({"ok": True, **outcome})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class StoreBeginLoginWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, adapter: StoreAdapter, binary: str, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.binary = binary

    def run(self) -> None:
        try:
            self.result.emit({"ok": True, "data": self.adapter.begin_login(self.binary)})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class StoreFinishLoginWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, adapter, binary, payload, pasted, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.binary = binary
        self.payload = payload
        self.pasted = pasted

    def run(self) -> None:
        try:
            user = self.adapter.finish_login(self.binary, self.payload, self.pasted)
            self.result.emit({"ok": True, "user": user})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class StoreLogoutWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, adapter, binary, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.binary = binary

    def run(self) -> None:
        try:
            self.adapter.logout(self.binary)
            self.result.emit({"ok": True})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class StoreSyncWorker(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(self, adapter, binary, installed, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.binary = binary
        self.installed = installed

    def run(self) -> None:
        try:
            status = self.adapter.auth_status(self.binary)
            if not status.get("logged_in"):
                self.result.emit(
                    {"ok": False, "error": tr("Nie jesteś zalogowany do {store}.", store=self.adapter.label)}
                )
                return
            games = self.adapter.sync(self.binary, installed=self.installed, status=self.status.emit)
            self.result.emit(
                {
                    "ok": True,
                    "games": games,
                    "username": status.get("username", ""),
                }
            )
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class StoreJobWorker(QThread):
    output = pyqtSignal(str)
    progress = pyqtSignal(object)
    result = pyqtSignal(object)

    def __init__(
        self,
        adapter,
        action,
        binary,
        game_id,
        *,
        target_path="",
        install_path="",
        max_workers=0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.action = action
        self.binary = binary
        self.game_id = game_id
        self.target_path = target_path
        self.install_path = install_path
        self.max_workers = max_workers
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _on_line(self, line: str) -> None:
        self.output.emit(line)
        parsed = _generic_progress(line)
        if parsed:
            self.progress.emit(parsed)

    def run(self) -> None:
        try:
            if self.action == "install":
                outcome = self.adapter.install(
                    self.binary,
                    self.game_id,
                    self.target_path,
                    max_workers=self.max_workers,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            elif self.action == "update":
                outcome = self.adapter.update(
                    self.binary,
                    self.game_id,
                    self.install_path,
                    max_workers=self.max_workers,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            elif self.action == "verify":
                outcome = self.adapter.verify(
                    self.binary,
                    self.game_id,
                    self.install_path,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            elif self.action == "uninstall":
                outcome = self.adapter.uninstall(
                    self.binary,
                    self.game_id,
                    self.install_path,
                    on_line=self._on_line,
                    cancel_event=self._cancel,
                )
            else:
                raise StoreError(tr("Nieznana operacja sklepu."))
            metadata = self.adapter.installed_metadata(
                self.game_id, self.target_path or self.install_path, binary=self.binary
            )
            self.result.emit(
                {
                    **outcome,
                    "action": self.action,
                    "game_id": self.game_id,
                    "target_path": self.target_path,
                    "install_path": str(
                        outcome.get("install_path") or self.install_path
                    ),
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
                    "game_id": self.game_id,
                }
            )


class StoreSpecWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, adapter, binary, game_id, install_path="", parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.binary = binary
        self.game_id = game_id
        self.install_path = install_path

    def run(self) -> None:
        try:
            spec = self.adapter.launch_spec(
                self.binary, self.game_id, self.install_path
            )
            self.result.emit({"ok": True, "spec": spec, "game_id": self.game_id})
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class StoreCoverWorker(QThread):
    result = pyqtSignal(str, str, str)

    def __init__(self, adapter, game, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.game = game

    def run(self) -> None:
        store_id = str(self.game.get("store_id", ""))
        try:
            path = self.adapter.fetch_cover(self.game)
        except Exception:
            path = ""
        self.result.emit(self.adapter.id, store_id, path)


class StoreCoverBatchWorker(QThread):
    progress = pyqtSignal(str)
    cover_ready = pyqtSignal(str, str, str)
    done = pyqtSignal()

    def __init__(self, adapter, games: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.games = list(games)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        total = len(self.games)
        completed = 0
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(self.adapter.fetch_cover, game): game
                    for game in self.games
                }
                for future in as_completed(futures):
                    if self._cancel.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
                    game = futures[future]
                    try:
                        path = future.result()
                    except Exception:
                        path = ""
                    completed += 1
                    if path:
                        self.cover_ready.emit(
                            self.adapter.id,
                            str(game.get("store_id", "")),
                            path,
                        )
                    self.progress.emit(
                        tr(
                            "Pobieram okładki {store}: {done}/{total}",
                            store=self.adapter.label,
                            done=completed,
                            total=total,
                        )
                    )
        finally:
            self.done.emit()


class StoreSizeBatchWorker(QThread):
    progress = pyqtSignal(str)
    size_ready = pyqtSignal(str, str, int)
    done = pyqtSignal()

    def __init__(
        self,
        adapter,
        binary: str,
        games: list[dict[str, Any]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.binary = binary
        self.games = list(games)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        total = len(self.games)
        completed = 0
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {}
                for game in self.games:
                    if self._cancel.is_set():
                        break
                    futures[
                        pool.submit(
                            self.adapter.fetch_size,
                            self.binary,
                            str(game.get("store_id", "")),
                            str(game.get("install_path", "") or ""),
                        )
                    ] = game
                    time.sleep(0.12)
                for future in as_completed(futures):
                    if self._cancel.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
                    game = futures[future]
                    try:
                        size = int(future.result() or 0)
                    except Exception:
                        size = 0
                    completed += 1
                    if size > 0:
                        self.size_ready.emit(
                            self.adapter.id,
                            str(game.get("store_id", "")),
                            size,
                        )
                    self.progress.emit(
                        tr(
                            "Pobieram rozmiary {store}: {done}/{total}",
                            store=self.adapter.label,
                            done=completed,
                            total=total,
                        )
                    )
        finally:
            self.done.emit()


def _human(value: int) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "?"
