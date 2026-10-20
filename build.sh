#!/usr/bin/env bash
# =============================================================================
#  BoostLayer build script — produces a PyInstaller one-file binary compressed
#  with UPX, then packages it as a portable .AppImage and an installable .deb.
#
#  Usage:  ./build.sh            (builds both packages)
#          ./build.sh clean      (remove build artefacts)
#
#  Requirements: python3, venv, curl/tar, dpkg-deb (for .deb), appimagetool.
# =============================================================================
set -euo pipefail

APP_NAME="boostlayer"
APP_TITLE="BoostLayer"
VERSION="1.0.0"
ARCH="$(uname -m)"                 # x86_64 | aarch64 | armv7l | i686 | ...

# ---------------------------------------------------------------------------
# Architecture mapping.
#
# PyInstaller does NOT cross-compile: the binary is always built for the arch
# this script runs on. To target other architectures, run build.sh natively on
# each one (or inside a QEMU/container/CI matrix). These mappings only make the
# produced packages correctly named and the .deb `Architecture` field valid.
# ---------------------------------------------------------------------------
case "$ARCH" in
    x86_64)  DEB_ARCH="amd64"    ; APPIMAGE_ARCH="x86_64"  ; UPX_SUFFIX="amd64_linux" ;;
    aarch64) DEB_ARCH="arm64"    ; APPIMAGE_ARCH="aarch64" ; UPX_SUFFIX="arm64_linux" ;;
    armv7l)  DEB_ARCH="armhf"    ; APPIMAGE_ARCH="armhf"   ; UPX_SUFFIX="armhf_linux" ;;
    armv6l)  DEB_ARCH="armel"    ; APPIMAGE_ARCH="armhf"   ; UPX_SUFFIX=""            ;;
    i686)    DEB_ARCH="i386"     ; APPIMAGE_ARCH="i686"    ; UPX_SUFFIX="i386_linux"  ;;
    ppc64le) DEB_ARCH="ppc64el"  ; APPIMAGE_ARCH="ppc64le" ; UPX_SUFFIX=""            ;;
    riscv64) DEB_ARCH="riscv64"  ; APPIMAGE_ARCH="riscv64" ; UPX_SUFFIX=""            ;;
    s390x)   DEB_ARCH="s390x"    ; APPIMAGE_ARCH="s390x"   ; UPX_SUFFIX=""            ;;
    *)       DEB_ARCH="$ARCH"    ; APPIMAGE_ARCH="$ARCH"   ; UPX_SUFFIX=""            ;;
esac

ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$ROOT/build"
DIST_DIR="$ROOT/dist"
VENV="$BUILD_DIR/venv"
TOOLS="$BUILD_DIR/tools"
APPDIR="$BUILD_DIR/AppDir"
DEB_DIR="$BUILD_DIR/deb"

BIN="$DIST_DIR/$APP_NAME"

