#!/usr/bin/env bash
set -e

# ============================================================================
# BlueShift One-Click Installer
# ============================================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}====================================================${NC}"
echo -e "${BLUE}        ✦ BlueShift BLE KVM Switch Installer ✦     ${NC}"
echo -e "${CYAN}====================================================${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_HOME="${HOME:-/home/gg}"

HAS_SUDO=0
if [ "$EUID" -eq 0 ]; then
    HAS_SUDO=1
elif sudo -n true 2>/dev/null; then
    HAS_SUDO=1
fi

# 1. Check Python Dependencies
echo -e "\n${BLUE}[1/6] Verifying Python runtime and core libraries...${NC}"
python3 -c "import PyQt6, evdev, dbus, gi" 2>/dev/null || {
    echo -e "${YELLOW}Notice: Installing missing Python packages via pip...${NC}"
    pip3 install --quiet PyQt6 evdev dbus-python PyGObject || true
}
echo -e "${GREEN}✔ Python environment verified.${NC}"

# 2. Setup Udev Rules
echo -e "\n${BLUE}[2/6] Configuring udev rules for evdev input grabbing...${NC}"
UDEV_RULE_SRC="${SCRIPT_DIR}/udev/99-blueshift-input.rules"
UDEV_DEST="/etc/udev/rules.d/99-blueshift-input.rules"

if [ -w "/etc/udev/rules.d" ]; then
    cp "${UDEV_RULE_SRC}" "${UDEV_DEST}"
    chmod 644 "${UDEV_DEST}"
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
    echo -e "${GREEN}✔ Udev rule installed directly to ${UDEV_DEST}.${NC}"
elif [ "${HAS_SUDO}" -eq 1 ]; then
    sudo cp "${UDEV_RULE_SRC}" "${UDEV_DEST}"
    sudo chmod 644 "${UDEV_DEST}"
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    echo -e "${GREEN}✔ Udev rule installed via sudo to ${UDEV_DEST}.${NC}"
else
    echo -e "${YELLOW}Notice: Sudo password required for /etc/udev/rules.d. If needed, run:${NC}"
    echo -e "  sudo cp \"${UDEV_RULE_SRC}\" /etc/udev/rules.d/"
    echo -e "  sudo udevadm control --reload-rules && sudo udevadm trigger"
fi

# 3. Install Application Icons
echo -e "\n${BLUE}[3/6] Installing desktop and tray vector icons...${NC}"
ICON_DIR_SVG="${USER_HOME}/.local/share/icons/hicolor/scalable/apps"
ICON_DIR_PNG="${USER_HOME}/.local/share/icons/hicolor/512x512/apps"
mkdir -p "${ICON_DIR_SVG}" "${ICON_DIR_PNG}"

cp "${SCRIPT_DIR}/assets/blueshift.svg" "${ICON_DIR_SVG}/blueshift.svg"
cp "${SCRIPT_DIR}/assets/blueshift.png" "${ICON_DIR_PNG}/blueshift.png"

if [ "${HAS_SUDO}" -eq 1 ]; then
    sudo mkdir -p /usr/share/icons/hicolor/scalable/apps /usr/share/icons/hicolor/512x512/apps 2>/dev/null || true
    sudo cp "${SCRIPT_DIR}/assets/blueshift.svg" /usr/share/icons/hicolor/scalable/apps/blueshift.svg 2>/dev/null || true
    sudo cp "${SCRIPT_DIR}/assets/blueshift.png" /usr/share/icons/hicolor/512x512/apps/blueshift.png 2>/dev/null || true
fi
echo -e "${GREEN}✔ Icons installed.${NC}"

# 4. Install FreeDesktop .desktop Launcher
echo -e "\n${BLUE}[4/6] Installing FreeDesktop launcher...${NC}"
APP_DIR="${USER_HOME}/.local/share/applications"
mkdir -p "${APP_DIR}"
cp "${SCRIPT_DIR}/blueshift.desktop" "${APP_DIR}/blueshift.desktop"
chmod +x "${APP_DIR}/blueshift.desktop"

if [ "${HAS_SUDO}" -eq 1 ]; then
    sudo cp "${SCRIPT_DIR}/blueshift.desktop" /usr/share/applications/blueshift.desktop 2>/dev/null || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APP_DIR}" 2>/dev/null || true
fi
echo -e "${GREEN}✔ Desktop entry installed to ${APP_DIR}/blueshift.desktop.${NC}"

# 5. Install Systemd User Services
echo -e "\n${BLUE}[5/6] Installing systemd user services...${NC}"
SYSTEMD_USER_DIR="${USER_HOME}/.config/systemd/user"
mkdir -p "${SYSTEMD_USER_DIR}"

cp "${SCRIPT_DIR}/systemd/blueshift.service" "${SYSTEMD_USER_DIR}/blueshift.service"
cp "${SCRIPT_DIR}/systemd/blueshift-client.service" "${SYSTEMD_USER_DIR}/blueshift-client.service"

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi
echo -e "${GREEN}✔ Systemd user services installed (blueshift.service, blueshift-client.service).${NC}"

# 6. Create Binary Launcher Symlink / Executable
echo -e "\n${BLUE}[6/6] Creating blueshift command launcher...${NC}"
WRAPPER_LOCAL="${USER_HOME}/.local/bin/blueshift"
mkdir -p "${USER_HOME}/.local/bin"

cat << 'EOF' > "${WRAPPER_LOCAL}"
#!/usr/bin/env bash
export PYTHONPATH="/home/gg/blueshift:${PYTHONPATH}"
exec /usr/bin/python3 /home/gg/blueshift/src/main.py "$@"
EOF
chmod +x "${WRAPPER_LOCAL}"
echo -e "${GREEN}✔ Created user launcher at ${WRAPPER_LOCAL}.${NC}"

if [ -w "/usr/local/bin" ]; then
    cp "${WRAPPER_LOCAL}" "/usr/local/bin/blueshift"
    chmod +x "/usr/local/bin/blueshift"
    echo -e "${GREEN}✔ Created system launcher at /usr/local/bin/blueshift.${NC}"
elif [ "${HAS_SUDO}" -eq 1 ]; then
    sudo cp "${WRAPPER_LOCAL}" "/usr/local/bin/blueshift"
    sudo chmod +x "/usr/local/bin/blueshift"
    echo -e "${GREEN}✔ Created system launcher via sudo at /usr/local/bin/blueshift.${NC}"
fi

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}   ✔ BlueShift installation completed successfully!${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "Start BlueShift by running: ${CYAN}blueshift${NC}"
echo -e "Or toggle active control with: ${CYAN}blueshift --toggle${NC}"
