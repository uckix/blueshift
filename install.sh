#!/usr/bin/env bash
# ============================================================================
# BlueShift installer
#   ./install.sh                                  keep the current role (default: server)
#   ./install.sh --role server                    this PC shares its keyboard & mouse
#   ./install.sh --role client --peer MAC [--peer-name NAME]
#                                                 this PC uses the host's keyboard & mouse
#   --sudo-stdin   read the sudo password from the first line of stdin
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${HOME}/.local/share/blueshift/app"
BIN="${HOME}/.local/bin/blueshift"
ROLE="" PEER="" PEER_NAME="" SUDO_STDIN=""

while [ $# -gt 0 ]; do
    case "$1" in
        --role) ROLE="$2"; shift 2 ;;
        --peer) PEER="$2"; shift 2 ;;
        --peer-name) PEER_NAME="$2"; shift 2 ;;
        --sudo-stdin) SUDO_STDIN=1; shift ;;
        *) echo "Unknown option: $1"; exit 2 ;;
    esac
done

G='\033[0;32m' B='\033[0;34m' Y='\033[1;33m' N='\033[0m'
step() { echo -e "\n${B}==> $*${N}"; }
ok()   { echo -e "${G}✔ $*${N}"; }
warn() { echo -e "${Y}! $*${N}"; }

SUDO_PW=""
if [ -n "$SUDO_STDIN" ]; then IFS= read -r SUDO_PW || true; fi
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif [ -n "$SUDO_STDIN" ]; then printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"
    elif [ -n "${SUDO_ASKPASS:-}" ]; then sudo -A "$@"
    else sudo "$@"
    fi
}

# ---------------------------------------------------------------------------
step "Checking dependencies"
if ! /usr/bin/python3 -c "import PyQt6.QtWidgets, evdev, dbus, gi" 2>/dev/null; then
    if command -v pacman >/dev/null; then
        as_root pacman -S --needed --noconfirm python-pyqt6 python-evdev python-dbus python-gobject libnotify bluez bluez-utils
    elif command -v apt-get >/dev/null; then
        as_root apt-get install -y python3-pyqt6 python3-evdev python3-dbus python3-gi libnotify-bin bluez
    elif command -v dnf >/dev/null; then
        as_root dnf install -y python3-pyqt6 python3-evdev python3-dbus python3-gobject libnotify bluez
    fi
    /usr/bin/python3 -c "import PyQt6.QtWidgets, evdev, dbus, gi" 2>/dev/null || \
        /usr/bin/python3 -m pip install --user --break-system-packages PyQt6 evdev dbus-python PyGObject
fi
/usr/bin/python3 -c "import PyQt6.QtWidgets, evdev, dbus, gi"
as_root systemctl enable --now bluetooth.service >/dev/null 2>&1 || warn "Could not enable bluetooth.service"
ok "Python, BlueZ and Qt are available"

# ---------------------------------------------------------------------------
step "Input device permissions"
as_root install -m 644 "${SCRIPT_DIR}/udev/70-blueshift-input.rules" /etc/udev/rules.d/70-blueshift-input.rules
# v1.0 rule made every input device world-readable; remove it
[ -f /etc/udev/rules.d/99-blueshift-input.rules ] && as_root rm -f /etc/udev/rules.d/99-blueshift-input.rules
as_root udevadm control --reload-rules
as_root udevadm trigger --subsystem-match=input --action=change
ok "Keyboards and mice are readable by the logged-in user"

# ---------------------------------------------------------------------------
# Resolve the role now so the Bluetooth tuning below knows which side we are.
if [ -z "$ROLE" ] && [ -f "${HOME}/.config/blueshift/config.json" ]; then
    ROLE="$(/usr/bin/python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('role','server'))" "${HOME}/.config/blueshift/config.json" 2>/dev/null || true)"
fi
case "$ROLE" in host) ROLE=server ;; target) ROLE=client ;; server|client) ;; *) ROLE=server ;; esac

if [ "$ROLE" = "client" ]; then
    step "Tuning Bluetooth LE latency (connection interval 7.5-15 ms)"
    # The receiving PC is the BLE central, so it picks the connection interval.
    # BlueZ defaults to 30-50 ms, which makes the mouse feel laggy.
    TUNE="$(mktemp)"
    cat > "$TUNE" <<'PY'
import re, sys, shutil
path = sys.argv[1]
try:
    text = open(path).read()
except FileNotFoundError:
    text = ""