log()  { printf '\033[1;36m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
clean() {
  log "Cleaning build artefacts..."
  rm -rf "$BUILD_DIR" "$DIST_DIR" "$ROOT/build" "$ROOT/dist" \
         "$ROOT"/*.spec "$ROOT"/__pycache__
}
[ "${1:-}" = "clean" ] && { clean; exit 0; }

mkdir -p "$BUILD_DIR" "$DIST_DIR" "$TOOLS"

# ---------------------------------------------------------------------------
# 1. Virtualenv + dependencies
# ---------------------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  log "Creating virtualenv..."
  python3 -m venv "$VENV"
fi
log "Installing dependencies (pip)..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt" pyinstaller

# ---------------------------------------------------------------------------
# 2. UPX (used to shrink the one-file binary)
# ---------------------------------------------------------------------------
find_upx() {
  if command -v upx >/dev/null 2>&1; then
    command -v upx
    return 0
  fi
  # Try to fetch a static UPX build for the current architecture.
  [ -n "$UPX_SUFFIX" ] || return 1
  UPX_URL="https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-${UPX_SUFFIX}.tar.xz"
  local tarball="$TOOLS/upx.tar.xz"
  if [ ! -x "$TOOLS/upx" ]; then
    log "Downloading UPX..."
    if curl -fsSL "$UPX_URL" -o "$tarball"; then
      tar -xJf "$tarball" -C "$TOOLS" --strip-components=1
      rm -f "$tarball"
    else
      rm -f "$tarball"
      return 1
    fi
  fi
  [ -x "$TOOLS/upx" ] && echo "$TOOLS/upx" && return 0
  return 1
}

UPX_BIN="$(find_upx || true)"

# ---------------------------------------------------------------------------
# 3. PyInstaller — stripped, lean, one-file
# ---------------------------------------------------------------------------
log "Building one-file binary with PyInstaller..."
# shellcheck disable=SC2046
"$VENV/bin/pyinstaller" \
  --onefile \
  --noconsole \
  --noconfirm \
  --strip \
  --noupx \
  --name "$APP_NAME" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR/pyi" \
  --specpath "$BUILD_DIR" \
  --exclude-module tkinter.test \
  --exclude-module unittest \
  --exclude-module test \
  --exclude-module doctest \
  --exclude-module pydoc_data \
  --exclude-module setuptools \
  --exclude-module pip \
  --exclude-module wheel \
  --exclude-module pytest \
  --exclude-module matplotlib \
  --exclude-module scipy \
  --exclude-module pandas \
  --exclude-module PyQt5 \
  --exclude-module PyQt6 \
  --exclude-module PySide2 \
  --exclude-module PySide6 \
  --collect-all customtkinter \
  --collect-all glfw \
  --collect-all pynput \
  --collect-all evdev \
  "$ROOT/main.py"

if [ -n "$UPX_BIN" ]; then
  log "Compressing binary with UPX ($UPX_BIN)..."
  "$UPX_BIN" --best --lzma "$BIN" || warn "UPX failed; continuing with uncompressed binary."
else
  warn "UPX not available — skipping binary compression."
fi

ORIG_SIZE=$(du -h "$BIN" | cut -f1)
log "Binary ready: $BIN ($ORIG_SIZE)"

# ---------------------------------------------------------------------------
# 4. Icon (generated programmatically — pure stdlib PNG writer, no deps)
# ---------------------------------------------------------------------------
ICON_PNG="$BUILD_DIR/$APP_NAME.png"
log "Generating icon..."
python3 - "$ICON_PNG" <<'PYEOF'
import sys, zlib, struct

W = H = 256
out = sys.argv[1]

def rounded_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r or (x0 + r <= x <= x1 - r) or (y0 + r <= y <= y1 - r)

def in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside

# Lightning bolt polygon (centred, classic shape).
bolt = [
    (152, 34), (62, 138), (114, 138), (94, 222), (196, 108), (140, 108),
]

rows = []
for y in range(H):
    row = bytearray()
    for x in range(W):
        if not rounded_rect(x, y, 4, 4, 251, 251, 48):
            row += b"\x00\x00\x00\x00"
            continue
        t = y / H
        bg = (int(18 + (10 - 18) * t), int(20 + (8 - 20) * t), int(52 + (26 - 52) * t))
        if in_poly(x, y, bolt):
            r, g, b, a = 0, 232, 156, 255
        else:
            r, g, b, a = bg[0], bg[1], bg[2], 255
        row += bytes((r, g, b, a))
    rows.append(b"\x00" + bytes(row))  # filter type 0 per scanline

raw = b"".join(rows)

def chunk(typ, data):
    c = struct.pack(">I", len(data)) + typ + data
    c += struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)
    return c

ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + \
      chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")

with open(out, "wb") as f:
    f.write(png)
print("Icon written:", out)
PYEOF

# ---------------------------------------------------------------------------
# 5. AppImage
# ---------------------------------------------------------------------------
log "Assembling AppDir..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp "$BIN" "$APPDIR/usr/bin/$APP_NAME"
cp "$ROOT/boostlayer.desktop" "$APPDIR/usr/share/applications/$APP_NAME.desktop"
cp "$ICON_PNG" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP_NAME.png"
# appimagetool requires the .desktop file at the AppDir root (and an icon).
cp "$ROOT/boostlayer.desktop" "$APPDIR/$APP_NAME.desktop"
cp "$ICON_PNG" "$APPDIR/$APP_NAME.png"
cp "$ICON_PNG" "$APPDIR/.DirIcon"
cp "$ROOT/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/$APP_NAME"

find_appimagetool() {
  if command -v appimagetool >/dev/null 2>&1; then
    command -v appimagetool; return 0
  fi
  local t="$TOOLS/appimagetool"
  if [ ! -x "$t" ]; then
    URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage"
    log "Downloading appimagetool..."
    curl -fsSL "$URL" -o "$t" && chmod +x "$t" || { rm -f "$t"; return 1; }
  fi
  echo "$t"
}

APPIMAGE_TOOL="$(find_appimagetool || true)"
if [ -n "$APPIMAGE_TOOL" ]; then
  log "Building .AppImage..."
  APPIMAGE_OUT="$DIST_DIR/${APP_TITLE}-${VERSION}-${APPIMAGE_ARCH}.AppImage"
  "$APPIMAGE_TOOL" "$APPDIR" "$APPIMAGE_OUT" || warn "appimagetool failed."
  [ -f "$APPIMAGE_OUT" ] && log "AppImage ready: $APPIMAGE_OUT"
else
  warn "appimagetool not available — skipping .AppImage (AppDir kept in $APPDIR)."
fi

# ---------------------------------------------------------------------------
# 6. Debian package
# ---------------------------------------------------------------------------
if command -v dpkg-deb >/dev/null 2>&1; then
  log "Building .deb..."

  rm -rf "$DEB_DIR"
  mkdir -p "$DEB_DIR/DEBIAN" \
           "$DEB_DIR/usr/bin" \
           "$DEB_DIR/usr/share/applications" \
           "$DEB_DIR/usr/share/icons/hicolor/256x256/apps"

  cp "$BIN" "$DEB_DIR/usr/bin/$APP_NAME"
  cp "$ROOT/boostlayer.desktop" "$DEB_DIR/usr/share/applications/$APP_NAME.desktop"
  cp "$ICON_PNG" "$DEB_DIR/usr/share/icons/hicolor/256x256/apps/$APP_NAME.png"

  cat > "$DEB_DIR/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: graphics
Priority: optional
Architecture: $DEB_ARCH
Maintainer: multicolor-rgb <multicolor-rgb@users.noreply.github.com>
Depends: libc6 (>= 2.17), libgl1, libx11-6
Description: Ultra-lean Linux scaling overlay (Lossless Scaling clone)
 BoostLayer is a native Linux scaling overlay with AMD FSR 1.0 upscaling,
 integer/nearest/bicubic scaling, in-shader frame generation, a performance
 OSD (FPS/CPU/GPU/RAM) and a global hotkey. Works on AMD (Mesa), NVIDIA and
 Intel (iris) under both X11 and Wayland.
EOF

  DEB_OUT="$DIST_DIR/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
  dpkg-deb --build "$DEB_DIR" "$DEB_OUT"
  log ".deb ready: $DEB_OUT"
else
  warn "dpkg-deb not available — skipping .deb."
fi

# ---------------------------------------------------------------------------
log "Done. Artifacts in: $DIST_DIR"
ls -lh "$DIST_DIR"
