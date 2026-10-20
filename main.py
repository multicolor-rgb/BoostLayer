#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BoostLayer — ultra-lean native Linux clone of "Lossless Scaling" with built-in OSD.

Real-time window/screen upscaling (AMD FSR 1.0 EASU+RCAS, Integer, Nearest, Bicubic),
in-shader frame generation, a performance OSD and a global hotkey.  Runs on Mesa
(AMD Radeon / Intel iris) and NVIDIA under both X11 and Wayland.

FSR 1.0 EASU/RCAS shader logic is a GLSL port of AMD FidelityFX Super Resolution 1.0
(c) 2021 Advanced Micro Devices, Inc. — MIT License.

Copyright (c) 2026 multicolor-rgb.  MIT License.
"""

import os
import sys
import gc
import time
import ctypes
import struct
import zlib
import shutil
import subprocess
import threading

import numpy as np

# ---------------------------------------------------------------------------
# Optional dependencies (graceful fallbacks).  The application reports exactly
# which backend is missing instead of crashing with an obscure ImportError.
# ---------------------------------------------------------------------------
try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    import glfw
    from OpenGL import GL as gl
    HAS_GL = True
except ImportError:  # pragma: no cover
    HAS_GL = False

try:
    import mss
    HAS_MSS = True
except ImportError:  # pragma: no cover
    HAS_MSS = False

try:
    from pynput import keyboard as _pynput_keyboard
    HAS_PYNPUT = True
except ImportError:  # pragma: no cover
    HAS_PYNPUT = False

try:
    import evdev
    HAS_EVDEV = True
except ImportError:  # pragma: no cover
    HAS_EVDEV = False

try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:  # pragma: no cover
    HAS_CTK = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME = "BoostLayer"
APP_VERSION = "1.0.1"
DEFAULT_HOTKEY = "<ctrl>+<alt>+s"

# Persistent log (especially useful for the packaged GUI build, where stdout is
# not attached to a terminal).
APP_LOG = os.path.join(
    os.environ.get(
        "XDG_STATE_HOME",
        os.path.join(os.path.expanduser("~"), ".local", "state")),
    "boostlayer", "boostlayer.log")


def _log(msg):
    """Append a timestamped line to the application log (best effort)."""
    try:
        os.makedirs(os.path.dirname(APP_LOG), exist_ok=True)
        with open(APP_LOG, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _acquire_single_instance():
    """Take an exclusive lock so only one BoostLayer instance can run.

    Returns an open file object on success, ``False`` when another instance
    holds the lock, or ``None`` when locking is not available.  The lock is
    released by the kernel when the process exits (even after a crash)."""
    try:
        import fcntl
    except ImportError:
        return None
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(base, "boostlayer-%d.lock" % os.getuid())
    try:
        fh = open(path, "w")
    except Exception:
        return None
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    try:
        fh.write(str(os.getpid()))
        fh.flush()
    except Exception:
        pass
    return fh



# Scaling-mode identifiers are stable ASCII keys; display names are localised.
SCALE_MODE_KEYS = ["fsr", "integer", "nearest", "bicubic"]
SCALE_MODE_IDS = {k: i for i, k in enumerate(SCALE_MODE_KEYS)}
SCALE_MODE_NAMES = {i: k for i, k in enumerate(SCALE_MODE_KEYS)}

# ---------------------------------------------------------------------------
# Localisation (English / German / Polish).
# GUI strings may use full Unicode; `osd_*` strings must stay ASCII-only
# because the embedded 5x7 OSD font only covers ASCII.
# ---------------------------------------------------------------------------
LANGUAGES = {
    "en": "English",
    "de": "Deutsch",
    "pl": "Polski",
}

TRANSLATIONS = {
    "en": {
        "tab_scaling": "Scaling & FG",
        "tab_osd": "Performance OSD",
        "language": "Language",
        "scaling_type": "Scaling type",
        "sharpness": "Sharpness",
        "aspect_ratio": "Aspect ratio",
        "auto": "Auto",
        "custom": "Custom",
        "custom_multiplier": "Custom multiplier",
        "frame_generation": "Frame generation (shader)",
        "capture_delay_ms": "Capture delay (ms)",
        "capture_target": "Capture target",
        "capture_monitor": "Capture monitor",
        "output_monitor": "Output monitor",
        "fullscreen": "Fullscreen",
        "active_window": "Active Window",
        "window": "Window",
        "target_window": "Target window",
        "refresh": "Refresh",
        "select_window": "Click window",
        "capture_note": "Window captures the selected window, Active follows focus, Fullscreen grabs the topmost window on the selected monitor. BoostLayer never captures its own overlay (no mirror loop).",
        "performance_osd": "Performance OSD",
        "displayed_metrics": "Displayed metrics",
        "metric_fps": "FPS (Capture & Render)",
        "metric_cpu": "CPU usage",
        "metric_gpu": "GPU usage",
        "metric_ram": "RAM usage",
        "gpu_note": "GPU telemetry: AMD (sysfs gpu_busy_percent), Intel (DRM freq / intel_gpu_top), NVIDIA (nvidia-smi).",
        "start_scaling": "Start Scaling",
        "stop_scaling": "Stop Scaling",
        "quit": "Quit",
        "status_listening": "Listening for hotkey...",
        "status_scaling": "SCALING",
        "status_idle": "IDLE",
        "status_fmt": "Hotkey: %s — Listening | %s | %s | %s",
        "mode_fsr": "FSR 1.0",
        "mode_integer": "Integer Scaling",
        "mode_nearest": "Nearest Neighbor",
        "mode_bicubic": "Bicubic",
        "osd_mode_fsr": "FSR 1.0",
        "osd_mode_integer": "INTEGER SCALING",
        "osd_mode_nearest": "NEAREST NEIGHBOR",
        "osd_mode_bicubic": "BICUBIC",
        "osd_fps": "FPS  CAPTURE:%5.1f   RENDER:%5.1f",
        "osd_fg_sharp": "FG: %s   SHARPNESS: %d",
        "osd_on": "ON",
        "osd_off": "OFF",
    },
    "de": {
        "tab_scaling": "Skalierung & FG",
        "tab_osd": "Performance-OSD",
        "language": "Sprache",
        "scaling_type": "Skalierungstyp",
        "sharpness": "Schärfe",
        "aspect_ratio": "Seitenverhältnis",
        "auto": "Auto",
        "custom": "Benutzerdefiniert",
        "custom_multiplier": "Benutzerdefinierter Multiplikator",
        "frame_generation": "Frame-Generierung (Shader)",
        "capture_delay_ms": "Aufnahmeverzögerung (ms)",
        "capture_target": "Aufnahmeziel",
        "capture_monitor": "Aufnahme-Monitor",
        "output_monitor": "Ausgabe-Monitor",
        "fullscreen": "Vollbild",
        "active_window": "Aktives Fenster",
        "window": "Fenster",
        "target_window": "Zielfenster",
        "refresh": "Aktualisieren",
        "select_window": "Fenster klicken",
        "capture_note": "Fenster erfasst das gewählte Fenster, Aktiv folgt dem Fokus, Vollbild nimmt das oberste Fenster am gewählten Monitor. BoostLayer erfasst nie sein eigenes Overlay (keine Spiegel-Schleife).",
        "performance_osd": "Performance-OSD",
        "displayed_metrics": "Angezeigte Metriken",
        "metric_fps": "FPS (Aufnahme & Render)",
        "metric_cpu": "CPU-Auslastung",
        "metric_gpu": "GPU-Auslastung",
        "metric_ram": "RAM-Auslastung",
        "gpu_note": "GPU-Telemetrie: AMD (sysfs gpu_busy_percent), Intel (DRM-Frequenz / intel_gpu_top), NVIDIA (nvidia-smi).",
        "start_scaling": "Skalierung starten",
        "stop_scaling": "Skalierung stoppen",
        "quit": "Beenden",
        "status_listening": "Warte auf Hotkey...",
        "status_scaling": "SKALIERUNG",
        "status_idle": "LEERLAUF",
        "status_fmt": "Hotkey: %s — lauscht | %s | %s | %s",
        "mode_fsr": "FSR 1.0",
        "mode_integer": "Ganzzahlige Skalierung",
        "mode_nearest": "Nächster Nachbar",
        "mode_bicubic": "Bikubisch",
        "osd_mode_fsr": "FSR 1.0",
        "osd_mode_integer": "INTEGER-SKALIERUNG",
        "osd_mode_nearest": "NAECHSTER NACHBAR",
        "osd_mode_bicubic": "BIKUBISCH",
        "osd_fps": "FPS  AUFNAHME:%5.1f  RENDER:%5.1f",
        "osd_fg_sharp": "FG: %s   SCHAERFE: %d",
        "osd_on": "AN",
        "osd_off": "AUS",
    },
    "pl": {
        "tab_scaling": "Skalowanie i FG",
        "tab_osd": "OSD wydajności",
        "language": "Język",
        "scaling_type": "Typ skalowania",
        "sharpness": "Ostrość",
        "aspect_ratio": "Proporcje obrazu",
        "auto": "Auto",
        "custom": "Niestandardowe",
        "custom_multiplier": "Własny mnożnik",
        "frame_generation": "Generowanie klatek (shader)",
        "capture_delay_ms": "Opóźnienie przechwytywania (ms)",
        "capture_target": "Cel przechwytywania",
        "capture_monitor": "Monitor przechwytywania",
        "output_monitor": "Monitor wyjścia",
        "fullscreen": "Pełny ekran",
        "active_window": "Aktywne okno",
        "window": "Okno",
        "target_window": "Okno docelowe",
        "refresh": "Odśwież",
        "select_window": "Kliknij okno",
        "capture_note": "Okno przechwytuje wybrane okno, Aktywne podąża za fokusem, Pełny ekran bierze najwyższe okno na wybranym monitorze. BoostLayer nigdy nie przechwytuje własnego overlayu (brak pętli lustra).",
        "performance_osd": "OSD wydajności",
        "displayed_metrics": "Wyświetlane metryki",
        "metric_fps": "FPS (Przechwyt i render)",
        "metric_cpu": "Użycie CPU",
        "metric_gpu": "Użycie GPU",
        "metric_ram": "Użycie RAM",
        "gpu_note": "Telemetria GPU: AMD (sysfs gpu_busy_percent), Intel (częstotliwość DRM / intel_gpu_top), NVIDIA (nvidia-smi).",
        "start_scaling": "Start skalowania",
        "stop_scaling": "Zatrzymaj skalowanie",
        "quit": "Zamknij",
        "status_listening": "Nasłuchiwanie skrótu...",
        "status_scaling": "SKALOWANIE",
        "status_idle": "BEZCZYNNOŚĆ",
        "status_fmt": "Skrót: %s — nasłuchiwanie | %s | %s | %s",
        "mode_fsr": "FSR 1.0",
        "mode_integer": "Skalowanie całkowite",
        "mode_nearest": "Najbliższy sąsiad",
        "mode_bicubic": "Bikubiczne",
        "osd_mode_fsr": "FSR 1.0",
        "osd_mode_integer": "SKALOWANIE CALKOWITE",
        "osd_mode_nearest": "NAJBLIZSZY SASIAD",
        "osd_mode_bicubic": "BIKUBICZNE",
        "osd_fps": "FPS  PRZECHWYT:%5.1f  RENDER:%5.1f",
        "osd_fg_sharp": "FG: %s   OSTROSC: %d",
        "osd_on": "ON",
        "osd_off": "OFF",
    },
}


def tr(lang, key):
    """Return the localised string for `key` in language `lang`."""
    table = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    return table.get(key, TRANSLATIONS["en"].get(key, key))


# ---------------------------------------------------------------------------
# Environment / hardware detection
# ---------------------------------------------------------------------------
def detect_display_server():
    """Return 'wayland', 'x11' or 'unknown'."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    st = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if st == "wayland":
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def detect_gpu_vendor():
    """Detect the primary GPU vendor from sysfs. Returns 'nvidia'/'amd'/'intel'/'unknown'."""
    vendors = []
    base = "/sys/class/drm"
    if os.path.isdir(base):
        try:
            entries = os.listdir(base)
        except OSError:
            entries = []
        for entry in entries:
            if entry.startswith("card"):
                vfile = os.path.join(base, entry, "device", "vendor")
                if os.path.isfile(vfile):
                    try:
                        with open(vfile, "r") as f:
                            vendors.append(f.read().strip())
                    except OSError:
                        pass
    if any("0x10de" in v for v in vendors):
        return "nvidia"
    if any("0x1002" in v for v in vendors):
        return "amd"
    if any("0x8086" in v for v in vendors):
        return "intel"
    if shutil.which("nvidia-smi"):
        return "nvidia"
    return "unknown"


