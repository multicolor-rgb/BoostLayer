# BoostLayer

Ultra-lean Linux scaling overlay — an open-source Lossless Scaling clone.

BoostLayer captures a monitor or a single window, upscales it on the GPU with a
GLSL shader and presents the result in a borderless, always-on-top overlay. It
also offers in-shader motion-adaptive frame generation, a performance OSD and a
global hotkey. Written in Python with GLFW + PyOpenGL; packaged as a single
binary, `.deb` and `.AppImage`.

## Features

- **Scaling modes** — AMD FSR 1.0 (EASU + RCAS), integer, nearest and bicubic.
- **Frame generation** — motion-adaptive interpolation in GLSL.
- **Capture targets**
  - *Fullscreen* — the topmost window on the selected monitor (captured
    off-screen, so the overlay can never capture itself — no mirror feedback).
  - *Active Window* — follows the focused window automatically.
  - *Window* — a window picked from the list or by clicking it.
- **Window picker** — `Click window` hides the GUI, shows a crosshair and
  captures whatever you click (right-click cancels). Wine/Proton virtual
  desktops are supported and unnamed windows show the running `.exe` name.
- **Multi-monitor** — separate capture monitor and output monitor selectors.
- **Always on top** — the overlay re-asserts `_NET_WM_STATE_ABOVE` once per
  second without stealing keyboard focus, so fullscreen games cannot bury it.
- **Click-through** — an empty X11 input shape is applied to the overlay, so
  clicks and key presses reach the game/desktop underneath instead of being
  swallowed by the full-screen window.
- **Single instance** — a second launch exits immediately; stacked overlays and
  duplicate capture threads cannot pile up and stall the desktop.
- **Performance OSD** — capture FPS, render FPS, CPU, GPU, RAM.
- **System tray** — closing the window hides BoostLayer to the tray
  (AppIndicator/StatusNotifier, with a legacy XEmbed fallback). Tray menu:
  *Show* / *Quit*. Without a tray the window is minimised instead.
- **Global hotkey** — `Ctrl+Alt+S` toggles scaling (X11 and Wayland).
- **Languages** — English, German, Polish (switchable at runtime).
- **Low overhead** — shared-memory window capture (`XShmGetImage`, ~5 ms per
  1080p frame), reused textures (`glTexSubImage2D`), no per-frame allocations,
  no GC pauses in the hot loops.

## Requirements

- Linux with X11 (recommended) or Wayland.
- OpenGL 4.0 capable GPU: AMD (Mesa), NVIDIA or Intel.
- Runtime libraries: `libgl1`, `libx11-6`, `python3-tk`.
- Optional, for the tray icon: `gir1.2-ayatanaappindicator3-0.1`.

## Install

```bash
# Debian / Ubuntu
sudo apt install ./boostlayer_1.0.1_amd64.deb

# AppImage (no installation)
chmod +x BoostLayer-1.0.1-x86_64.AppImage
./BoostLayer-1.0.1-x86_64.AppImage
```

Or run the portable single binary: `./boostlayer`.

## Usage

1. Launch BoostLayer.
2. Pick a **capture target** — *Fullscreen*, *Active Window* or *Window*.
   - For *Window*, select the entry from the list, press **Refresh**, or press
     **Click window** and click the game.
3. Choose **capture monitor** (1 = primary, 2 = next, …) and **output monitor**
   (1-based, matching the monitor layout).
4. Set the scaling mode, sharpness and frame generation.
5. Press **Ctrl+Alt+S** (or the *Start/Stop* button) to toggle the overlay.
6. Closing the window keeps BoostLayer running in the tray.

For Proton/Steam games run the game in **windowed** or **borderless** mode.
Exclusive fullscreen is intentionally never used by the overlay, so the game is
not kicked out of its own display mode.

### Troubleshooting

- **The window list does not show the game name** — the game may run in a Wine
  virtual desktop (an unnamed override-redirect window). Use `Click window` to
  pick it directly, or run the game in windowed/borderless mode.
- **Black overlay** — the selected window cannot be composited (e.g. a
  compositor-internal window). Pick another window; a fullscreen grab is used
  only when the overlay is not covering the captured monitor.
- **Duplicated panel / frozen desktop** — this was caused by capturing the
  monitor (and therefore the overlay itself). Current builds capture windows
  off-screen and refuse monitor grabs while the overlay is visible, so this
  cannot happen; press `Ctrl+Alt+S` to hide the overlay if an old build
  misbehaves.
- **No tray icon** — install `gir1.2-ayatanaappindicator3-0.1`; otherwise the
  window is minimised on close instead of hidden.
- **Logs** — BoostLayer writes a small log to
  `~/.local/state/boostlayer/boostlayer.log`, including the chosen tray backend
  and any renderer errors.

## Build

```bash
./build.sh              # native arch: binary + .deb + AppImage in dist/
./build.sh arm64        # cross-deb target name (see build.sh for the mapping)
```

The script creates an isolated build virtualenv, installs `requirements.txt`,
runs PyInstaller (`--onefile --strip`), generates the icon, and packages both a
`.deb` and an `.AppImage`.

> The final one-file executable is intentionally **not** UPX-compressed: UPX
> rewrites the PyInstaller bootloader and the embedded archive can no longer be
> located at runtime. Set `BOOSTLAYER_UPX=1` to force the old behaviour.

## Development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python main.py
```

## License

Released under the MIT License.
