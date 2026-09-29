#!/usr/bin/env bash
set -e

# ============================================================================
# BlueShift Uninstaller
# ============================================================================

RED='\033[0;31m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${BLUE}Uninstalling BlueShift...${NC}"

USER_HOME="${HOME:-/home/gg}"

HAS_SUDO=0
if [ "$EUID" -eq 0 ]; then
    HAS_SUDO=1
elif sudo -n true 2>/dev/null; then
    HAS_SUDO=1
fi

# 1. Stop systemd services
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop blueshift.service 2>/dev/null || true
    systemctl --user disable blueshift.service 2>/dev/null || true
    systemctl --user stop blueshift-client.service 2>/dev/null || true
    systemctl --user disable blueshift-client.service 2>/dev/null || true
fi

# 2. Remove systemd service files
rm -f "${USER_HOME}/.config/systemd/user/blueshift.service"
rm -f "${USER_HOME}/.config/systemd/user/blueshift-client.service"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

# 3. Remove udev rules
UDEV_DEST="/etc/udev/rules.d/99-blueshift-input.rules"
if [ -f "${UDEV_DEST}" ]; then
    if [ -w "${UDEV_DEST}" ]; then
        rm -f "${UDEV_DEST}"
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
    elif [ "${HAS_SUDO}" -eq 1 ]; then
        sudo rm -f "${UDEV_DEST}"
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
    fi
fi

# 4. Remove Desktop files and icons
rm -f "${USER_HOME}/.local/share/applications/blueshift.desktop"
rm -f "${USER_HOME}/.local/share/icons/hicolor/scalable/apps/blueshift.svg"
rm -f "${USER_HOME}/.local/share/icons/hicolor/512x512/apps/blueshift.png"

if [ "${HAS_SUDO}" -eq 1 ]; then
    sudo rm -f /usr/share/applications/blueshift.desktop 2>/dev/null || true
    sudo rm -f /usr/share/icons/hicolor/scalable/apps/blueshift.svg 2>/dev/null || true
    sudo rm -f /usr/share/icons/hicolor/512x512/apps/blueshift.png 2>/dev/null || true
fi

# 5. Remove binary launcher
if [ -f "/usr/local/bin/blueshift" ]; then
    if [ -w "/usr/local/bin/blueshift" ]; then
        rm -f "/usr/local/bin/blueshift"
    elif [ "${HAS_SUDO}" -eq 1 ]; then
        sudo rm -f "/usr/local/bin/blueshift"
    fi
fi
rm -f "${USER_HOME}/.local/bin/blueshift"

echo -e "${GREEN}✔ BlueShift components removed successfully.${NC}"