want = {"MinConnectionInterval": "6", "MaxConnectionInterval": "12", "ConnectionLatency": "0"}
lines = text.splitlines()
if not any(l.strip() == "[LE]" for l in lines):
    lines += ["", "[LE]"]
start = next(i for i, l in enumerate(lines) if l.strip() == "[LE]")
end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
changed = False
for key, val in want.items():
    pat = re.compile(rf"^\s*#?\s*{key}\s*=")
    idx = next((i for i in range(start + 1, end) if pat.match(lines[i])), None)
    new = f"{key}={val}"
    if idx is None:
        lines.insert(start + 1, new); end += 1; changed = True
    elif lines[idx].strip() != new:
        lines[idx] = new; changed = True
if changed:
    if text:
        shutil.copy2(path, path + ".blueshift.bak")
    open(path, "w").write("\n".join(lines) + "\n")
print("yes" if changed else "no")
PY
    # (script in a file, not stdin: stdin may be carrying the sudo password)
    CHANGED="$(as_root /usr/bin/python3 "$TUNE" /etc/bluetooth/main.conf)"
    rm -f "$TUNE"
    if [ "$CHANGED" = "yes" ]; then
        as_root systemctl restart bluetooth.service
        sleep 2
        ok "Updated /etc/bluetooth/main.conf (backup: main.conf.blueshift.bak) and restarted Bluetooth"
    else
        ok "Already tuned"
    fi
fi

# ---------------------------------------------------------------------------
step "Installing BlueShift to ${APP_DIR}"
systemctl --user stop blueshift.service blueshift-client.service >/dev/null 2>&1 || true
systemctl --user disable blueshift-client.service >/dev/null 2>&1 || true
rm -f "${HOME}/.config/systemd/user/blueshift-client.service"

rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}" "$(dirname "$BIN")"
cp -r "${SCRIPT_DIR}/src" "${SCRIPT_DIR}/assets" "${APP_DIR}/"
find "${APP_DIR}" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$BIN" <<EOF
#!/usr/bin/env bash
exec /usr/bin/python3 "${APP_DIR}/src/main.py" "\$@"
EOF
chmod +x "$BIN"
# v1.0 put a wrapper pointing at the git checkout here
if [ -f /usr/local/bin/blueshift ] && grep -q "src/main.py" /usr/local/bin/blueshift 2>/dev/null; then
    as_root ln -sf "$BIN" /usr/local/bin/blueshift
fi

mkdir -p "${HOME}/.local/share/icons/hicolor/scalable/apps" "${HOME}/.local/share/icons/hicolor/512x512/apps" "${HOME}/.local/share/applications"
cp "${SCRIPT_DIR}/assets/blueshift.svg" "${HOME}/.local/share/icons/hicolor/scalable/apps/blueshift.svg"
cp "${SCRIPT_DIR}/assets/blueshift.png" "${HOME}/.local/share/icons/hicolor/512x512/apps/blueshift.png"
# Absolute Exec path: ~/.local/bin is often not on the desktop session's PATH
sed "s|^Exec=blueshift|Exec=${BIN}|" "${SCRIPT_DIR}/blueshift.desktop" > "${HOME}/.local/share/applications/blueshift.desktop"
update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
ok "Installed (command: blueshift, app menu: BlueShift)"

# ---------------------------------------------------------------------------
step "Configuring role: ${ROLE}"
SETUP=(setup --role "$ROLE")
[ -n "$PEER" ] && SETUP+=(--peer "$PEER")
[ -n "$PEER_NAME" ] && SETUP+=(--peer-name "$PEER_NAME")
"$BIN" "${SETUP[@]}" >/dev/null
ok "Saved ~/.config/blueshift/config.json"

# ---------------------------------------------------------------------------
step "Starting the background service"
install -m 644 "${SCRIPT_DIR}/systemd/blueshift.service" "${HOME}/.config/systemd/user/blueshift.service" 2>/dev/null || {
    mkdir -p "${HOME}/.config/systemd/user"
    install -m 644 "${SCRIPT_DIR}/systemd/blueshift.service" "${HOME}/.config/systemd/user/blueshift.service"
}
systemctl --user daemon-reload
systemctl --user enable blueshift.service >/dev/null 2>&1
systemctl --user restart blueshift.service
sleep 2
if systemctl --user is-active --quiet blueshift.service; then
    ok "blueshift.service is running"
else
    warn "blueshift.service failed to start: journalctl --user -u blueshift -n 30"
    exit 1
fi

echo -e "\n${G}BlueShift is installed.${N} Open it from the app menu or run: blueshift"
