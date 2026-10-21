#!/bin/sh
# Grant the active desktop user access to joystick devices without adding
# them to the broad "input" group.
set -eu

if ! command -v pkexec >/dev/null 2>&1; then
    printf '%s\n' "Brak pkexec — zainstaluj regułę udev ręcznie." >&2
    exit 2
fi
if ! command -v udevadm >/dev/null 2>&1; then
    printf '%s\n' "Brak udevadm — nie można odświeżyć reguł udev." >&2
    exit 3
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
printf '%s\n' 'KERNEL=="js[0-9]*", SUBSYSTEM=="input", TAG+="uaccess"' > "$TMP"
pkexec install -Dm644 "$TMP" /etc/udev/rules.d/99-boostlayer-gamepad.rules
pkexec udevadm control --reload-rules
pkexec udevadm trigger --subsystem-match=input
printf '%s\n' "Gotowe. Odłącz i podłącz pad ponownie."