def _read_file(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return None


def _list_drm():
    base = "/sys/class/drm"
    try:
        return [e for e in os.listdir(base) if e.startswith("card")]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# GPU telemetry
# ---------------------------------------------------------------------------
class GpuMonitor:
    """Reads GPU usage for AMD (sysfs gpu_busy_percent), Intel (DRM frequency
    ratio / intel_gpu_top) and NVIDIA (nvidia-smi).  All I/O is cached per call
    and never blocks the render loop."""

    def __init__(self):
        self.vendor = detect_gpu_vendor()
        self._amd_busy_path = self._find_amd_busy()
        self._intel_freq = self._find_intel_freq()
        self._name = self._detect_name()

    # -- detection helpers -------------------------------------------------
    def _find_amd_busy(self):
        if self.vendor == "amd":
            for card in _list_drm():
                p = os.path.join("/sys/class/drm", card, "device", "gpu_busy_percent")
                if os.path.isfile(p):
                    return p
        return None

    def _find_intel_freq(self):
        if self.vendor == "intel":
            for card in _list_drm():
                dev = os.path.join("/sys/class/drm", card, "device")
                if os.path.isfile(os.path.join(dev, "gt_cur_freq_mhz")):
                    return dev
        return None

    def _detect_name(self):
        if self.vendor == "nvidia":
            return "NVIDIA GPU"
        if self.vendor == "amd":
            return "AMD Radeon"
        if self.vendor == "intel":
            return "Intel iGPU"
        return "Unknown GPU"

    # -- readers -----------------------------------------------------------
    def _read_amd(self):
        v = _read_file(self._amd_busy_path)
        if v is None:
            return None
        try:
            return max(0.0, min(100.0, float(v)))
        except ValueError:
            return None

    def _read_intel(self):
        # Prefer the DRM frequency ratio; fall back to intel_gpu_top parsing.
        if self._intel_freq:
            cur = _read_file(os.path.join(self._intel_freq, "gt_cur_freq_mhz"))
            mx = _read_file(os.path.join(self._intel_freq, "gt_max_freq_mhz"))
            if mx is None:
                mx = _read_file(os.path.join(self._intel_freq, "gt_RP0_freq_mhz"))
            if cur and mx:
                try:
                    curf, mxf = float(cur), float(mx)
                    if mxf > 0:
                        return max(0.0, min(100.0, (curf / mxf) * 100.0))
                except ValueError:
                    pass
        top = shutil.which("intel_gpu_top")
        if top:
            try:
                out = subprocess.run(
                    [top, "-J", "-s", "250"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=2, text=True,
                ).stdout
                # intel_gpu_top -J emits JSON; take the first "busy" value.
                for token in out.split(","):
                    if '"busy"' in token:
                        val = "".join(ch for ch in token if ch.isdigit() or ch == ".")
                        if val:
                            return max(0.0, min(100.0, float(val)))
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass
        return None

    def _read_nvidia(self):
        if not shutil.which("nvidia-smi"):
            return None
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=2, text=True,
            ).stdout
            val = out.strip().splitlines()
            if val:
                return max(0.0, min(100.0, float(val[0].strip())))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        return None

    def usage(self):
        """Return GPU usage percentage (0-100) or None if unavailable."""
        if self.vendor == "amd":
            return self._read_amd()
        if self.vendor == "intel":
            return self._read_intel()
        if self.vendor == "nvidia":
            return self._read_nvidia()
        return None

    @property
    def name(self):
        return self._name


# ---------------------------------------------------------------------------
# Embedded 5x7 bitmap font (subset sufficient for the OSD).
# Each glyph is 7 strings of 5 characters; '#' = lit pixel.
# ---------------------------------------------------------------------------
def _g(*rows):
    return rows


FONT_5X7 = {
    " ": _g(".....", ".....", ".....", ".....", ".....", ".....", "....."),
    "0": _g(".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": _g("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": _g(".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": _g("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    "4": _g("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": _g("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": _g("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": _g("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": _g(".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": _g(".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    "A": _g(".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": _g("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": _g(".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": _g("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": _g("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": _g("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": _g(".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": _g("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": _g(".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": _g("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": _g("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": _g("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": _g("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": _g("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": _g(".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": _g("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": _g(".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".####"),
    "R": _g("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": _g(".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": _g("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": _g("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": _g("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": _g("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": _g("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": _g("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": _g("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    ":": _g(".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    ".": _g(".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    "%": _g("##..#", "##..#", "...#.", "..#..", ".#...", "#..##", "#..##"),
    "/": _g("....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."),
    "-": _g(".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "+": _g(".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    "(": _g("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": _g(".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "=": _g(".....", ".....", "#####", ".....", "#####", ".....", "....."),
    ",": _g(".....", ".....", ".....", ".....", ".##..", ".##..", ".#..."),
    ">": _g(".....", "#....", ".#...", "..#..", ".#...", "#....", "....."),
    "<": _g(".....", "...#.", "..#..", ".#...", "..#..", "...#.", "....."),
    "[": _g(".###.", ".#...", ".#...", ".#...", ".#...", ".#...", ".###."),
    "]": _g(".###.", "...#.", "...#.", "...#.", "...#.", "...#.", ".###."),
    "_": _g(".....", ".....", ".....", ".....", ".....", ".....", "#####"),
    "|": _g("..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "x": _g(".....", ".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"),
    "v": _g(".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
}

# ---------------------------------------------------------------------------
# Shader sources (embedded as strings, per requirement).
# ---------------------------------------------------------------------------

# Fullscreen triangle vertex shader (no vertex buffer needed).
VERT_SRC = """
#version 400 core
const vec2 VERTS[3] = vec2[3](
    vec2(-1.0, -1.0),
    vec2( 3.0, -1.0),
    vec2(-1.0,  3.0)
);
out vec2 v_uv;
void main() {
    vec2 p = VERTS[gl_VertexID];
    v_uv = p * 0.5 + 0.5;
    gl_Position = vec4(p, 0.0, 1.0);
}
"""

# Scaling shader: FSR 1.0 EASU / Integer / Nearest / Bicubic, selected by
# u_mode.  Input sampled with textureGather/texture()/texelFetch so no new
# texture is ever allocated in the hot path.
SCALE_FRAG_SRC = """
#version 400 core
out vec4 fragColor;

uniform sampler2D u_src;
uniform vec2  u_srcSize;   // input texture size in texels
uniform vec2  u_outSize;   // output target size in pixels
uniform vec4  u_srcRect;   // source region (x, y, w, h) in input texel space
uniform vec4  u_dstRect;   // dest region   (x, y, w, h) in output pixel space
uniform int   u_mode;      // 0 FSR, 1 Integer, 2 Nearest, 3 Bicubic
uniform vec4  u_con0;
uniform vec4  u_con1;
uniform vec4  u_con2;
uniform vec4  u_con3;

// ==========================================================================
// FSR 1.0 EASU  (AMD FidelityFX Super Resolution 1.0, MIT)
// ==========================================================================
vec4 FsrEasuRF(vec2 p){ return textureGather(u_src, p, 0); }
vec4 FsrEasuGF(vec2 p){ return textureGather(u_src, p, 1); }
vec4 FsrEasuBF(vec2 p){ return textureGather(u_src, p, 2); }

void FsrEasuTapF(inout vec3 aC, inout float aW, vec2 off, vec2 dir,
                 vec2 len, float lob, float clp, vec3 c){
    vec2 v;
    v.x = (off.x * dir.x) + (off.y * dir.y);
    v.y = (off.x * (-dir.y)) + (off.y * dir.x);
    v *= len;
    float d2 = v.x * v.x + v.y * v.y;
    d2 = min(d2, clp);
    float wB = (2.0 / 5.0) * d2 + (-1.0);
    float wA = lob * d2 + (-1.0);
    wB *= wB;
    wA *= wA;
    wB = (25.0 / 16.0) * wB + (-(25.0 / 16.0 - 1.0));
    float w = wB * wA;
    aC += c * w;
    aW += w;
}

void FsrEasuSetF(inout vec2 dir, inout float len, vec2 pp,
                 bool biS, bool biT, bool biU, bool biV,
                 float lA, float lB, float lC, float lD, float lE){
    float w = 0.0;
    if(biS) w = (1.0 - pp.x) * (1.0 - pp.y);
    if(biT) w = pp.x * (1.0 - pp.y);
    if(biU) w = (1.0 - pp.x) * pp.y;
    if(biV) w = pp.x * pp.y;
    float dc = lD - lC;
    float cb = lC - lB;
    float lenX = max(abs(dc), abs(cb));
    lenX = 1.0 / max(lenX, 1e-6);
    float dirX = lD - lB;
    dir.x += dirX * w;
    lenX = clamp(abs(dirX) * lenX, 0.0, 1.0);
    lenX *= lenX;
    len += lenX * w;
    float ec = lE - lC;
    float ca = lC - lA;
    float lenY = max(abs(ec), abs(ca));
    lenY = 1.0 / max(lenY, 1e-6);
    float dirY = lE - lA;
    dir.y += dirY * w;
    lenY = clamp(abs(dirY) * lenY, 0.0, 1.0);
    lenY *= lenY;
    len += lenY * w;
}

vec3 FsrEasuF(vec2 ip){
    vec2 pp = ip * u_con0.xy + u_con0.zw;
    vec2 fp = floor(pp);
    pp -= fp;

    vec2 p0 = fp * u_con1.xy + u_con1.zw;
    vec2 p1 = p0 + u_con2.xy;
    vec2 p2 = p0 + u_con2.zw;
    vec2 p3 = p0 + u_con3.xy;

    vec4 bczzR = FsrEasuRF(p0);
    vec4 bczzG = FsrEasuGF(p0);
    vec4 bczzB = FsrEasuBF(p0);
    vec4 ijfeR = FsrEasuRF(p1);
    vec4 ijfeG = FsrEasuGF(p1);
    vec4 ijfeB = FsrEasuBF(p1);
    vec4 klhgR = FsrEasuRF(p2);
    vec4 klhgG = FsrEasuGF(p2);
    vec4 klhgB = FsrEasuBF(p2);
    vec4 zzonR = FsrEasuRF(p3);
    vec4 zzonG = FsrEasuGF(p3);
    vec4 zzonB = FsrEasuBF(p3);

    vec4 bczzL = bczzB * 0.5 + (bczzR * 0.5 + bczzG);
    vec4 ijfeL = ijfeB * 0.5 + (ijfeR * 0.5 + ijfeG);
    vec4 klhgL = klhgB * 0.5 + (klhgR * 0.5 + klhgG);
    vec4 zzonL = zzonB * 0.5 + (zzonR * 0.5 + zzonG);

    float bL = bczzL.x;
    float cL = bczzL.y;
    float iL = ijfeL.x;
    float jL = ijfeL.y;
    float fL = ijfeL.z;
    float eL = ijfeL.w;
    float kL = klhgL.x;
    float lL = klhgL.y;
    float hL = klhgL.z;
    float gL = klhgL.w;
    float oL = zzonL.z;
    float nL = zzonL.w;

    vec2 dir = vec2(0.0);
    float len = 0.0;
    FsrEasuSetF(dir, len, pp, true,  false, false, false, bL, eL, fL, gL, jL);
    FsrEasuSetF(dir, len, pp, false, true,  false, false, cL, fL, gL, hL, kL);
    FsrEasuSetF(dir, len, pp, false, false, true,  false, fL, iL, jL, kL, nL);
    FsrEasuSetF(dir, len, pp, false, false, false, true,  gL, jL, kL, lL, oL);

    vec2 dir2 = dir * dir;
    float dirR = dir2.x + dir2.y;
    bool zro = dirR < (1.0 / 32768.0);
    dirR = inversesqrt(max(dirR, 1e-12));
    dirR = zro ? 1.0 : dirR;
    dir.x = zro ? 1.0 : dir.x;
    dir *= vec2(dirR);
    len = len * 0.5;
    len *= len;
    float stretch = (dir.x * dir.x + dir.y * dir.y) *
                    (1.0 / max(abs(dir.x), abs(dir.y)));
    vec2 len2 = vec2(1.0 + (stretch - 1.0) * len, 1.0 + (-0.5) * len);
    float lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
    float clp = 1.0 / lob;

    vec3 min4 = min(min(vec3(ijfeR.z, ijfeG.z, ijfeB.z),
                        vec3(klhgR.w, klhgG.w, klhgB.w)),
                    vec3(ijfeR.y, ijfeG.y, ijfeB.y));
    min4 = min(min4, vec3(klhgR.x, klhgG.x, klhgB.x));
    vec3 max4 = max(max(vec3(ijfeR.z, ijfeG.z, ijfeB.z),
                        vec3(klhgR.w, klhgG.w, klhgB.w)),
                    vec3(ijfeR.y, ijfeG.y, ijfeB.y));
    max4 = max(max4, vec3(klhgR.x, klhgG.x, klhgB.x));

    vec3 aC = vec3(0.0);
    float aW = 0.0;
    FsrEasuTapF(aC, aW, vec2( 0.0,-1.0)-pp, dir, len2, lob, clp, vec3(bczzR.x, bczzG.x, bczzB.x));
    FsrEasuTapF(aC, aW, vec2( 1.0,-1.0)-pp, dir, len2, lob, clp, vec3(bczzR.y, bczzG.y, bczzB.y));
    FsrEasuTapF(aC, aW, vec2(-1.0, 1.0)-pp, dir, len2, lob, clp, vec3(ijfeR.x, ijfeG.x, ijfeB.x));
    FsrEasuTapF(aC, aW, vec2( 0.0, 1.0)-pp, dir, len2, lob, clp, vec3(ijfeR.y, ijfeG.y, ijfeB.y));
    FsrEasuTapF(aC, aW, vec2( 0.0, 0.0)-pp, dir, len2, lob, clp, vec3(ijfeR.z, ijfeG.z, ijfeB.z));
    FsrEasuTapF(aC, aW, vec2(-1.0, 0.0)-pp, dir, len2, lob, clp, vec3(ijfeR.w, ijfeG.w, ijfeB.w));
    FsrEasuTapF(aC, aW, vec2( 1.0, 1.0)-pp, dir, len2, lob, clp, vec3(klhgR.x, klhgG.x, klhgB.x));
    FsrEasuTapF(aC, aW, vec2( 2.0, 1.0)-pp, dir, len2, lob, clp, vec3(klhgR.y, klhgG.y, klhgB.y));
    FsrEasuTapF(aC, aW, vec2( 2.0, 0.0)-pp, dir, len2, lob, clp, vec3(klhgR.z, klhgG.z, klhgB.z));
    FsrEasuTapF(aC, aW, vec2( 1.0, 0.0)-pp, dir, len2, lob, clp, vec3(klhgR.w, klhgG.w, klhgB.w));
    FsrEasuTapF(aC, aW, vec2( 1.0, 2.0)-pp, dir, len2, lob, clp, vec3(zzonR.z, zzonG.z, zzonB.z));
    FsrEasuTapF(aC, aW, vec2( 0.0, 2.0)-pp, dir, len2, lob, clp, vec3(zzonR.w, zzonG.w, zzonB.w));

    return min(max4, max(min4, aC * vec3(1.0 / max(aW, 1e-6))));
}

// ==========================================================================
// Catmull-Rom bicubic (16 taps via texelFetch)
// ==========================================================================
float _cubic(float x){
    x = abs(x);
    if(x < 1.0)  return (1.5 * x - 2.5) * x * x + 1.0;
    if(x < 2.0)  return ((-0.5 * x + 2.5) * x - 4.0) * x + 2.0;
    return 0.0;
}

vec3 _bicubic(vec2 coord){
    vec2 base = floor(coord);
    vec2 f = coord - base;
    vec3 sum = vec3(0.0);
    for(int j = -1; j <= 2; j++){
        int yy = clamp(int(base.y) + j, 0, int(u_srcSize.y) - 1);
        float wy = _cubic(f.y - float(j));
        for(int i = -1; i <= 2; i++){
            int xx = clamp(int(base.x) + i, 0, int(u_srcSize.x) - 1);
            float wx = _cubic(f.x - float(i));
            sum += texelFetch(u_src, ivec2(xx, yy), 0).rgb * (wx * wy);
        }
    }
    return sum;
}

void main(){
    vec2 ipInt = floor(gl_FragCoord.xy);
    vec2 ipTL = vec2(ipInt.x, u_outSize.y - 1.0 - ipInt.y);
    vec2 ipLocal = ipTL - u_dstRect.xy;

    if(ipLocal.x < 0.0 || ipLocal.y < 0.0 ||
       ipLocal.x >= u_dstRect.z || ipLocal.y >= u_dstRect.w){
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    if(u_mode == 0){
        fragColor = vec4(FsrEasuF(ipLocal), 1.0);
        return;
    }

    vec2 inCoord = u_srcRect.xy + (ipLocal + 0.5) * (u_srcRect.zw / u_dstRect.zw) - 0.5;

    if(u_mode == 1 || u_mode == 2){
        ivec2 t = ivec2(floor(inCoord + 0.5));
        t = clamp(t, ivec2(0), ivec2(u_srcSize) - 1);
        fragColor = texelFetch(u_src, t, 0);
    } else {
        fragColor = vec4(_bicubic(inCoord), 1.0);
    }
}
"""

# RCAS (Robust Contrast Adaptive Sharpening) — applied as a post pass.
RCAS_FRAG_SRC = """
#version 400 core
out vec4 fragColor;
uniform sampler2D u_src;
uniform float u_rcas;   // exp2(-stops)

const float FSR_RCAS_LIMIT = 0.25 - (1.0 / 16.0);

vec3 _load(ivec2 p){ return texelFetch(u_src, p, 0).rgb; }

void main(){
    ivec2 ip = ivec2(floor(gl_FragCoord.xy));
    vec3 b = _load(ip + ivec2(0, -1));
    vec3 d = _load(ip + ivec2(-1, 0));
    vec3 e = _load(ip);
    vec3 f = _load(ip + ivec2(1, 0));
    vec3 h = _load(ip + ivec2(0, 1));

    float bL = b.b * 0.5 + (b.r * 0.5 + b.g);
    float dL = d.b * 0.5 + (d.r * 0.5 + d.g);
    float eL = e.b * 0.5 + (e.r * 0.5 + e.g);
    float fL = f.b * 0.5 + (f.r * 0.5 + f.g);
    float hL = h.b * 0.5 + (h.r * 0.5 + h.g);

    float mn4R = min(min(b.r, d.r), min(f.r, h.r));
    float mn4G = min(min(b.g, d.g), min(f.g, h.g));
    float mn4B = min(min(b.b, d.b), min(f.b, h.b));
    float mx4R = max(max(b.r, d.r), max(f.r, h.r));
    float mx4G = max(max(b.g, d.g), max(f.g, h.g));
    float mx4B = max(max(b.b, d.b), max(f.b, h.b));

    float hitMinR = min(mn4R, e.r) / max(4.0 * mx4R, 1e-6);
    float hitMinG = min(mn4G, e.g) / max(4.0 * mx4G, 1e-6);
    float hitMinB = min(mn4B, e.b) / max(4.0 * mx4B, 1e-6);
    float hitMaxR = (1.0 - max(mx4R, e.r)) / (4.0 * mn4R - 4.0 + 1e-6);
    float hitMaxG = (1.0 - max(mx4G, e.g)) / (4.0 * mn4G - 4.0 + 1e-6);
    float hitMaxB = (1.0 - max(mx4B, e.b)) / (4.0 * mn4B - 4.0 + 1e-6);

    float lobeR = max(-hitMinR, hitMaxR);
    float lobeG = max(-hitMinG, hitMaxG);
    float lobeB = max(-hitMinB, hitMaxB);
    float lobe = max(-FSR_RCAS_LIMIT, min(max(lobeR, max(lobeG, lobeB)), 0.0)) * u_rcas;

    float rcpL = 1.0 / (4.0 * lobe + 1.0);
    float r = (lobe * (b.r + d.r + h.r + f.r) + e.r) * rcpL;
    float g = (lobe * (b.g + d.g + h.g + f.g) + e.g) * rcpL;
    float bb = (lobe * (b.b + d.b + h.b + f.b) + e.b) * rcpL;
    fragColor = vec4(r, g, bb, 1.0);
}
"""

# Simple passthrough blit.
BLIT_FRAG_SRC = """
#version 400 core
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_src;
void main(){
    fragColor = texture(u_src, v_uv);
}
"""

# Frame generation: motion-compensated interpolation (Lucas-Kanade single
# iteration optical flow) between the previous and current scaled frames.
FG_FRAG_SRC = """
#version 400 core
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_cur;   // current scaled frame
uniform sampler2D u_prev;  // previous scaled frame
uniform vec2  u_size;      // output size (texels)
uniform float u_fgPhase;   // interpolation phase 0..1

float _luma(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }

void main(){
    vec2 texel = 1.0 / u_size;
    vec3 cur = texture(u_cur, v_uv).rgb;
    vec3 prv = texture(u_prev, v_uv).rgb;

    // Spatial gradient of previous frame + temporal difference.
    float gx = _luma(texture(u_prev, v_uv + vec2( texel.x, 0.0)).rgb)
             - _luma(texture(u_prev, v_uv + vec2(-texel.x, 0.0)).rgb);
    float gy = _luma(texture(u_prev, v_uv + vec2(0.0,  texel.y)).rgb)
             - _luma(texture(u_prev, v_uv + vec2(0.0, -texel.y)).rgb);
    float dt = _luma(cur) - _luma(prv);

    // Lucas-Kanade single-step optical flow.
    float g2 = gx * gx + gy * gy + 1e-4;
    vec2 flow = -vec2(gx, gy) * (dt / g2);

    // Clamp motion vector magnitude.
    float fl = length(flow);
    float maxFlow = 8.0;
    if(fl > maxFlow) flow *= maxFlow / fl;

    // Warp both frames toward the midpoint at phase.
    vec3 wCur = texture(u_cur,  v_uv - flow * (1.0 - u_fgPhase)).rgb;
    vec3 wPrv = texture(u_prev, v_uv + flow * u_fgPhase).rgb;
    vec3 interpolated = mix(wPrv, wCur, u_fgPhase);

    fragColor = vec4(interpolated, 1.0);
}
"""

# OSD (text atlas) shaders.
OSD_VERT_SRC = """
#version 400 core
layout(location = 0) in vec2 a_pos;    // top-left origin, pixels
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec4 a_color;
uniform vec2 u_screenSize;
out vec2 v_uv;
out vec4 v_color;
void main(){
    float x = (a_pos.x / u_screenSize.x) * 2.0 - 1.0;
    float y = 1.0 - (a_pos.y / u_screenSize.y) * 2.0;
    v_uv = a_uv;
    v_color = a_color;
    gl_Position = vec4(x, y, 0.0, 1.0);
}
"""

OSD_FRAG_SRC = """
#version 400 core
in vec2 v_uv;
in vec4 v_color;
out vec4 fragColor;
uniform sampler2D u_atlas;
uniform int u_solid;
void main(){
    if(u_solid == 1){
        fragColor = v_color;
        return;
    }
    float a = texture(u_atlas, v_uv).r;
    if(a < 0.05) discard;
    fragColor = vec4(v_color.rgb, v_color.a * a);
}
"""

# ---------------------------------------------------------------------------
# Shared application state (thread-safe)
# ---------------------------------------------------------------------------
class AppState:
    """Central shared state between GUI, renderer, capture, stats and hotkey
    threads.  All reads/writes are guarded by a single RLock to keep the hot
    path allocation-free."""

    def __init__(self):
        self.lock = threading.RLock()
        self.running = threading.Event()
        self.running.set()

        # Settings (mirrored from the GUI).
        self.mode = 0                 # SCALE_MODE_IDS value
        self.sharpness = 30           # 0..100
        self.aspect = "auto"          # "auto" | "custom"
        self.custom_mult = 1.5
        self.fg_enabled = False
        self.capture_delay_ms = 0
        self.capture_target = "active"       # "fullscreen" | "active" | "window"
        self.capture_window_id = None        # X11 window id for XComposite
        self.capture_monitor = 1             # mss monitor index (1 = primary)
        self.output_monitor = 0              # GLFW monitor index (0 = primary)
        # Screen rect (x, y, w, h) currently covered by the overlay, written by
        # the renderer.  Used to refuse full-screen grabs that would capture
        # the overlay itself (mirror feedback loop).
        self.overlay_rect = None
        self.osd_enabled = True
        self.osd_show_fps = True
        self.osd_show_cpu = True
        self.osd_show_gpu = True
        self.osd_show_ram = True
        self.hotkey = DEFAULT_HOTKEY
        self.lang = "en"

        # Runtime state.
        self.scaling_active = False
        self.settings_dirty = True    # GUI sets True when settings change

        # Latest capture slot: (array, seq, timestamp).
        self.capture_lock = threading.Lock()
        self.latest_frame = None      # BGRA uint8 numpy array (h, w, 4)
        self.latest_seq = -1
        self.latest_ts = 0.0

        # Stats (updated by the OSD thread every 500 ms).
        self.stats_lock = threading.Lock()
        self.stats = {
            "capture_fps": 0.0,
            "render_fps": 0.0,
            "cpu": 0.0,
            "ram": 0.0,
            "gpu": None,
            "gpu_name": "Unknown",
            "src_size": (0, 0),
            "out_size": (0, 0),
        }

    # -- settings ----------------------------------------------------------
    def snapshot(self):
        with self.lock:
            return {
                "mode": self.mode,
                "sharpness": self.sharpness,
                "aspect": self.aspect,
                "custom_mult": self.custom_mult,
                "fg_enabled": self.fg_enabled,
                "capture_delay_ms": self.capture_delay_ms,
                "capture_target": self.capture_target,
                "capture_window_id": self.capture_window_id,
                "capture_monitor": self.capture_monitor,
                "output_monitor": self.output_monitor,
                "osd_enabled": self.osd_enabled,
                "osd_show_fps": self.osd_show_fps,
                "osd_show_cpu": self.osd_show_cpu,
                "osd_show_gpu": self.osd_show_gpu,
                "osd_show_ram": self.osd_show_ram,
                "hotkey": self.hotkey,
                "lang": self.lang,
            }

    def update(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            self.settings_dirty = True

    def consume_dirty(self):
        with self.lock:
            d = self.settings_dirty
            self.settings_dirty = False
            return d

    def toggle_scaling(self):
        with self.lock:
            self.scaling_active = not self.scaling_active
            return self.scaling_active

    # -- capture -----------------------------------------------------------
    def put_frame(self, array, seq, ts):
        with self.capture_lock:
            self.latest_frame = array
            self.latest_seq = seq
            self.latest_ts = ts

    def get_frame(self):
        with self.capture_lock:
            return self.latest_frame, self.latest_seq, self.latest_ts


# ---------------------------------------------------------------------------
# OSD statistics collector thread (sleeps 500 ms between samples)
# ---------------------------------------------------------------------------
class StatsCollector(threading.Thread):
    def __init__(self, state, gpu_monitor):
        super().__init__(name="BoostLayer-Stats", daemon=True)
        self.state = state
        self.gpu = gpu_monitor
        self._cap_count = 0
        self._cap_t0 = time.time()
        self._ren_count = 0
        self._ren_t0 = time.time()

    def bump_capture(self):
        self._cap_count += 1

    def bump_render(self):
        self._ren_count += 1

    def run(self):
        interval = 0.5
        while self.state.running.is_set():
            time.sleep(interval)
            try:
                self._sample()
            except Exception:
                # Never let the telemetry thread kill the app.
                pass

    def _sample(self):
        now = time.time()

        # FPS computed from counters accumulated in the capture/render loops.
        cap_elapsed = now - self._cap_t0
        ren_elapsed = now - self._ren_t0
        cap_fps = self._cap_count / cap_elapsed if cap_elapsed > 0 else 0.0
        ren_fps = self._ren_count / ren_elapsed if ren_elapsed > 0 else 0.0
        self._cap_count = 0
        self._ren_count = 0
        self._cap_t0 = now
        self._ren_t0 = now

        cpu = 0.0
        ram = 0.0
        if psutil is not None:
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
            except Exception:
                pass

        gpu = self.gpu.usage() if self.gpu else None

        with self.state.stats_lock:
            s = self.state.stats
            s["capture_fps"] = cap_fps
            s["render_fps"] = ren_fps
            s["cpu"] = cpu
            s["ram"] = ram
            s["gpu"] = gpu
            s["gpu_name"] = self.gpu.name if self.gpu else "Unknown"
            s["rev"] = s.get("rev", 0) + 1


# ---------------------------------------------------------------------------
# Capture thread (mss on X11 / XWayland, grim+portal fallback on Wayland)
# ---------------------------------------------------------------------------
def _decode_png(data):
    """Minimal, dependency-free PNG decoder (8-bit, non-interlaced, color
    types 0/2/3/4/6).  Returns a BGRA uint8 numpy array (h, w, 4)."""
    if not data or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _c, _f, interlace = \
                struct.unpack(">IIBBBBB", chunk)
            if interlace != 0:
                raise ValueError("interlaced PNG unsupported")
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if width is None or bit_depth != 8:
        raise ValueError("unsupported PNG")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(width * height * channels)
    prev = bytearray(stride)
    idx = 0
    for y in range(height):
        ft = raw[idx]
        idx += 1
        line = bytearray(raw[idx:idx + stride])
        idx += stride
        if ft == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ft == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line

    if channels == 4:  # RGBA -> BGRA
        bgra = np.frombuffer(bytes(out), np.uint8).reshape(height, width, 4)
        bgra[:, :, 0], bgra[:, :, 2] = \
            bgra[:, :, 2].copy(), bgra[:, :, 0].copy()
        return bgra
    if channels == 3:  # RGB -> BGRA
        rgb = np.frombuffer(bytes(out), np.uint8).reshape(height, width, 3)
        bgra = np.empty((height, width, 4), np.uint8)
        bgra[:, :, 0] = rgb[:, :, 2]
        bgra[:, :, 1] = rgb[:, :, 1]
        bgra[:, :, 2] = rgb[:, :, 0]
        bgra[:, :, 3] = 255
        return bgra
    if channels == 2:  # gray+alpha
        ga = np.frombuffer(bytes(out), np.uint8).reshape(height, width, 2)
        bgra = np.empty((height, width, 4), np.uint8)
        bgra[:, :, 0] = ga[:, :, 0]
        bgra[:, :, 1] = ga[:, :, 0]
        bgra[:, :, 2] = ga[:, :, 0]
        bgra[:, :, 3] = ga[:, :, 1]
        return bgra
    # channels == 1 (gray)
    g = np.frombuffer(bytes(out), np.uint8).reshape(height, width)
    bgra = np.empty((height, width, 4), np.uint8)
    bgra[:, :, 0] = g
    bgra[:, :, 1] = g
    bgra[:, :, 2] = g
    bgra[:, :, 3] = 255
    return bgra


# ---------------------------------------------------------------------------
# XComposite window capture (python-xlib) — captures an occluded window
# (e.g. a windowed game covered by the fullscreen overlay) without the mss
# self-capture feedback loop.
# ---------------------------------------------------------------------------
def list_windows():
    """Return [(window_id, title, width, height), ...] for visible top-level
    X11 windows, using python-xlib (no external tools)."""
    try:
        from Xlib import display, X
    except ImportError:
        return []
    try:
        d = display.Display()
    except Exception:
        return []
    root = d.screen().root
    try:
        net_name = d.intern_atom("_NET_WM_NAME")
        wm_class_atom = d.intern_atom("WM_CLASS")
        net_pid_atom = d.intern_atom("_NET_WM_PID")
    except Exception:
        net_name = None
        wm_class_atom = None
        net_pid_atom = None
    windows = []
    exe_hints = None
    try:
        children = root.query_tree().children
    except Exception:
        children = []
    for w in children:
        name = None
        try:
            name = w.get_wm_name()
        except Exception:
            name = None
        if not name and net_name is not None:
            try:
                prop = w.get_full_property(net_name, 0)
                if prop and prop.value:
                    v = prop.value
                    name = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
            except Exception:
                name = None
        if not name and wm_class_atom is not None:
            try:
                prop = w.get_full_property(wm_class_atom, 0)
                if prop and prop.value:
                    v = prop.value
                    cls = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
                    name = cls.split("\x00")[-1] or cls
            except Exception:
                name = None
        comm = None
        if net_pid_atom is not None:
            try:
                prop = w.get_full_property(net_pid_atom, 0)
                if prop and prop.value is not None:
                    v = prop.value
                    pid = int(v[0]) if isinstance(v, (list, tuple)) else int(v)
                    comm = _pid_comm(pid)
            except Exception:
                comm = None
        if not name and comm:
            name = comm
        # Wine/Proton windows often share a generic title — append the .exe
        # name so the actual game is easy to spot in the list.
        if name and comm and comm.lower().endswith(".exe") \
                and comm.lower() not in name.lower():
            name = "%s [%s]" % (name, comm)
        try:
            geo = w.get_geometry()
            attrs = w.get_attributes()
        except Exception:
            continue
        is_override = bool(attrs.override_redirect)
        if is_override:
            # Override-redirect windows (Proton/Wine games, fullscreen) have no
            # WM title — skip tiny compositor internals, keep game-sized ones
            # even if currently unmapped.
            if geo.width < 320 or geo.height < 240:
                continue
        else:
            if attrs.map_state != X.IsViewable:
                continue
            if geo.width < 60 or geo.height < 60:
                continue
        if not name:
            name = "Window %dx%d" % (geo.width, geo.height)
            # Wine/Proton virtual desktops expose an unnamed override-redirect
            # window.  Use the running .exe name(s) as a hint so the game is
            # recognisable in the list.
            if is_override:
                if exe_hints is None:
                    exe_hints = _wine_exe_names()
                if exe_hints:
                    name = "%s [%s]" % (name, ", ".join(exe_hints[:2]))
        windows.append((int(w.id), name, geo.width, geo.height))
    try:
        d.close()
    except Exception:
        pass
    windows.sort(key=lambda t: t[1].lower())
    return windows


def _mask_to_byte(mask):
    """Return the byte offset (0-based) of the lowest set bit in a channel mask."""
    if not mask:
        return 0
    m = int(mask)
    return ((m & -m).bit_length() - 1) // 8


def _pid_comm(pid):
    """Resolve a PID to its short process name (e.g. 'DP.exe')."""
    if not pid:
        return None
    try:
        with open("/proc/%d/comm" % int(pid)) as fh:
            return fh.read().strip()
    except Exception:
        return None


def active_window_id():
    """Return the currently-focused (active) X11 window id, or None."""
    try:
        from Xlib import display, X
    except ImportError:
        return None
    try:
        d = display.Display()
    except Exception:
        return None
    try:
        root = d.screen().root
        atom = d.intern_atom("_NET_ACTIVE_WINDOW")
        prop = root.get_full_property(atom, X.AnyPropertyType)
        if prop and prop.value is not None:
            v = prop.value
            if isinstance(v, (list, tuple)):
                return int(v[0]) if v else None
            return int(v)
    except Exception:
        pass
    finally:
        try:
            d.close()
        except Exception:
            pass
    return None


def _has_wm_state(win):
    try:
        prop = win.get_full_property(win.display.intern_atom("WM_STATE"), 0)
        return prop is not None
    except Exception:
        return False


def _find_client_window(win, depth=0):
    """Return the real client window below a WM frame (top-level window).
    Frames carry no WM_STATE; the client inside them does."""
    if win is None or depth > 4:
        return None
    if _has_wm_state(win):
        return win
    try:
        children = win.query_tree().children
    except Exception:
        return None
    for child in children:
        found = _find_client_window(child, depth + 1)
        if found is not None:
            return found
    return None


def select_window_by_click():
    """Grab the pointer, let the user click a window, and return its client
    window id (or None).  Right-click cancels; gives up after 15 s."""
    import select
    try:
        from Xlib import display, X
    except ImportError:
        return None
    try:
        d = display.Display()
    except Exception:
        return None
    root = d.screen().root
    child = None
    cursor = None
    try:
        # Visual feedback: crosshair cursor while picking.
        try:
            from Xlib import Xcursorfont
            font = d.open_font("cursor")
            cursor = font.create_glyph_cursor(
                font, Xcursorfont.crosshair, Xcursorfont.crosshair + 1,
                (65535, 65535, 65535), (0, 0, 0))
            root.change_attributes(cursor=cursor)
        except Exception:
            cursor = None
        root.grab_pointer(True, X.ButtonPressMask, X.GrabModeAsync,
                          X.GrabModeAsync, X.NONE, X.NONE, X.CurrentTime)
        d.sync()
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if not d.pending_events():
                select.select([d.fileno()], [], [], 0.1)
                continue
            event = d.next_event()
            if event.type != X.ButtonPress:
                continue
            if getattr(event, "detail", 1) == 3:   # right button -> cancel
                child = None
                break
            child = getattr(event, "child", None)
            if not child:
                child = root.query_pointer().child
            break
    except Exception:
        child = None
    finally:
        try:
            d.ungrab_pointer(X.CurrentTime)
        except Exception:
            pass
        if cursor is not None:
            try:
                root.change_attributes(cursor=X.NONE)
            except Exception:
                pass
        try:
            d.sync()
        except Exception:
            pass

    top = None
    try:
        if isinstance(child, int):
            from Xlib.xobject.drawable import Window
            child = Window(d.display, child, d)
        w = child
        if w is not None and getattr(w, "id", 0) not in (0, X.NONE):
            while True:
                parent = w.query_tree().parent
                if parent is None or getattr(parent, "id", 0) in (0, X.NONE):
                    break
                if parent.id == root.id:
                    top = w
                    break
                w = parent
    except Exception:
        top = None

    result = None
    if top is not None:
        client = _find_client_window(top)
        result = int((client if client is not None else top).id)
    try:
        d.close()
    except Exception:
        pass
    return result


def _wine_exe_names():
    """Sorted unique names of running Wine/Proton executables."""
    names = set()
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            comm = _pid_comm(int(entry))
            if comm and comm.lower().endswith(".exe"):
                names.add(comm)
    except Exception:
        pass
    return sorted(names)


# ---------------------------------------------------------------------------
# Fast X11 window capture (ctypes: libX11 / libXext / libXcomposite)
#
# python-xlib transfers XGetImage replies through its pure-Python socket
# layer, which costs ~60 ms for a 1080p frame.  XShmGetImage writes the pixels
# straight into shared memory (~3 ms), which is what keeps the overlay smooth.
# ---------------------------------------------------------------------------

_ZPIXMAP = 2
_ALL_PLANES = 0xFFFFFFFF

_X11_LIBS = None          # (libX11, libXext, libXcomposite, libc) or False
_X11_ERROR = [0]          # last X error code seen by the handler
_X11_PREV_HANDLER = None


class _XImageStruct(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int),
        ("bitmap_bit_order", ctypes.c_int),
        ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("bytes_per_line", ctypes.c_int),
        ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
    ]


class _XShmSegmentInfo(ctypes.Structure):
    _fields_ = [
        ("shmseg", ctypes.c_ulong),
        ("shmid", ctypes.c_int),
        ("shmaddr", ctypes.c_void_p),
        ("readOnly", ctypes.c_int),
    ]


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


class _XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("resourceid", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


_XErrorHandlerType = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                      ctypes.POINTER(_XErrorEvent))


@_XErrorHandlerType
def _x11_error_handler(dpy, event):
    """Record async X errors instead of letting Xlib abort the process."""
    try:
        _X11_ERROR[0] = event.contents.error_code
    except Exception:
        _X11_ERROR[0] = -1
    prev = _X11_PREV_HANDLER
    if prev is not None:
        try:
            return prev(dpy, event)
        except Exception:
            return 0
    return 0


def _x11_load():
    """Load and prototype the X11 libraries once.  True on success."""
    global _X11_LIBS, _X11_PREV_HANDLER
    if _X11_LIBS is not None:
        return bool(_X11_LIBS)
    try:
        import ctypes.util
        def _lib(name, fallback):
            return ctypes.CDLL(ctypes.util.find_library(name) or fallback)
        libx11 = _lib("X11", "libX11.so.6")
        libxext = _lib("Xext", "libXext.so.6")
        libxc = _lib("Xcomposite", "libXcomposite.so.1")
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6",
                           use_errno=True)
    except OSError as e:
        _log("X11 libraries unavailable: %r" % (e,))
        _X11_LIBS = False
        return False

    libx11.XOpenDisplay.restype = ctypes.c_void_p
    libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    libx11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    libx11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libx11.XSetErrorHandler.restype = ctypes.c_void_p
    libx11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    libx11.XGetWindowAttributes.restype = ctypes.c_int
    libx11.XGetWindowAttributes.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XWindowAttributes)]
    libx11.XGetImage.restype = ctypes.c_void_p
    libx11.XGetImage.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
    libx11.XDestroyImage.argtypes = [ctypes.c_void_p]
    libx11.XFreePixmap.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

    libxc.XCompositeRedirectWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
    libxc.XCompositeUnredirectWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
    libxc.XCompositeNameWindowPixmap.restype = ctypes.c_ulong
    libxc.XCompositeNameWindowPixmap.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_ulong]

    libxext.XShmQueryExtension.restype = ctypes.c_int
    libxext.XShmQueryExtension.argtypes = [ctypes.c_void_p]
    libxext.XShmCreateImage.restype = ctypes.c_void_p
    libxext.XShmCreateImage.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
        ctypes.c_void_p, ctypes.POINTER(_XShmSegmentInfo),
        ctypes.c_uint, ctypes.c_uint]
    libxext.XShmAttach.restype = ctypes.c_int
    libxext.XShmAttach.argtypes = [ctypes.c_void_p,
                                   ctypes.POINTER(_XShmSegmentInfo)]
    libxext.XShmDetach.restype = ctypes.c_int
    libxext.XShmDetach.argtypes = [ctypes.c_void_p,
                                   ctypes.POINTER(_XShmSegmentInfo)]
    libxext.XShmGetImage.restype = ctypes.c_int
    libxext.XShmGetImage.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, ctypes.c_ulong]

    libc.shmget.restype = ctypes.c_int
    libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
    libc.shmat.restype = ctypes.c_void_p
    libc.shmat.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    libc.shmdt.argtypes = [ctypes.c_void_p]
    libc.shmctl.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]

    prev = libx11.XSetErrorHandler(
        ctypes.cast(_x11_error_handler, ctypes.c_void_p))
    if prev:
        _X11_PREV_HANDLER = ctypes.cast(prev, _XErrorHandlerType)

    _X11_LIBS = (libx11, libxext, libxc, libc)
    return True


class XCompositeCapture:
    """Capture a specific X11 window through the Composite extension.

    XCompositeRedirectWindow keeps the window's content in an off-screen
    buffer, so it can be read even when the always-on-top overlay covers it.
    Pixels are pulled with MIT-SHM (XShmGetImage) and converted in place into
    a reused BGRA buffer, so steady-state capture allocates nothing."""

    def __init__(self, window_id):
        self.window_id = int(window_id)
        self._ok = False
        self._dpy = None
        self._pixmap = 0
        self._shm_img = None
        self._shm = None
        self._shm_id = -1
        self._shm_addr = None
        self._shm_size = 0
        self._shm_bpl = 0
        self._shm_ok = False
        self._w = 0
        self._h = 0
        self._out = None
        self._bpp = 4
        self._r_byte = 2
        self._g_byte = 1
        self._b_byte = 0
        self._fast = True

        if not _x11_load():
            return
        libx11 = _X11_LIBS[0]
        try:
            dpy = libx11.XOpenDisplay(None)
        except Exception:
            dpy = None
        if not dpy:
            _log("XComposite: cannot open X display")
            return
        self._dpy = dpy
        if not self._redirect():
            self.release()

    # -- setup ------------------------------------------------------------
    def _redirect(self):
        libx11, _xext, libxc, _libc = _X11_LIBS
        _X11_ERROR[0] = 0
        try:
            libxc.XCompositeRedirectWindow(self._dpy, self.window_id, 0)
            libx11.XSync(self._dpy, 0)
        except Exception as e:
            _log("XComposite redirect failed for %d: %r"
                 % (self.window_id, e))
            return False
        if _X11_ERROR[0]:
            _log("XComposite redirect refused for window %d (X error %d)"
                 % (self.window_id, _X11_ERROR[0]))
            return False
        attrs = _XWindowAttributes()
        _X11_ERROR[0] = 0
        if not libx11.XGetWindowAttributes(self._dpy, self.window_id,
                                           ctypes.byref(attrs)):
            return False
        if attrs.width <= 0 or attrs.height <= 0:
            return False
        self._w, self._h = int(attrs.width), int(attrs.height)
        if not self._make_target():
            return False
        self._ok = True
        return True

    def _make_target(self):
        """(Re)name the window pixmap and (re)allocate the capture buffers."""
        libx11, _xext, libxc, _libc = _X11_LIBS
        self._free_pixmap()
        self._free_shm()
        _X11_ERROR[0] = 0
        pixmap = libxc.XCompositeNameWindowPixmap(self._dpy, self.window_id)
        if _X11_ERROR[0] or not pixmap:
            return False
        self._pixmap = int(pixmap)
        self._out = np.empty((self._h, self._w, 4), dtype=np.uint8)
        self._setup_shm()
        return True

    def _setup_shm(self):
        libx11, libxext, _libxc, libc = _X11_LIBS
        try:
            if not libxext.XShmQueryExtension(self._dpy):
                return False
            attrs = _XWindowAttributes()
            _X11_ERROR[0] = 0
            if not libx11.XGetWindowAttributes(self._dpy, self.window_id,
                                               ctypes.byref(attrs)):
                return False
            shm = _XShmSegmentInfo()
            img = libxext.XShmCreateImage(
                self._dpy, attrs.visual, attrs.depth, _ZPIXMAP, None,
                ctypes.byref(shm), self._w, self._h)
            if not img:
                return False
            xi = ctypes.cast(img, ctypes.POINTER(_XImageStruct)).contents
            size = int(xi.bytes_per_line) * int(xi.height)
            if size <= 0:
                libx11.XDestroyImage(img)
                return False
            shmid = libc.shmget(0, size, 0o600 | 0o1000)   # IPC_PRIVATE|CREAT
            if shmid < 0:
                libx11.XDestroyImage(img)
                return False
            addr = libc.shmat(shmid, None, 0)
            if not addr or addr == ctypes.c_void_p(-1).value:
                libc.shmctl(shmid, 0, None)
                libx11.XDestroyImage(img)
                return False
            shm.shmid = shmid
            shm.shmaddr = addr
            shm.readOnly = 0
            xi.data = addr
            _X11_ERROR[0] = 0
            if not libxext.XShmAttach(self._dpy, ctypes.byref(shm)):
                libc.shmdt(addr)
                libc.shmctl(shmid, 0, None)
                libx11.XDestroyImage(img)
                return False
            libx11.XSync(self._dpy, 0)
            if _X11_ERROR[0]:
                libxext.XShmDetach(self._dpy, ctypes.byref(shm))
                libc.shmdt(addr)
                libc.shmctl(shmid, 0, None)
                libx11.XDestroyImage(img)
                return False
            self._shm = shm
            self._shm_img = img
            self._shm_id = shmid
            self._shm_addr = addr
            self._shm_size = size
            self._shm_bpl = int(xi.bytes_per_line)
            self._shm_ok = True
            self._read_format(xi)
            return True
        except Exception as e:
            _log("XShm setup failed: %r" % (e,))
            return False

    def _read_format(self, xi):
        self._bpp = max(1, int(xi.bits_per_pixel) // 8)
        self._r_byte = _mask_to_byte(xi.red_mask)
        self._g_byte = _mask_to_byte(xi.green_mask)
        self._b_byte = _mask_to_byte(xi.blue_mask)
        self._fast = (self._bpp == 4 and self._r_byte == 2 and
                      self._g_byte == 1 and self._b_byte == 0)

    # -- grabbing ---------------------------------------------------------
    def grab(self):
        if not self._ok or not self._dpy:
            return None
        libx11 = _X11_LIBS[0]
        # Window resized? Then the named pixmap and the SHM image are stale.
        attrs = _XWindowAttributes()
        _X11_ERROR[0] = 0
        if not libx11.XGetWindowAttributes(self._dpy, self.window_id,
                                           ctypes.byref(attrs)):
            return None
        if attrs.width != self._w or attrs.height != self._h:
            if attrs.width <= 0 or attrs.height <= 0:
                return None
            self._w, self._h = int(attrs.width), int(attrs.height)
            if not self._make_target():
                return None
        return self._read()

    def _read(self):
        libx11, libxext, _libxc, _libc = _X11_LIBS
        if self._shm_ok:
            _X11_ERROR[0] = 0
            ok = libxext.XShmGetImage(self._dpy, self._pixmap, self._shm_img,
                                      0, 0, _ALL_PLANES)
            if ok and not _X11_ERROR[0]:
                buf = (ctypes.c_ubyte * self._shm_size).from_address(
                    self._shm_addr)
                raw = np.frombuffer(buf, dtype=np.uint8)
                return self._convert(raw, self._h, self._shm_bpl)
            # SHM stopped working (segment detached, window gone): fall back.
            _log("XShmGetImage failed, using XGetImage fallback")
            self._free_shm()
        _X11_ERROR[0] = 0
        ptr = libx11.XGetImage(self._dpy, self._pixmap, 0, 0, self._w,
                               self._h, _ALL_PLANES, _ZPIXMAP)
        if not ptr:
            return None
        try:
            xi = ctypes.cast(ptr, ctypes.POINTER(_XImageStruct)).contents
            size = int(xi.bytes_per_line) * int(xi.height)
            if size <= 0:
                return None
            self._read_format(xi)
            buf = (ctypes.c_ubyte * size).from_address(xi.data)
            raw = np.frombuffer(buf, dtype=np.uint8)
            return self._convert(raw, int(xi.height), int(xi.bytes_per_line))
        finally:
            libx11.XDestroyImage(ptr)

    def _convert(self, raw, h, bpl):
        w = self._w
        out = self._out
        if out is None or out.shape[0] != h or out.shape[1] != w:
            out = np.empty((h, w, 4), dtype=np.uint8)
            self._out = out
        bpp = self._bpp
        if bpl < w * bpp or raw.size < bpl * h:
            return None
        if self._fast:
            src = raw.reshape(h, bpl)[:, :w * 4].reshape(h, w, 4)
            np.copyto(out, src)
        else:
            src = raw.reshape(h, bpl)[:, :w * bpp].reshape(h, w, bpp)
            bb = min(self._b_byte, bpp - 1)
            gb = min(self._g_byte, bpp - 1)
            rb = min(self._r_byte, bpp - 1)
            out[:, :, 0] = src[:, :, bb]
            out[:, :, 1] = src[:, :, gb]
            out[:, :, 2] = src[:, :, rb]
        out[:, :, 3] = 255
        return out

    # -- teardown ---------------------------------------------------------
    def _free_shm(self):
        if self._shm_img is None and self._shm is None:
            return
        libx11, libxext, _libxc, libc = _X11_LIBS
        try:
            if self._shm is not None and self._dpy:
                libxext.XShmDetach(self._dpy, ctypes.byref(self._shm))
        except Exception:
            pass
        try:
            if self._shm_img is not None:
                libx11.XDestroyImage(self._shm_img)
        except Exception:
            pass
        try:
            if self._shm_addr:
                libc.shmdt(self._shm_addr)
        except Exception:
            pass
        try:
            if self._shm_id >= 0:
                libc.shmctl(self._shm_id, 0, None)   # IPC_RMID
        except Exception:
            pass
        self._shm_img = None
        self._shm = None
        self._shm_addr = None
        self._shm_id = -1
        self._shm_size = 0
        self._shm_ok = False

    def _free_pixmap(self):
        if self._pixmap and self._dpy:
            try:
                _X11_LIBS[0].XFreePixmap(self._dpy, self._pixmap)
            except Exception:
                pass
        self._pixmap = 0

    def release(self):
        self._ok = False
        self._free_shm()
        self._free_pixmap()
        if self._dpy:
            try:
                _X11_LIBS[2].XCompositeUnredirectWindow(self._dpy,
                                                        self.window_id, 0)
                _X11_LIBS[0].XSync(self._dpy, 0)
            except Exception:
                pass
            try:
                _X11_LIBS[0].XCloseDisplay(self._dpy)
            except Exception:
                pass
            self._dpy = None


class CaptureThread(threading.Thread):
    def __init__(self, state, stats_collector=None):
        super().__init__(name="BoostLayer-Capture", daemon=True)
        self.state = state
        self.stats = stats_collector
        self.display = detect_display_server()
        self._sct = None
        self._monitor = None
        self._xcomp = None
        self._active_win_id = None
        self._last_active_refresh = 0.0
        self._full_win_id = None
        self._last_full_refresh = 0.0
        self._bad_windows = set()
        self._mss_warned = False
        self._seq = 0
        self._last_window_refresh = 0.0
        self._window_region = None
        self._active_event = threading.Event()
        self._last_grim_ts = 0.0

    def _open(self):
        # mss is used for fullscreen capture; XComposite capture does not
        # require it, so the thread still runs if mss is unavailable.
        self._sct = None
        self._monitor = None
        if HAS_MSS:
            # mss 10 renamed mss.mss() to mss.MSS(); prefer the new API.
            factory = getattr(mss, "MSS", None) or mss.mss
            self._sct = factory()
            self._monitor = self._sct.monitors[1]  # primary monitor
        return True

    def _grab_frame(self):
        """Dispatch to the appropriate capture backend.

        On X11 every target ultimately captures a *window* off-screen via
        XComposite.  Grabbing the monitor while the always-on-top overlay is
        visible would capture the overlay itself, producing an endless mirror
        (duplicated panel, runaway GPU load) — so ``mss`` is only used when the
        overlay is provably not on the captured monitor.
        """
        target = self.state.capture_target
        win_id = self.state.capture_window_id

        if target == "window":
            if win_id:
                arr = self._grab_window(win_id)
                if arr is not None:
                    return arr
            return self._grab_safe_mss()

        if target == "active":
            now = time.time()
            if now - self._last_active_refresh > 0.5:
                self._last_active_refresh = now
                new_id = active_window_id()
                # Ignore BoostLayer's own windows (the GUI or the overlay),
                # otherwise we would capture ourselves and show a mirror.
                if new_id and not self._is_own_window(new_id):
                    self._active_win_id = new_id
            if self._active_win_id:
                arr = self._grab_window(self._active_win_id)
                if arr is not None:
                    return arr
                self._active_win_id = None
            # Nothing foreign has been focused yet (e.g. scaling was started
            # from the GUI): capture the topmost window on the monitor as a
            # safe stand-in instead of giving up.
            arr = self._grab_topmost()
            if arr is not None:
                return arr
            return self._grab_safe_mss()

        # "fullscreen": capture the topmost window on the selected monitor.
        arr = self._grab_topmost()
        if arr is not None:
            return arr
        if self.display == "x11":
            return self._grab_safe_mss()

        arr = self._grab_grim()
        if arr is not None:
            return arr
        return self._grab_safe_mss()

    def _grab_topmost(self):
        """Topmost window on the capture monitor (X11 only, never the overlay)."""
        if self.display != "x11":
            return None
        now = time.time()
        if not self._full_win_id or now - self._last_full_refresh > 1.0:
            self._last_full_refresh = now
            self._full_win_id = self._topmost_window_on_monitor()
        if not self._full_win_id:
            return None
        arr = self._grab_window(self._full_win_id)
        if arr is not None:
            return arr
        # Uncompositable window — never try it again.
        if len(self._bad_windows) < 64:
            self._bad_windows.add(self._full_win_id)
        self._full_win_id = None
        return None

    def _grab_window(self, win_id):
        """Capture a window via XComposite (Wayland: fall back to grim)."""
        arr = self._grab_xcomp(win_id)
        if arr is None and self.display == "wayland":
            arr = self._grab_grim()
        return arr

    # -- monitor geometry / feedback-loop protection -----------------------
    def _capture_rect(self):
        """The mss monitor rect that would be captured by full-screen mode."""
        if self._sct is None:
            return None
        try:
            mons = self._sct.monitors
            idx = max(1, min(int(self.state.capture_monitor), len(mons) - 1))
            return mons[idx]
        except Exception:
            return None

    def _overlay_covers_capture(self):
        """True when the overlay sits on the monitor full-screen mode would
        grab — i.e. when using mss would capture the overlay itself."""
        rect = self._capture_rect()
        ov = getattr(self.state, "overlay_rect", None)
        if not ov:
            return False
        if not rect:
            # No monitor geometry (typical on Wayland): a full-output grab
            # inevitably includes the visible overlay.
            return True
        try:
            rx, ry, rw, rh = rect["left"], rect["top"], rect["width"], rect["height"]
            ox, oy, ow, oh = ov
        except Exception:
            return False
        ix = max(0, min(rx + rw, ox + ow) - max(rx, ox))
        iy = max(0, min(ry + rh, oy + oh) - max(ry, oy))
        return (ix * iy) > 0

    def _grab_safe_mss(self):
        """Full-screen grab that refuses to capture the overlay itself."""
        if self._sct is None:
            return None
        if self._overlay_covers_capture():
            if not self._mss_warned:
                self._mss_warned = True
                _log("fullscreen grab skipped: overlay covers the captured "
                     "monitor (choose another window/monitor)")
            return None
        return self._grab_mss()

    def _topmost_window_on_monitor(self):
        """Topmost non-BoostLayer, non-panel window covering the capture
        monitor.  Used as the safe target for full-screen mode."""
        rect = self._capture_rect()
        if rect is None:
            return None
        try:
            from Xlib import display as _xd, X
        except ImportError:
            return None
        try:
            d = _xd.Display()
        except Exception:
            return None
        result = None
        try:
            root = d.screen().root
            try:
                children = root.query_tree().children
            except Exception:
                children = []
            pid_atom = d.intern_atom("_NET_WM_PID")
            type_atom = d.intern_atom("_NET_WM_WINDOW_TYPE")
            skip_types = {
                d.intern_atom("_NET_WM_WINDOW_TYPE_DOCK"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_DESKTOP"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_TOOLBAR"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_MENU"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_DROPDOWN_MENU"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_POPUP_MENU"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_TOOLTIP"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_NOTIFICATION"),
                d.intern_atom("_NET_WM_WINDOW_TYPE_SPLASH"),
            }
            mono_area = max(1, rect["width"] * rect["height"])
            # XQueryTree returns children bottom-to-top: walk topmost first.
            for w in reversed(children):
                if int(w.id) in self._bad_windows:
                    continue
                try:
                    if w.get_attributes().map_state != X.IsViewable:
                        continue
                    geo = w.get_geometry()
                except Exception:
                    continue
                # Direct children of root: geometry is already in root coords.
                x, y, ww, hh = geo.x, geo.y, geo.width, geo.height
                if ww < 200 or hh < 120:
                    continue
                ix = max(0, min(x + ww, rect["left"] + rect["width"]) -
                         max(x, rect["left"]))
                iy = max(0, min(y + hh, rect["top"] + rect["height"]) -
                         max(y, rect["top"]))
                if ix * iy < mono_area * 0.6:
                    continue          # too small to represent the monitor
                try:
                    prop = w.get_full_property(type_atom, 0)
                    if prop and prop.value is not None:
                        v = prop.value
                        first = int(v[0]) if isinstance(v, (list, tuple)) else int(v)
                        if first in skip_types:
                            continue
                except Exception:
                    pass
                try:
                    prop = w.get_full_property(pid_atom, 0)
                    if prop and prop.value is not None:
                        v = prop.value
                        pid = int(v[0]) if isinstance(v, (list, tuple)) else int(v)
                        if pid == os.getpid():
                            continue
                except Exception:
                    pass
                result = int(w.id)
                break
        except Exception:
            result = None
        finally:
            try:
                d.close()
            except Exception:
                pass
        return result

    @staticmethod
    def _is_own_window(wid):
        """True if the window belongs to this process (BoostLayer itself)."""
        try:
            from Xlib import display as _xd
        except ImportError:
            return False
        try:
            d = _xd.Display()
        except Exception:
            return False
        try:
            w = d.create_resource_object("window", int(wid))
            prop = w.get_full_property(d.intern_atom("_NET_WM_PID"), 0)
            if prop and prop.value is not None:
                v = prop.value
                pid = int(v[0]) if isinstance(v, (list, tuple)) else int(v)
                return pid == os.getpid()
        except Exception:
            return False
        finally:
            try:
                d.close()
            except Exception:
                pass
        return False

    def _grab_mss(self):
        mons = self._sct.monitors
        idx = max(1, min(int(self.state.capture_monitor), len(mons) - 1))
        shot = self._sct.grab(mons[idx])
        w = shot.width
        h = shot.height
        return np.frombuffer(shot.raw, dtype=np.uint8).reshape(h, w, 4)

    def _grab_xcomp(self, win_id):
        if self._xcomp is None or self._xcomp.window_id != win_id:
            if self._xcomp is not None:
                self._xcomp.release()
            self._xcomp = XCompositeCapture(win_id)
        return self._xcomp.grab()

    def _grab_grim(self):
        """Wayland-native fallback: capture the focused output via 'grim'
        (which talks to wlr-screencopy / the xdg-desktop-portal underneath)."""
        if not shutil.which("grim"):
            return None
        # grim captures the composited output, so it would include our own
        # overlay when it is on the captured monitor (mirror feedback loop).
        if self._overlay_covers_capture():
            if not self._mss_warned:
                self._mss_warned = True
                _log("grim capture skipped: overlay covers the captured output")
            return None
        # Rate-limit: grim is a one-shot screencopy, not a stream.
        now = time.time()
        if now - self._last_grim_ts < 1.0 / 15.0:
            return None
        try:
            out = subprocess.run(
                ["grim", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=2,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        if not out:
            return None
        self._last_grim_ts = now
        return _decode_png(out)

    def run(self):
        gc.disable()  # no GC pauses in the hot capture loop
        if not self._open():
            return
        try:
            while self.state.running.is_set():
                if not self.state.scaling_active:
                    self._active_event.clear()
                    time.sleep(0.05)
                    continue
                self._active_event.set()
                arr = None
                try:
                    arr = self._grab_frame()
                except Exception:
                    arr = None
                if arr is None:
                    time.sleep(0.02)
                    continue
                self._seq += 1
                self.state.put_frame(arr, self._seq, time.time())
                if self.stats is not None:
                    self.stats.bump_capture()
                delay = self.state.capture_delay_ms
                if delay > 0:
                    time.sleep(delay / 1000.0)
        finally:
            if self._xcomp is not None:
                self._xcomp.release()
            if self._sct is not None:
                try:
                    self._sct.close()
                except Exception:
                    pass
            gc.enable()


# ---------------------------------------------------------------------------
# Renderer helpers (pure functions, allocation-light)
# ---------------------------------------------------------------------------
def compute_rects(mode, aspect, custom_mult, in_w, in_h, out_w, out_h):
    """Return (src_rect, dst_rect, scale) tuples (x, y, w, h)."""
    if in_w <= 0 or in_h <= 0 or out_w <= 0 or out_h <= 0:
        return (0, 0, in_w, in_h), (0, 0, out_w, out_h), 1.0

    if mode == 1:  # Integer scaling
        scale = float(max(1, int(min(out_w / in_w, out_h / in_h))))
    elif aspect == "custom":
        scale = max(0.1, float(custom_mult))
    else:  # auto aspect ratio (fit)
        scale = min(out_w / in_w, out_h / in_h)

    scaled_w = in_w * scale
    scaled_h = in_h * scale

    if scaled_w <= out_w + 1e-3 and scaled_h <= out_h + 1e-3:
        dw = max(1, int(round(scaled_w)))
        dh = max(1, int(round(scaled_h)))
        ox = (out_w - dw) // 2
        oy = (out_h - dh) // 2
        return (0, 0, in_w, in_h), (ox, oy, dw, dh), scale

    crop_w = out_w / scale
    crop_h = out_h / scale
    sx = (in_w - crop_w) / 2.0
    sy = (in_h - crop_h) / 2.0
    return (sx, sy, crop_w, crop_h), (0, 0, out_w, out_h), scale


def compute_fsr_cons(src_rect, in_size, dst_rect):
    """Compute the four EASU constant vectors (FsrEasuConOffset)."""
    ivw, ivh = src_rect[2], src_rect[3]
    isw, ish = in_size
    osw, osh = float(dst_rect[2]), float(dst_rect[3])
    ox, oy = src_rect[0], src_rect[1]
    con0 = [ivw / osw, ivh / osh,
            0.5 * ivw / osw - 0.5 + ox,
            0.5 * ivh / osh - 0.5 + oy]
    con1 = [1.0 / isw, 1.0 / ish, 1.0 / isw, -1.0 / ish]
    con2 = [-1.0 / isw, 2.0 / ish, 1.0 / isw, 2.0 / ish]
    con3 = [0.0, 4.0 / ish, 0.0, 0.0]
    return con0, con1, con2, con3


def sharpness_to_rcas(sharpness):
    """Convert 0..100 slider to an RCAS strength (exp2(-stops)); None = off."""
    if sharpness <= 0:
        return None
    stops = 2.0 * (1.0 - sharpness / 100.0)
    return 2.0 ** (-stops)


def compile_program(vs_src, fs_src):
    """Compile and link a GL program, raising with the info log on failure."""
    def _shader(stage, src):
        sh = gl.glCreateShader(stage)
        gl.glShaderSource(sh, src)
        gl.glCompileShader(sh)
        if not gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(sh).decode("utf-8", "replace")
            raise RuntimeError("Shader compile error:\n" + log)
        return sh

    vs = _shader(gl.GL_VERTEX_SHADER, vs_src)
    fs = _shader(gl.GL_FRAGMENT_SHADER, fs_src)
    prog = gl.glCreateProgram()
    gl.glAttachShader(prog, vs)
    gl.glAttachShader(prog, fs)
    gl.glLinkProgram(prog)
    if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
        log = gl.glGetProgramInfoLog(prog).decode("utf-8", "replace")
        raise RuntimeError("Program link error:\n" + log)
    gl.glDeleteShader(vs)
    gl.glDeleteShader(fs)
    return prog


# ---------------------------------------------------------------------------
# GL renderer thread
# ---------------------------------------------------------------------------
class GLRenderer(threading.Thread):
    def __init__(self, state, stats_collector):
        super().__init__(name="BoostLayer-Renderer", daemon=True)
        self.state = state
        self.stats = stats_collector
        self.display = detect_display_server()

        # GL objects (created on the render thread).
        self._win = None
        self._monitor = None
        self._monitor_idx = None
        self._windowed_size = (1280, 720)

        self._prog = {}
        self._fullscreen_vao = None

        # Input texture.
        self._input_tex = None
        self._input_w = 0
        self._input_h = 0

        # Output textures + FBOs.
        self._out_w = 0
        self._out_h = 0
        self._tex_final = [None, None]
        self._fbo_final = [None, None]
        self._tex_work = None
        self._fbo_work = None
        self._cur = 0
        self._prev = 1
        self._have_prev = False
        self._cur_ts = 0.0
        self._prev_ts = 0.0
        self._last_seq = -1
        self._loc_cache = {}

        # Cached settings / geometry.
        self._cfg = None
        self._src_rect = (0, 0, 0, 0)
        self._dst_rect = (0, 0, 0, 0)
        self._scale = 1.0
        self._cons = None
        self._rcas = None

        # OSD.
        self._osd_vao = None
        self._osd_vbo = None
        self._atlas_tex = None
        self._char_uv = {}
        self._atlas_size = (0, 0)
        self._osd_key = None
        self._osd_data = None

        self._was_active = False
        self._x11_win_id = 0
        self._last_raise = 0.0

    # ======================================================================
    # GLFW + GL initialisation
    # ======================================================================
    def _init_gl(self):
        if not glfw.init():
            raise RuntimeError("glfw.init() failed")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 0)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        glfw.window_hint(glfw.AUTO_ICONIFY, False)
        glfw.window_hint(glfw.FLOATING, True)
        glfw.window_hint(glfw.DECORATED, False)
        glfw.window_hint(glfw.VISIBLE, False)
        glfw.window_hint(glfw.RESIZABLE, False)

        monitors = glfw.get_monitors()
        idx = max(0, min(self.state.output_monitor, len(monitors) - 1))
        self._monitor_idx = idx
        self._monitor = monitors[idx]
        mode = glfw.get_video_mode(self._monitor)
        self._windowed_size = (mode.size.width, mode.size.height)
        self._win = glfw.create_window(mode.size.width, mode.size.height,
                                       APP_NAME, None, None)
        if not self._win:
            glfw.terminate()
            raise RuntimeError("glfw.create_window() failed")
        # Borderless full-screen overlay positioned on the selected monitor
        # (not blindly at (0,0), which breaks on multi-monitor layouts).
        mx, my = glfw.get_monitor_pos(self._monitor)
        glfw.set_window_pos(self._win, mx, my)
        self.state.overlay_rect = (int(mx), int(my),
                                   int(mode.size.width), int(mode.size.height))
        glfw.make_context_current(self._win)
        glfw.swap_interval(1)
        self._make_click_through()

        # Core GL state.
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)

        self._prog["scale"] = compile_program(VERT_SRC, SCALE_FRAG_SRC)
        self._prog["rcas"] = compile_program(VERT_SRC, RCAS_FRAG_SRC)
        self._prog["blit"] = compile_program(VERT_SRC, BLIT_FRAG_SRC)
        self._prog["fg"] = compile_program(VERT_SRC, FG_FRAG_SRC)
        self._prog["osd"] = compile_program(OSD_VERT_SRC, OSD_FRAG_SRC)

        self._fullscreen_vao = gl.glGenVertexArrays(1)

        self._build_osd_atlas()
        self._create_osd_geometry()

    # ======================================================================
    # Textures / FBOs
    # ======================================================================
    def _new_texture(self, filt):
        tid = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        return tid

    def _ensure_input(self, w, h):
        if self._input_tex is not None and self._input_w == w and self._input_h == h:
            return
        if self._input_tex is not None:
            gl.glDeleteTextures([self._input_tex])
        self._input_tex = self._new_texture(gl.GL_NEAREST)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._input_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                        gl.GL_BGRA, gl.GL_UNSIGNED_BYTE, None)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self._input_w, self._input_h = w, h

    def _create_out_texture(self, w, h):
        tid = self._new_texture(gl.GL_LINEAR)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, tid, 0)
        gl.glDrawBuffers([gl.GL_COLOR_ATTACHMENT0])
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        return tid, fbo

    def _ensure_output(self, w, h):
        if self._out_w == w and self._out_h == h and self._tex_final[0] is not None:
            return
        self._out_w, self._out_h = w, h
        for i in range(2):
            if self._tex_final[i] is not None:
                gl.glDeleteTextures([self._tex_final[i]])
                gl.glDeleteFramebuffers([self._fbo_final[i]])
            self._tex_final[i], self._fbo_final[i] = self._create_out_texture(w, h)
        if self._tex_work is not None:
            gl.glDeleteTextures([self._tex_work])
            gl.glDeleteFramebuffers([self._fbo_work])
        self._tex_work, self._fbo_work = self._create_out_texture(w, h)

    # ======================================================================
    # OSD font atlas
    # ======================================================================
    def _build_osd_atlas(self):
        chars = sorted(FONT_5X7.keys())
        cols = 16
        cell_w, cell_h = 5, 7
        rows = (len(chars) + cols - 1) // cols
        atlas_w = cols * cell_w
        atlas_h = rows * cell_h
        data = np.zeros((atlas_h, atlas_w), dtype=np.uint8)
        for idx, ch in enumerate(chars):
            col = idx % cols
            row = idx // cols
            ox = col * cell_w
            oy = row * cell_h
            glyph = FONT_5X7[ch]
            for gy in range(7):
                line = glyph[gy]
                for gx in range(5):
                    if line[gx] == "#":
                        data[oy + gy, ox + gx] = 255
            u0 = ox / atlas_w
            v0 = oy / atlas_h
            u1 = (ox + cell_w) / atlas_w
            v1 = (oy + cell_h) / atlas_h
            self._char_uv[ch] = (u0, v0, u1, v1)
        # Missing glyphs render as a blank space.
        self._char_uv.setdefault(" ", (0.0, 0.0, 0.0, 0.0))

        self._atlas_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._atlas_tex)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R8, atlas_w, atlas_h, 0,
                        gl.GL_RED, gl.GL_UNSIGNED_BYTE, data)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self._atlas_size = (atlas_w, atlas_h)

    def _create_osd_geometry(self):
        self._osd_vao = gl.glGenVertexArrays(1)
        self._osd_vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self._osd_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._osd_vbo)
        stride = 8 * 4
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(8))
        gl.glEnableVertexAttribArray(2)
        gl.glVertexAttribPointer(2, 4, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(16))
        gl.glBindVertexArray(0)

    # ======================================================================
    # Main loop
    # ======================================================================
    def run(self):
        if not HAS_GL:
            print("[BoostLayer] OpenGL/GLFW unavailable; renderer disabled.")
            return
        try:
            self._init_gl()
        except Exception as e:
            print("[BoostLayer] Renderer init failed:", e)
            _log("renderer init failed: %r" % (e,))
            glfw.terminate()
            return
        try:
            self._loop()
        finally:
            self._cleanup()

    def _apply_active(self, active):
        # The window is already a borderless full-screen overlay; simply show
        # or hide it. No exclusive-fullscreen switch, so the target game is
        # never kicked out of its own fullscreen mode.
        if active:
            glfw.show_window(self._win)
            # Keep clicks going to the game/desktop, not to the overlay.
            self._make_click_through()
            # Raise without stealing input focus: focusing the overlay would
            # both annoy the player and make "active window" capture pick the
            # overlay instead of the game.
            self._raise_overlay()
        else:
            glfw.hide_window(self._win)

    def _make_click_through(self):
        """Make the overlay input-transparent (X11 SHAPE input region).

        Without this, the always-on-top full-screen window would swallow every
        click and keypress, so the desktop and the game would seem frozen."""
        if self.display != "x11":
            return
        try:
            from Xlib import display as _xdisplay, X
            from Xlib.ext import shape
            if not self._x11_win_id:
                self._x11_win_id = int(glfw.get_x11_window(self._win) or 0)
            wid = self._x11_win_id
            if not wid:
                return
            d = _xdisplay.Display()
            try:
                d.query_extension("SHAPE")
                w = d.create_resource_object("window", wid)
                # Empty input region: all input passes through to the window
                # below the overlay.
                w.shape_rectangles(shape.SO.Set, shape.SK.Input,
                                   X.Unsorted, 0, 0, [])
                d.sync()
            finally:
                d.close()
        except Exception as e:
            _log("overlay: click-through unavailable: %r" % (e,))

    def _raise_overlay(self):
        """Keep the overlay above the game without stealing input focus.

        ``raise_window`` alone is ignored by some WMs when a fullscreen game
        re-stacks itself, so every second we also re-assert _NET_WM_STATE_ABOVE
        through an EWMH client message."""
        if self.display != "x11":
            return
        self._last_raise = time.time()
        try:
            if not self._x11_win_id:
                self._x11_win_id = int(glfw.get_x11_window(self._win) or 0)
            wid = self._x11_win_id
            if not wid:
                return
            from Xlib import display as _xdisplay, X, protocol
            d = _xdisplay.Display()
            try:
                w = d.create_resource_object("window", wid)
                root = d.screen().root
                state_atom = d.intern_atom("_NET_WM_STATE")
                above_atom = d.intern_atom("_NET_WM_STATE_ABOVE")
                ev = protocol.event.ClientMessage(
                    window=w, client_type=state_atom,
                    data=(32, [1, above_atom, 0, 1, 0]))
                root.send_event(
                    ev, event_mask=(X.SubstructureRedirectMask |
                                    X.SubstructureNotifyMask))
                w.raise_window()
                d.flush()
            finally:
                d.close()
        except Exception:
            pass

    def _sync_output_monitor(self):
        """Reposition/resize the overlay if the output monitor changed."""
        try:
            monitors = glfw.get_monitors()
        except Exception:
            return
        idx = max(0, min(int(self.state.output_monitor), len(monitors) - 1))
        if idx == self._monitor_idx:
            return
        self._monitor_idx = idx
        self._monitor = monitors[idx]
        mode = glfw.get_video_mode(self._monitor)
        mx, my = glfw.get_monitor_pos(self._monitor)
        glfw.set_window_size(self._win, mode.size.width, mode.size.height)
        glfw.set_window_pos(self._win, mx, my)
        self.state.overlay_rect = (int(mx), int(my),
                                   int(mode.size.width), int(mode.size.height))
        self._windowed_size = (mode.size.width, mode.size.height)

    def _loop(self):
        gc.disable()
        while self.state.running.is_set():
            glfw.poll_events()
            if glfw.window_should_close(self._win):
                self.state.running.clear()
                break

            self._sync_output_monitor()

            active = self.state.scaling_active
            if active != self._was_active:
                self._apply_active(active)
                self._was_active = active

            if not active:
                time.sleep(0.02)
                continue

            # Re-assert always-on-top periodically (some WMs drop the hint
            # when a fullscreen game restacks itself) — no focus stealing.
            if time.time() - self._last_raise > 1.0:
                self._raise_overlay()

            self._render_frame()

    def _render_frame(self):
        frame, seq, ts = self.state.get_frame()
        if frame is None:
            glfw.swap_buffers(self._win)
            return

        fb_w, fb_h = glfw.get_framebuffer_size(self._win)
        if fb_w <= 0 or fb_h <= 0:
            return
        self._ensure_output(fb_w, fb_h)

        new_frame = seq != self._last_seq
        if new_frame:
            self._last_seq = seq
            self._process_capture(frame, ts)

        if self._have_prev and self._cfg is not None:
            self._present()
        self._draw_osd()

        glfw.swap_buffers(self._win)
        self.stats.bump_render()

    def _process_capture(self, frame, ts):
        h, w = frame.shape[0], frame.shape[1]
        self._ensure_input(w, h)

        # Upload (glTexSubImage2D — no texture reallocation).
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._input_tex)
        gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h,
                           gl.GL_BGRA, gl.GL_UNSIGNED_BYTE, frame)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        # Refresh settings when dirty or when source size changed.
        cfg = self._cfg
        if cfg is None or self.state.consume_dirty() or \
           w != cfg.get("_src_w", 0) or h != cfg.get("_src_h", 0):
            cfg = self.state.snapshot()
            cfg["_src_w"] = w
            cfg["_src_h"] = h
            self._cfg = cfg
            self._recompute_geometry(cfg, w, h)

        # Swap FG ping-pong and render the scaled frame.
        self._prev, self._cur = self._cur, self._prev
        self._prev_ts = self._cur_ts
        self._cur_ts = ts
        if not self._have_prev:
            self._have_prev = True

        self._render_scale(w, h)

    def _recompute_geometry(self, cfg, in_w, in_h):
        out_w, out_h = self._out_w, self._out_h
        src, dst, scale = compute_rects(cfg["mode"], cfg["aspect"],
                                        cfg["custom_mult"],
                                        in_w, in_h, out_w, out_h)
        self._src_rect = src
        self._dst_rect = dst
        self._scale = scale
        self._cons = compute_fsr_cons(src, (in_w, in_h), dst)
        self._rcas = sharpness_to_rcas(cfg["sharpness"])

    def _render_scale(self, in_w, in_h):
        p = self._prog["scale"]
        gl.glUseProgram(p)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_final[self._cur])
        gl.glViewport(0, 0, self._out_w, self._out_h)

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._input_tex)
        gl.glUniform1i(self._loc(p, "u_src"), 0)
        gl.glUniform2f(self._loc(p, "u_srcSize"), float(in_w), float(in_h))
        gl.glUniform2f(self._loc(p, "u_outSize"), float(self._out_w), float(self._out_h))
        gl.glUniform4f(self._loc(p, "u_srcRect"), *self._src_rect)
        gl.glUniform4f(self._loc(p, "u_dstRect"), *self._dst_rect)
        gl.glUniform1i(self._loc(p, "u_mode"), self._cfg["mode"])
        gl.glUniform4f(self._loc(p, "u_con0"), *self._cons[0])
        gl.glUniform4f(self._loc(p, "u_con1"), *self._cons[1])
        gl.glUniform4f(self._loc(p, "u_con2"), *self._cons[2])
        gl.glUniform4f(self._loc(p, "u_con3"), *self._cons[3])

        gl.glBindVertexArray(self._fullscreen_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)

        # Optional RCAS sharpening pass.
        if self._rcas is not None:
            pr = self._prog["rcas"]
            gl.glUseProgram(pr)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_work)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex_final[self._cur])
            gl.glUniform1i(self._loc(pr, "u_src"), 0)
            gl.glUniform1f(self._loc(pr, "u_rcas"), self._rcas)
            gl.glBindVertexArray(self._fullscreen_vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            gl.glBindVertexArray(0)

            # Copy RCAS result back into the current final texture.
            pb = self._prog["blit"]
            gl.glUseProgram(pb)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_final[self._cur])
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex_work)
            gl.glUniform1i(self._loc(pb, "u_src"), 0)
            gl.glBindVertexArray(self._fullscreen_vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            gl.glBindVertexArray(0)

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    def _present(self):
        cfg = self._cfg
        if cfg["fg_enabled"] and self._have_prev and self._prev_ts > 0:
            interval = self._cur_ts - self._prev_ts
            phase = min(1.0, max(0.0, (time.time() - self._cur_ts) / interval)) \
                if interval > 0 else 0.0
            p = self._prog["fg"]
            gl.glUseProgram(p)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex_final[self._cur])
            gl.glUniform1i(self._loc(p, "u_cur"), 0)
            gl.glActiveTexture(gl.GL_TEXTURE1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex_final[self._prev])
            gl.glUniform1i(self._loc(p, "u_prev"), 1)
            gl.glUniform2f(self._loc(p, "u_size"), float(self._out_w), float(self._out_h))
            gl.glUniform1f(self._loc(p, "u_fgPhase"), phase)
        else:
            p = self._prog["blit"]
            gl.glUseProgram(p)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._tex_final[self._cur])
            gl.glUniform1i(self._loc(p, "u_src"), 0)

        gl.glViewport(0, 0, self._out_w, self._out_h)
        gl.glBindVertexArray(self._fullscreen_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)

    # ======================================================================
    # OSD drawing
    # ======================================================================
    def _draw_osd(self):
        cfg = self._cfg
        if cfg is None or not cfg["osd_enabled"]:
            return

        with self.state.stats_lock:
            s = dict(self.state.stats)
            rev = s.get("rev", 0)
        key = (rev, cfg["mode"], cfg["sharpness"], cfg["fg_enabled"],
               cfg["osd_show_fps"], cfg["osd_show_cpu"],
               cfg["osd_show_gpu"], cfg["osd_show_ram"], cfg["lang"])
        if key != self._osd_key:
            self._osd_key = key
            s["src_size"] = (self._input_w, self._input_h)
            s["out_size"] = (self._out_w, self._out_h)
            self._osd_data = self._build_osd_verts(s, cfg)

        data = self._osd_data
        if data is None or len(data) == 0:
            return

        gl.glUseProgram(self._prog["osd"])
        gl.glUniform2f(self._loc(self._prog["osd"], "u_screenSize"),
                       float(self._out_w), float(self._out_h))

        gl.glBindVertexArray(self._osd_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._osd_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_DYNAMIC_DRAW)

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._atlas_tex)
        gl.glUniform1i(self._loc(self._prog["osd"], "u_atlas"), 0)

        gl.glUniform1i(self._loc(self._prog["osd"], "u_solid"), 1)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glUniform1i(self._loc(self._prog["osd"], "u_solid"), 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 6, len(data) // 8 - 6)

        gl.glBindVertexArray(0)

    def _build_osd_verts(self, s, cfg):
        lines = self._build_osd_lines(s, cfg)
        verts = []
        box_h = 14 + 22 * len(lines)
        self._osd_quad_solid(verts, 12, 10, 470, box_h, (0.0, 0.0, 0.0, 0.55))
        y = 20
        for line in lines:
            self._osd_text(verts, line, 24, y, (0.95, 0.95, 0.95, 1.0), 2)
            y += 22
        return np.array(verts, dtype=np.float32)

    def _build_osd_lines(self, s, cfg):
        lang = cfg.get("lang", "en")
        gpu = s["gpu"]
        gpu_str = ("%d%%" % int(round(gpu))) if gpu is not None else "N/A"
        lines = ["%s V%s" % (APP_NAME.upper(), APP_VERSION)]
        if cfg["osd_show_fps"]:
            lines.append(tr(lang, "osd_fps")
                         % (s["capture_fps"], s["render_fps"]))
        parts = []
        if cfg["osd_show_cpu"]:
            parts.append("CPU %3d%%" % int(s["cpu"]))
        if cfg["osd_show_gpu"]:
            parts.append("GPU %s" % gpu_str)
        if cfg["osd_show_ram"]:
            parts.append("RAM %3d%%" % int(s["ram"]))
        if parts:
            lines.append("   ".join(parts))
        mode_key = SCALE_MODE_NAMES.get(cfg["mode"], "fsr")
        lines.append("%s  %dx%d -> %dx%d"
                     % (tr(lang, "osd_mode_" + mode_key),
                        s["src_size"][0], s["src_size"][1],
                        s["out_size"][0], s["out_size"][1]))
        fg_txt = tr(lang, "osd_on") if cfg["fg_enabled"] else tr(lang, "osd_off")
        lines.append(tr(lang, "osd_fg_sharp") % (fg_txt, cfg["sharpness"]))
        return lines

    def _osd_quad_solid(self, verts, x0, y0, x1, y1, color):
        # One solid quad (triangle strip via two triangles).
        self._push(verts, x0, y0, 0, 0, color)
        self._push(verts, x1, y0, 0, 0, color)
        self._push(verts, x0, y1, 0, 0, color)
        self._push(verts, x0, y1, 0, 0, color)
        self._push(verts, x1, y0, 0, 0, color)
        self._push(verts, x1, y1, 0, 0, color)

    def _osd_text(self, verts, text, x, y, color, scale):
        cx = x
        for ch in text:
            u0, v0, u1, v1 = self._char_uv.get(ch, (0.0, 0.0, 0.0, 0.0))
            x0 = cx
            x1 = cx + 5 * scale
            y0 = y
            y1 = y + 7 * scale
            self._push(verts, x0, y0, u0, v0, color)
            self._push(verts, x1, y0, u1, v0, color)
            self._push(verts, x0, y1, u0, v1, color)
            self._push(verts, x0, y1, u0, v1, color)
            self._push(verts, x1, y0, u1, v0, color)
            self._push(verts, x1, y1, u1, v1, color)
            cx += 6 * scale

    @staticmethod
    def _push(verts, x, y, u, v, color):
        verts.extend((x, y, u, v, color[0], color[1], color[2], color[3]))

    # ======================================================================
    # Helpers
    # ======================================================================
    def _loc(self, prog, name):
        key = (prog, name)
        loc = self._loc_cache.get(key)
        if loc is None:
            loc = gl.glGetUniformLocation(prog, name)
            self._loc_cache[key] = loc
        return loc

    def _cleanup(self):
        glfw.terminate()
        gc.enable()

# ---------------------------------------------------------------------------
# Global hotkey listener (pynput on X11, evdev on Wayland)
# ---------------------------------------------------------------------------
class HotkeyListener:
    def __init__(self, state, on_toggle):
        self.state = state
        self.on_toggle = on_toggle
        self.display = detect_display_server()
        self._listener = None
        self._evdev_thread = None
        self._stop = threading.Event()
        self._device = None

    def start(self):
        if self.display == "wayland" and HAS_EVDEV:
            self._evdev_thread = threading.Thread(
                target=self._evdev_loop, daemon=True,
                name="BoostLayer-Hotkey-evdev")
            self._evdev_thread.start()
            print("[BoostLayer] Hotkey: evdev backend (Wayland).")
        elif HAS_PYNPUT:
            try:
                self._listener = _pynput_keyboard.GlobalHotKeys(
                    {self.state.hotkey: self._fire})
                self._listener.daemon = True
                self._listener.start()
                print("[BoostLayer] Hotkey: pynput backend (X11).")
            except Exception as e:
                print("[BoostLayer] Hotkey registration failed:", e)
                self._listener = None
        else:
            print("[BoostLayer] No hotkey backend available "
                  "(install 'pynput' or 'evdev').")

    def stop(self):
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass

    def _fire(self):
        self.on_toggle()

    def _evdev_loop(self):
        try:
            paths = evdev.list_devices()
        except Exception:
            return
        dev = None
        for p in paths:
            try:
                d = evdev.InputDevice(p)
            except OSError:
                continue
            caps = d.capabilities(verbose=False)
            keys = caps.get(1, [])
            if evdev.ecodes.KEY_A in keys or evdev.ecodes.KEY_S in keys:
                dev = d
                break
        if dev is None:
            return
        self._device = dev
        ctrl = alt = False
        try:
            for event in dev.read_loop():
                if self._stop.is_set():
                    break
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                code = event.code
                value = event.value
                if code in (evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_RIGHTCTRL):
                    ctrl = value != 0
                elif code in (evdev.ecodes.KEY_LEFTALT, evdev.ecodes.KEY_RIGHTALT):
                    alt = value != 0
                elif code == evdev.ecodes.KEY_S and value == 1:
                    if ctrl and alt:
                        self._fire()
        except OSError:
            pass


def _make_tray_image():
    """Build a PIL image for the system tray icon (lightning bolt)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 61, 61], radius=14, fill=(26, 26, 46, 255))
    bolt = [
        (int(0.594 * size), int(0.133 * size)),
        (int(0.242 * size), int(0.539 * size)),
        (int(0.445 * size), int(0.539 * size)),
        (int(0.367 * size), int(0.867 * size)),
        (int(0.766 * size), int(0.422 * size)),
        (int(0.547 * size), int(0.422 * size)),
    ]
    d.polygon(bolt, fill=(0, 232, 156, 255))
    return img


def _enable_system_gi():
    """Make the distro's PyGObject (gi) importable inside a venv or a frozen
    build.  Appended to ``sys.path`` so the venv's own packages still win."""
    for p in ("/usr/lib/python3/dist-packages",
              "/usr/lib/python3.12/dist-packages"):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    try:
        import gi  # noqa: F401
        return True
    except Exception:
        return False


class TrayIcon:
    """System tray icon.  Prefers the Ayatana AppIndicator backend (works on
    Cinnamon/GNOME/KDE) and falls back to the legacy XEmbed tray.  Optional —
    degrades gracefully when pystray/Pillow/gi are unavailable."""

    def __init__(self, on_show, on_quit, title="BoostLayer"):
        self._icon = None
        self._backend = None
        self.title = title
        try:
            has_gi = _enable_system_gi()
            if has_gi:
                os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
            else:
                os.environ.setdefault("PYSTRAY_BACKEND", "xorg")
            import importlib
            import pystray
            img = _make_tray_image()
            if img is None:
                return
            menu = pystray.Menu(
                pystray.MenuItem("Show", lambda *_: on_show(), default=True),
                pystray.MenuItem("Quit", lambda *_: on_quit()),
            )
            names = ("_appindicator", "_xorg") if has_gi else ("_xorg",)
            for name in names:
                try:
                    mod = importlib.import_module("pystray." + name)
                    self._icon = mod.Icon("BoostLayer", img, title, menu)
                    self._backend = name.lstrip("_")
                    break
                except Exception as e:
                    _log("tray backend %s unavailable: %r"
                         % (name.lstrip("_"), e))
            if self._icon is None:
                _log("tray disabled: no usable backend (gi=%s)" % has_gi)
        except Exception as e:
            _log("tray unavailable: %r" % (e,))
            self._icon = None

    @property
    def available(self):
        return self._icon is not None

    @property
    def visible(self):
        """True once the icon is actually shown by the desktop's tray."""
        try:
            return bool(self._icon is not None and self._icon.visible)
        except Exception:
            return False

    def start(self):
        if self._icon is None:
            return
        _log("tray: starting backend=%s" % self._backend)
        if hasattr(self._icon, "run_detached"):
            self._icon.run_detached()
        else:
            threading.Thread(target=self._icon.run, daemon=True,
                             name="BoostLayer-Tray").start()
        threading.Thread(target=self._report_state, daemon=True,
                         name="BoostLayer-TrayCheck").start()

    def _report_state(self):
        time.sleep(3.0)
        _log("tray: backend=%s visible=%s" % (self._backend, self.visible))

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass


def _make_window_icon(tk_root, size=64):
    """Build the window/taskbar icon programmatically (no external file):
    a dark gradient square with a teal lightning bolt, matching the packaged
    PNG icon.  Returns a tkinter.PhotoImage."""
    import tkinter as tk

    bolt = [
        (0.594, 0.133), (0.242, 0.539), (0.445, 0.539),
        (0.367, 0.867), (0.766, 0.422), (0.547, 0.422),
    ]

    def in_bolt(x, y):
        inside = False
        n = len(bolt)
        j = n - 1
        for i in range(n):
            xi, yi = bolt[i]
            xj, yj = bolt[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    rows = []
    for yy in range(size):
        row = []
        for xx in range(size):
            nx = (xx + 0.5) / size
            ny = (yy + 0.5) / size
            t = ny
            r = int(18 + (10 - 18) * t)
            g = int(20 + (8 - 20) * t)
            b = int(52 + (26 - 52) * t)
            if in_bolt(nx, ny):
                r, g, b = 0, 232, 156
            row.append("#%02x%02x%02x" % (r, g, b))
        rows.append("{" + " ".join(row) + "}")

    img = tk.PhotoImage(master=tk_root, width=size, height=size)
    img.put(" ".join(rows))
    return img


# ---------------------------------------------------------------------------
# GUI (CustomTkinter, dark theme)
# ---------------------------------------------------------------------------
class BoostLayerApp:
    def __init__(self, state, display_server, gpu_name):
        self.state = state
        self.display_server = display_server
        self.gpu_name = gpu_name
        self.lang = state.lang
        self._win_refresh_t0 = 0.0
        self._last_win_ids = None
        self._tray = None

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("BoostLayer")
        self.root.geometry("540x720")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Window/taskbar icon.
        try:
            self._icon = _make_window_icon(self.root)
            self.root.iconphoto(True, self._icon)
        except Exception:
            self._icon = None

        # System tray icon (optional; closes to tray when available).
        try:
            self._tray = TrayIcon(self._show_from_tray, self._quit_from_tray)
            if self._tray.available:
                self._tray.start()
            else:
                self._tray = None
        except Exception:
            self._tray = None

        self._build_ui()
        self._refresh_status()
        self.root.after(1000, self._periodic_status)

    def _t(self, key):
        """Localise a UI string in the currently selected language."""
        return tr(self.lang, key)

    # ------------------------------------------------------------------
    def _build_ui(self):
        # Language selector (top, always visible).
        lang_row = ctk.CTkFrame(self.root, fg_color="transparent")
        lang_row.pack(fill="x", padx=14, pady=(10, 0))
        self.lang_label = ctk.CTkLabel(
            lang_row, text=self._t("language") + ":",
            anchor="w", font=ctk.CTkFont(size=12))
        self.lang_label.pack(side="left")
        self.lang_menu = ctk.CTkOptionMenu(
            lang_row, values=list(LANGUAGES.values()),
            command=self._on_lang, width=130)
        self.lang_menu.set(LANGUAGES.get(self.lang, "English"))
        self.lang_menu.pack(side="left", padx=(8, 0))

        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(6, 8))
        self.tab_scaling = self.tabview.add(self._t("tab_scaling"))
        self.tab_osd = self.tabview.add(self._t("tab_osd"))
        self.tabview.set(self._t("tab_scaling"))
        self._build_scaling_tab()
        self._build_osd_tab()

        # Status line.
        self.status_var = ctk.StringVar(value=self._t("status_listening"))
        self.status_label = ctk.CTkLabel(
            self.root, textvariable=self.status_var, anchor="w",
            font=ctk.CTkFont(size=12))
        self.status_label.pack(fill="x", padx=14, pady=(0, 4))

        # Buttons.
        btn = ctk.CTkFrame(self.root, fg_color="transparent")
        btn.pack(fill="x", padx=14, pady=(0, 14))
        self.toggle_btn = ctk.CTkButton(
            btn, text=self._t("start_scaling"), width=160, command=self.on_toggle)
        self.toggle_btn.pack(side="left")
        ctk.CTkButton(btn, text=self._t("quit"), width=90, command=self._quit,
                      fg_color="#7a1f1f",
                      hover_color="#a02a2a").pack(side="right")

    def _build_scaling_tab(self):
        t = self.tab_scaling
        pad = {"padx": 14, "pady": 7}
        st = self.state

        # Scaling type.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("scaling_type")).pack(side="left")
        self._mode_labels = [self._t("mode_" + k) for k in SCALE_MODE_KEYS]
        self._mode_by_label = {
            lab: SCALE_MODE_IDS[k]
            for lab, k in zip(self._mode_labels, SCALE_MODE_KEYS)
        }
        self.mode_menu = ctk.CTkOptionMenu(
            row, values=self._mode_labels, width=200, command=self._on_mode)
        self.mode_menu.set(
            self._t("mode_" + SCALE_MODE_NAMES.get(st.mode, "fsr")))
        self.mode_menu.pack(side="right")

        # Sharpness.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("sharpness")).pack(side="left")
        self.sharp_label = ctk.CTkLabel(row, text=str(st.sharpness), width=36)
        self.sharp_label.pack(side="right")
        self.sharp_slider = ctk.CTkSlider(
            t, from_=0, to=100, command=self._on_sharpness)
        self.sharp_slider.set(st.sharpness)
        self.sharp_slider.pack(fill="x", padx=14)

        # Aspect ratio.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("aspect_ratio")).pack(side="left")
        self._aspect_by_label = {self._t("auto"): "auto",
                                 self._t("custom"): "custom"}
        self.aspect_menu = ctk.CTkOptionMenu(
            row, values=[self._t("auto"), self._t("custom")],
            width=140, command=self._on_aspect)
        self.aspect_menu.set(self._t(st.aspect))
        self.aspect_menu.pack(side="right")

        # Custom multiplier.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("custom_multiplier")).pack(side="left")
        self.mult_var = ctk.StringVar(value=str(st.custom_mult))
        self.mult_entry = ctk.CTkEntry(row, width=90,
                                       textvariable=self.mult_var)
        self.mult_entry.pack(side="right")
        self.mult_entry.bind("<Return>", self._on_mult)
        self.mult_entry.bind("<FocusOut>", self._on_mult)
        if st.aspect != "custom":
            self.mult_entry.configure(state="disabled")

        # Frame generation.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("frame_generation")).pack(side="left")
        self.fg_switch = ctk.CTkSwitch(row, text="", command=self._on_fg)
        if st.fg_enabled:
            self.fg_switch.select()
        self.fg_switch.pack(side="right")

        # Capture delay.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("capture_delay_ms")).pack(side="left")
        self.delay_label = ctk.CTkLabel(row, text=str(st.capture_delay_ms),
                                        width=36)
        self.delay_label.pack(side="right")
        self.delay_slider = ctk.CTkSlider(
            t, from_=0, to=500, command=self._on_delay)
        self.delay_slider.set(st.capture_delay_ms)
        self.delay_slider.pack(fill="x", padx=14)

        # Capture target.
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("capture_target")).pack(side="left")
        self._target_by_label = {
            self._t("fullscreen"): "fullscreen",
            self._t("active_window"): "active",
            self._t("window"): "window",
        }
        self.target_menu = ctk.CTkOptionMenu(
            row, values=[self._t("fullscreen"), self._t("active_window"),
                         self._t("window")],
            width=150, command=self._on_target)
        target_display = {
            "fullscreen": "fullscreen", "active": "active_window",
            "window": "window",
        }.get(st.capture_target, "fullscreen")
        self.target_menu.set(self._t(target_display))
        self.target_menu.pack(side="right")

        # Target window (XComposite) selector + actions.
        win_row = ctk.CTkFrame(t, fg_color="transparent")
        win_row.pack(fill="x", **pad)
        ctk.CTkLabel(win_row, text=self._t("target_window")).pack(side="left")
        self.click_btn = ctk.CTkButton(
            win_row, text=self._t("select_window"), width=90,
            command=self._on_select_window)
        self.click_btn.pack(side="right", padx=(0, 6))
        self.refresh_btn = ctk.CTkButton(
            win_row, text=self._t("refresh"), width=60,
            command=self._refresh_windows)
        self.refresh_btn.pack(side="right", padx=(0, 6))
        self._windows = []
        self._win_by_label = {}
        self._last_win_ids = None
        self.window_menu = ctk.CTkOptionMenu(
            win_row, values=[], width=180, command=self._on_window)
        self.window_menu.pack(side="right")
        self._refresh_windows()

        # Capture monitor (mss index) and output monitor (GLFW index).
        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("capture_monitor")).pack(side="left")
        self.cap_mon_menu = ctk.CTkOptionMenu(
            row, values=["1", "2", "3", "4"], width=90,
            command=self._on_capture_monitor)
        self.cap_mon_menu.set(str(st.capture_monitor))
        self.cap_mon_menu.pack(side="right")

        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("output_monitor")).pack(side="left")
        self.out_mon_menu = ctk.CTkOptionMenu(
            row, values=["1", "2", "3", "4"], width=90,
            command=self._on_output_monitor)
        self.out_mon_menu.set(str(st.output_monitor + 1))
        self.out_mon_menu.pack(side="right")

        ctk.CTkLabel(t, text=self._t("capture_note"), wraplength=460,
                     justify="left", font=ctk.CTkFont(size=11),
                     text_color="#8a8a8a"
                     ).pack(fill="x", padx=14, pady=8)

    def _build_osd_tab(self):
        t = self.tab_osd
        pad = {"padx": 14, "pady": 10}
        st = self.state

        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=self._t("performance_osd")).pack(side="left")
        self.osd_switch = ctk.CTkSwitch(row, text="", command=self._on_osd)
        if st.osd_enabled:
            self.osd_switch.select()
        self.osd_switch.pack(side="right")

        ctk.CTkLabel(t, text=self._t("displayed_metrics"), anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(fill="x", padx=14, pady=(6, 0))

        self.fps_chk = ctk.CTkCheckBox(t, text=self._t("metric_fps"),
                                       command=self._on_metrics)
        if st.osd_show_fps:
            self.fps_chk.select()
        self.fps_chk.pack(anchor="w", **pad)

        self.cpu_chk = ctk.CTkCheckBox(t, text=self._t("metric_cpu"),
                                       command=self._on_metrics)
        if st.osd_show_cpu:
            self.cpu_chk.select()
        self.cpu_chk.pack(anchor="w", **pad)

        self.gpu_chk = ctk.CTkCheckBox(t, text=self._t("metric_gpu"),
                                       command=self._on_metrics)
        if st.osd_show_gpu:
            self.gpu_chk.select()
        self.gpu_chk.pack(anchor="w", **pad)

        self.ram_chk = ctk.CTkCheckBox(t, text=self._t("metric_ram"),
                                       command=self._on_metrics)
        if st.osd_show_ram:
            self.ram_chk.select()
        self.ram_chk.pack(anchor="w", **pad)

        ctk.CTkLabel(t, text=self._t("gpu_note"), wraplength=460,
                     justify="left", font=ctk.CTkFont(size=11),
                     text_color="#8a8a8a"
                     ).pack(fill="x", padx=14, pady=10)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _on_mode(self, value):
        self.state.update(mode=self._mode_by_label.get(value, 0))

    def _on_sharpness(self, value):
        v = int(round(float(value)))
        self.sharp_label.configure(text=str(v))
        self.state.update(sharpness=v)

    def _on_aspect(self, value):
        aspect = self._aspect_by_label.get(value, "auto")
        self.state.update(aspect=aspect)
        self.mult_entry.configure(
            state="normal" if aspect == "custom" else "disabled")

    def _on_mult(self, _event=None):
        try:
            v = float(self.mult_var.get())
            if v <= 0:
                raise ValueError
            self.state.update(custom_mult=v)
        except ValueError:
            self.mult_var.set(str(self.state.custom_mult))

    def _on_fg(self):
        self.state.update(fg_enabled=bool(self.fg_switch.get()))

    def _on_delay(self, value):
        v = int(round(float(value)))
        self.delay_label.configure(text=str(v))
        self.state.update(capture_delay_ms=v)

    def _on_target(self, value):
        self.state.update(
            capture_target=self._target_by_label.get(value, "fullscreen"))

    def _refresh_windows(self):
        wins = list_windows()
        new_ids = tuple(sorted(w[0] for w in wins))
        if new_ids == getattr(self, "_last_win_ids", None):
            return  # no new/removed windows — avoid churn while a game launches
        self._last_win_ids = new_ids
        self._windows = wins
        self._win_by_label = {}
        labels = []
        seen = {}
        for wid, title, w, h in wins:
            label = "%s  (%dx%d)" % (title, w, h)
            if len(label) > 42:
                label = label[:39] + "..."
            if label in seen:
                seen[label] += 1
                label = "%s #%d" % (label, seen[label])
            else:
                seen[label] = 1
            labels.append(label)
            self._win_by_label[label] = wid
        if not labels:
            labels = [self._t("window")]
        self.window_menu.configure(values=labels)
        cur = self.state.capture_window_id
        selected = False
        if cur is not None:
            for lab, wid in self._win_by_label.items():
                if wid == cur:
                    self.window_menu.set(lab)
                    selected = True
                    break
        if not selected:
            self.window_menu.set(labels[0])

    def _on_window(self, label):
        wid = self._win_by_label.get(label)
        if wid is None:
            return
        self.state.update(capture_target="window", capture_window_id=wid)
        self.target_menu.set(self._t("window"))

    def _on_select_window(self):
        """Hide the GUI, let the user click a window, then capture it."""
        self.root.withdraw()
        self.root.update()
        time.sleep(0.3)
        wid = None
        try:
            wid = select_window_by_click()
        finally:
            self.root.deiconify()
        if wid:
            self.state.update(capture_target="window", capture_window_id=wid)
            self.target_menu.set(self._t("window"))
            self._refresh_windows()
            # Reflect the click even if the window list itself did not change.
            for lab, w in self._win_by_label.items():
                if w == wid:
                    self.window_menu.set(lab)
                    break

    def _on_capture_monitor(self, value):
        try:
            self.state.update(capture_monitor=int(value))
        except ValueError:
            pass

    def _on_output_monitor(self, value):
        try:
            self.state.update(output_monitor=int(value) - 1)  # 1-based -> 0-based
        except ValueError:
            pass

    def _on_osd(self):
        self.state.update(osd_enabled=bool(self.osd_switch.get()))

    def _on_metrics(self):
        self.state.update(
            osd_show_fps=bool(self.fps_chk.get()),
            osd_show_cpu=bool(self.cpu_chk.get()),
            osd_show_gpu=bool(self.gpu_chk.get()),
            osd_show_ram=bool(self.ram_chk.get()),
        )

    # ------------------------------------------------------------------
    def on_toggle(self):
        active = self.state.toggle_scaling()
        self.root.after(0, self._refresh_status)

    def _refresh_status(self):
        active = self.state.scaling_active
        self.toggle_btn.configure(
            text=self._t("stop_scaling") if active else self._t("start_scaling"))
        server = self.display_server.upper()
        state_txt = self._t("status_scaling") if active else self._t("status_idle")
        self.status_var.set(
            self._t("status_fmt")
            % (self.state.hotkey, state_txt, server, self.gpu_name))

    def _periodic_status(self):
        if self.root.winfo_exists():
            self._refresh_status()
            now = time.time()
            if now - self._win_refresh_t0 >= 3.0:
                self._win_refresh_t0 = now
                try:
                    self._refresh_windows()
                except Exception:
                    pass
            self.root.after(1000, self._periodic_status)

    def _on_lang(self, value):
        code = {v: k for k, v in LANGUAGES.items()}.get(value, "en")
        if code == self.lang:
            return
        self.lang = code
        self.state.update(lang=code)
        self._rebuild_ui()

    def _rebuild_ui(self):
        for w in self.root.winfo_children():
            w.destroy()
        self._build_ui()
        self._refresh_status()

    def _quit(self):
        self.state.running.clear()
        if self._tray is not None:
            self._tray.stop()
        self.root.destroy()

    def _on_close(self):
        # Close button -> hide to tray.  If the desktop has no tray, minimize
        # instead so the window can never get lost.
        if self._tray is not None and self._tray.visible:
            self.root.withdraw()
        elif self._tray is not None:
            self.root.iconify()
        else:
            self._quit()

    def _show_from_tray(self):
        def _restore():
            self.root.deiconify()
            self.root.lift()
            try:
                self.root.focus_force()
            except Exception:
                pass
        self.root.after(0, _restore)

    def _quit_from_tray(self):
        self.root.after(0, self._quit)

    def run(self):
        self.root.mainloop()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("%s v%s — Linux scaling overlay" % (APP_NAME, APP_VERSION))
    print("=" * 60)

    # Only one instance may run: several overlays capturing and presenting at
    # the same time would stack windows and can freeze the desktop.
    instance_lock = _acquire_single_instance()
    if instance_lock is False:
        _log("second instance refused (single-instance lock held)")
        print("Another BoostLayer instance is already running — exiting.")
        return 0

    # Log uncaught thread exceptions instead of losing them (the packaged
    # build has no attached terminal).
    def _thread_hook(args):
        _log("uncaught exception in %s: %r"
             % (getattr(args.thread, "name", "?"), args.exc_value))
    threading.excepthook = _thread_hook

    display = detect_display_server()
    gpu = GpuMonitor()
    print("Display server :", display)
    print("GPU            :", gpu.name)
    if psutil is None:
        print("WARNING: 'psutil' missing — CPU/RAM telemetry disabled.")
    if not HAS_MSS:
        print("ERROR: 'mss' missing — screen capture unavailable.")
    if not HAS_GL:
        print("ERROR: 'PyOpenGL'/'glfw' missing — renderer unavailable.")
    if not HAS_CTK:
        print("ERROR: 'customtkinter' missing — GUI unavailable.")
        return 1

    state = AppState()
    stats = StatsCollector(state, gpu)
    capture = CaptureThread(state, stats)
    renderer = GLRenderer(state, stats)
    app = BoostLayerApp(state, display, gpu.name)
    hotkey = HotkeyListener(state, app.on_toggle)

    # Start background threads before entering the Tk mainloop.
    stats.start()
    capture.start()
    renderer.start()
    hotkey.start()

    # Log uncaught thread exceptions instead of losing them (the packaged
    # build has no attached terminal).
    _log("%s v%s started (display=%s, gpu=%s)"
         % (APP_NAME, APP_VERSION, display, gpu.name))

    rc = 0
    try:
        app.run()
    except KeyboardInterrupt:
        rc = 130
    finally:
        state.running.clear()
        hotkey.stop()
        for t in (capture, renderer, stats):
            t.join(timeout=2.0)
    return rc


if __name__ == "__main__":
    sys.exit(main())
