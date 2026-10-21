#!/bin/sh
# Boostlayer reproducible packaging: PyInstaller -> AppDir -> .deb / .AppImage.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERSION=${VERSION:-$(cat "$ROOT/VERSION" 2>/dev/null || printf '0.1.0')}
PYTHON=${PYTHON:-python3}
BUILD_DIR="$ROOT/build"
DIST_DIR="$ROOT/dist"
APPDIR="$DIST_DIR/AppDir"
DEB_ROOT="$DIST_DIR/deb-root"
APP_NAME="Boostlayer"

case "$(uname -m)" in
    x86_64|amd64)
        APPIMAGE_ARCH=x86_64
        DEB_ARCH=amd64
        ;;
    aarch64|arm64)
        APPIMAGE_ARCH=aarch64
        DEB_ARCH=arm64
        ;;
    *)
        echo "Nieobsługiwana architektura: $(uname -m)" >&2
        exit 1
        ;;
esac

if ! "$PYTHON" -m PyInstaller --version >/dev/null 2>&1; then
    echo "Brak PyInstaller. Zainstaluj: $PYTHON -m pip install pyinstaller PyQt6" >&2
    exit 1
fi
if ! "$PYTHON" -c 'import PyQt6' >/dev/null 2>&1; then
    echo "Brak PyQt6. Zainstaluj: $PYTHON -m pip install PyQt6" >&2
    exit 1
fi
for required in launcher.sh assets/crt.fx assets/boostlayer.svg tools/render_icons.py tools/install-gamepad-udev.sh; do
    if [ ! -f "$ROOT/$required" ]; then
        echo "Brak wymaganego pliku: $required" >&2
        exit 1
    fi
done

echo "== Boostlayer $VERSION ($APPIMAGE_ARCH) =="
rm -rf "$BUILD_DIR" "$APPDIR" "$DEB_ROOT"
mkdir -p "$BUILD_DIR" "$DIST_DIR"
printf '%s\n' "$VERSION" > "$BUILD_DIR/VERSION"
ICONS_DIR="$BUILD_DIR/icons"
mkdir -p "$ICONS_DIR"
QT_QPA_PLATFORM=offscreen "$PYTHON" "$ROOT/tools/render_icons.py" \
    "$ROOT/assets/boostlayer.svg" "$ICONS_DIR"
