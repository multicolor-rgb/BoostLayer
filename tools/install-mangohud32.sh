#!/bin/sh
# Install the official 32-bit MangoHud release for old 32-bit games.
#
# Ubuntu/Mint do not ship mangohud:i386.  MangoHud publishes a lib32 build in
# its GitHub releases (the Arch package is just a convenient container for the
# same upstream binaries).  We extract only the i386 shared libraries and put
# them where the stock /usr/bin/mangohud wrapper looks for $LIB.
set -eu

VERSION=${MANGOHUD32_VERSION:-0.8.0}
ASSET="lib32-mangohud-${VERSION}-1-x86_64.pkg.tar.zst"
URL="https://github.com/flightlessmango/MangoHud/releases/download/v${VERSION}/${ASSET}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/boostlayer/mangohud32"
ARCHIVE="$CACHE/$ASSET"
EXTRACT="$CACHE/extract"
DEST="/usr/lib/i386-linux-gnu/mangohud"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'Brak wymaganego programu: %s\n' "$1" >&2
        exit 2
    }
}

need curl
need tar
need zstd
need pkexec

mkdir -p "$CACHE"
if [ ! -s "$ARCHIVE" ]; then
    printf 'Pobieram %s...\n' "$ASSET"
    curl -fL --retry 3 -o "$ARCHIVE.part" "$URL"
    [ "$(wc -c < "$ARCHIVE.part")" -gt 1024 ] || {
        printf 'Pobrany plik jest zbyt mały.\n' >&2
        rm -f "$ARCHIVE.part"
        exit 3
    }
    mv "$ARCHIVE.part" "$ARCHIVE"
fi

rm -rf "$EXTRACT"
mkdir -p "$EXTRACT"
tar --zstd -xf "$ARCHIVE" -C "$EXTRACT"
for lib in libMangoHud.so libMangoHud_opengl.so libMangoHud_shim.so; do
    [ -f "$EXTRACT/usr/lib32/$lib" ] || {
        printf 'Brak %s w archiwum MangoHud.\n' "$lib" >&2
        exit 4
    }
done

# Runtime libraries needed by the 32-bit overlay and by 32-bit GameMode.
if command -v apt-get >/dev/null 2>&1; then
    printf 'Instaluję biblioteki i386 (pkexec)...\n'
    pkexec apt-get install -y \
        mangohud \
        libc6:i386 libgcc-s1:i386 \
        libwayland-client0:i386 libxkbcommon0:i386 \
        libgl1:i386 libglx0:i386 libglvnd0:i386 libvulkan1:i386 \
        libx11-6:i386 libxrandr2:i386 libxcb1:i386 \
        libgamemode0:i386 libgamemodeauto0:i386
fi

pkexec install -d "$DEST"
for lib in libMangoHud.so libMangoHud_opengl.so libMangoHud_shim.so; do
    pkexec install -m 0755 "$EXTRACT/usr/lib32/$lib" "$DEST/$lib"
done

# Optional Vulkan implicit-layer manifest, with the Arch path rewritten.
if [ -f "$EXTRACT/usr/share/vulkan/implicit_layer.d/MangoHud.x86.json" ]; then
    MANIFEST="$CACHE/MangoHud.x86.json"
    sed 's#/usr/lib32/#/usr/lib/i386-linux-gnu/mangohud/#g' \
        "$EXTRACT/usr/share/vulkan/implicit_layer.d/MangoHud.x86.json" \
        > "$MANIFEST"
    pkexec install -Dm644 "$MANIFEST" \
        /usr/share/vulkan/implicit_layer.d/MangoHud.x86.json
fi

if command -v ldconfig >/dev/null 2>&1; then
    pkexec ldconfig || true
fi

printf 'Gotowe: %s/libMangoHud.so\n' "$DEST"
