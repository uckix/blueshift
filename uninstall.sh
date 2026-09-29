#!/usr/bin/env bash
# BlueShift uninstaller (keeps ~/.config/blueshift unless --purge)
set -uo pipefail

as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; elif [ -n "${SUDO_ASKPASS:-}" ]; then sudo -A "$@"; else sudo "$@"; fi; }

systemctl --user disable --now blueshift.service blueshift-client.service >/dev/null 2>&1
rm -f "${HOME}/.config/systemd/user/blueshift.service" "${HOME}/.config/systemd/user/blueshift-client.service"
systemctl --user daemon-reload >/dev/null 2>&1

rm -rf "${HOME}/.local/share/blueshift"
rm -f "${HOME}/.local/bin/blueshift" \
      "${HOME}/.local/share/applications/blueshift.desktop" \
      "${HOME}/.local/share/icons/hicolor/scalable/apps/blueshift.svg" \
      "${HOME}/.local/share/icons/hicolor/512x512/apps/blueshift.png"

for f in /etc/udev/rules.d/70-blueshift-input.rules /etc/udev/rules.d/99-blueshift-input.rules /usr/local/bin/blueshift; do
    { [ -e "$f" ] || [ -L "$f" ]; } && as_root rm -f "$f"
done
as_root udevadm control --reload-rules >/dev/null 2>&1

[ "${1:-}" = "--purge" ] && rm -rf "${HOME}/.config/blueshift"
echo "BlueShift removed. (/etc/bluetooth/main.conf tuning, if any, is left in place; backup at main.conf.blueshift.bak)"