# Never publish stale artifacts from an older app/version in SHA256SUMS.
rm -f "$DIST_DIR"/*.deb "$DIST_DIR"/*.AppImage "$DIST_DIR/SHA256SUMS"

# One-dir build: faster start than one-file and friendlier for AppImage.
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name boostlayer \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --specpath "$BUILD_DIR" \
    --add-data "$ROOT/launcher.sh:." \
    --add-data "$BUILD_DIR/VERSION:." \
    --add-data "$ROOT/assets:assets" \
    --add-data "$ROOT/tools:tools" \
    --exclude-module tkinter \
    --exclude-module unittest \
    --exclude-module pydoc \
    "$ROOT/main.py"

if [ ! -x "$DIST_DIR/boostlayer/boostlayer" ]; then
    echo "PyInstaller nie utworzył dist/boostlayer/boostlayer" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# AppDir
# ---------------------------------------------------------------------------
mkdir -p \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/lib" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/doc/boostlayer"
cp -a "$DIST_DIR/boostlayer" "$APPDIR/usr/lib/boostlayer"
ln -s ../lib/boostlayer/boostlayer "$APPDIR/usr/bin/boostlayer"
cp "$ROOT/assets/boostlayer.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/boostlayer.svg"
cp "$ROOT/assets/boostlayer.svg" "$APPDIR/boostlayer.svg"
for size in 16 24 32 48 64 128 256 512; do
    icon_dir="$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$icon_dir"
    cp "$ICONS_DIR/boostlayer-${size}.png" "$icon_dir/boostlayer.png"
done
cp "$ICONS_DIR/boostlayer-256.png" "$APPDIR/boostlayer.png"
cp "$ICONS_DIR/boostlayer-256.png" "$APPDIR/.DirIcon"

cat > "$APPDIR/usr/share/applications/boostlayer.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Boostlayer
GenericName=Game Launcher
Comment=Minimalist Wine/Proton launcher with MangoHud, GameMode and Steam wrapper
Exec=boostlayer %F
Icon=boostlayer
Terminal=false
Categories=Game;Utility;
Keywords=game;wine;proton;steam;mangohud;gamemode;
StartupNotify=true
StartupWMClass=boostlayer
DESKTOP
cp "$APPDIR/usr/share/applications/boostlayer.desktop" "$APPDIR/boostlayer.desktop"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
set -eu
APPDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export APPDIR
export PATH="$APPDIR/usr/bin:$PATH"
exec "$APPDIR/usr/bin/boostlayer" "$@"
APPRUN
chmod 0755 "$APPDIR/AppRun"

# ---------------------------------------------------------------------------
# .deb
# ---------------------------------------------------------------------------
mkdir -p \
    "$DEB_ROOT/DEBIAN" \
    "$DEB_ROOT/usr/bin" \
    "$DEB_ROOT/usr/lib" \
    "$DEB_ROOT/usr/share/applications" \
    "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$DEB_ROOT/usr/share/doc/boostlayer"
cp -a "$APPDIR/usr/lib/boostlayer" "$DEB_ROOT/usr/lib/boostlayer"
ln -s ../lib/boostlayer/boostlayer "$DEB_ROOT/usr/bin/boostlayer"
cp "$APPDIR/usr/share/applications/boostlayer.desktop" \
    "$DEB_ROOT/usr/share/applications/boostlayer.desktop"
cp "$APPDIR/usr/share/icons/hicolor/scalable/apps/boostlayer.svg" \
    "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/boostlayer.svg"
for size in 16 24 32 48 64 128 256 512; do
    icon_dir="$DEB_ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$icon_dir"
    cp "$ICONS_DIR/boostlayer-${size}.png" "$icon_dir/boostlayer.png"
done
cat > "$DEB_ROOT/usr/share/doc/boostlayer/README" <<'README'
Boostlayer
==========
Launcher: boostlayer
Dane: ~/.config/boostlayer/
Wymagane opcjonalnie: wine, gamemoderun, mangohud, gamescope.
README

INSTALLED_SIZE=$(du -sk "$DEB_ROOT/usr" | awk '{print $1}')
cat > "$DEB_ROOT/DEBIAN/control" <<CONTROL
Package: boostlayer
Version: $VERSION
Section: games
Priority: optional
Architecture: $DEB_ARCH
Installed-Size: $INSTALLED_SIZE
Maintainer: Boostlayer <boostlayer@localhost>
Depends: libc6, libx11-6, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libxkbcommon0, libgl1, libegl1, libfontconfig1, libdbus-1-3, libwayland-client0, mangohud, gamemode
Recommends: gamescope
Suggests: wine, mangoapp, intel-gpu-tools
Description: Minimalist Wine/Proton game launcher with MangoHud and GameMode
 Boostlayer launches standalone Windows games and imported Steam entries with
 isolated WINEPREFIXes, Feral GameMode, MangoHud, Gamescope scaling and a
 lightweight PyQt6 library UI.
CONTROL
cat > "$DEB_ROOT/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi
exit 0
POSTINST
chmod 0755 "$DEB_ROOT/DEBIAN/postinst"

DEB_PATH="$DIST_DIR/Boostlayer-${VERSION}-${DEB_ARCH}.deb"
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_PATH" >/dev/null
else
    echo "dpkg-deb niedostępny — składam .deb przez ar+tar." >&2
    TMP_DEB="$BUILD_DIR/deb"
    mkdir -p "$TMP_DEB"
    printf '2.0\n' > "$TMP_DEB/debian-binary"
    tar -C "$DEB_ROOT/DEBIAN" -czf "$TMP_DEB/control.tar.gz" .
    tar -C "$DEB_ROOT" -czf "$TMP_DEB/data.tar.gz" --exclude=./DEBIAN .
    (
        cd "$TMP_DEB"
        ar rcs "$DEB_PATH" debian-binary control.tar.gz data.tar.gz
    )
fi

# ---------------------------------------------------------------------------
# .AppImage
# ---------------------------------------------------------------------------
if [ "${SKIP_APPIMAGE:-0}" = "1" ]; then
    echo "Pominięto AppImage (SKIP_APPIMAGE=1)."
else
    TOOL=${APPIMAGETOOL:-}
    if [ -z "$TOOL" ]; then
        TOOL=$(command -v appimagetool || true)
    fi
    if [ -z "$TOOL" ]; then
        TOOL="$BUILD_DIR/appimagetool-$APPIMAGE_ARCH.AppImage"
        URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$APPIMAGE_ARCH.AppImage"
        echo "Pobieram appimagetool: $URL"
        if command -v curl >/dev/null 2>&1; then
            curl -fL --retry 3 -o "$TOOL" "$URL"
        elif command -v wget >/dev/null 2>&1; then
            wget -O "$TOOL" "$URL"
        else
            echo "Brak curl/wget do pobrania appimagetool." >&2
            exit 1
        fi
        chmod 0755 "$TOOL"
    fi
    APPIMAGE_PATH="$DIST_DIR/Boostlayer-${VERSION}-${APPIMAGE_ARCH}.AppImage"
    rm -f "$APPIMAGE_PATH"
    APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$APPIMAGE_ARCH" \
        "$TOOL" "$APPDIR" "$APPIMAGE_PATH"
    chmod 0755 "$APPIMAGE_PATH"
fi

# ---------------------------------------------------------------------------
# Checksums and summary
# ---------------------------------------------------------------------------
(
    cd "$DIST_DIR"
    : > SHA256SUMS
    for artifact in Boostlayer-"$VERSION"-*.deb Boostlayer-"$VERSION"-*.AppImage; do
        if [ -f "$artifact" ]; then
            sha256sum "$artifact" >> SHA256SUMS
        fi
    done
)
echo
echo "Gotowe:"
ls -lh "$DIST_DIR"/*.deb "$DIST_DIR"/*.AppImage 2>/dev/null || true
cat "$DIST_DIR/SHA256SUMS" 2>/dev/null || true
