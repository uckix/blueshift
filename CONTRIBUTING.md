# Contributing to BlueShift 🚀

Thank you for your interest in contributing to **BlueShift**! We are thrilled to welcome your bug reports, feature ideas, architectural enhancements, and code contributions. BlueShift is dedicated to delivering a seamless, low-latency, kernel-level Bluetooth KVM experience for Linux users worldwide.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [How Can I Contribute?](#how-can-i-contribute)
   - [Reporting Bugs](#reporting-bugs)
   - [Suggesting Enhancements](#suggesting-enhancements)
   - [Submitting Pull Requests](#submitting-pull-requests)
3. [Architecture & Design Principles](#architecture--design-principles)
4. [Development Environment Setup](#development-environment-setup)
5. [Running Tests & Linting](#running-tests--linting)
6. [Testing Without a Second PC (Mock Testing)](#testing-without-a-second-pc-mock-testing)
7. [Commit Message Guidelines](#commit-message-guidelines)
8. [Security Disclosures](#security-disclosures)

---

## Code of Conduct

We expect all contributors and participants to follow the [Contributor Covenant](https://www.contributor-covenant.org/) standard:
- **Respect and empathy** towards all maintainers and contributors.
- **Constructive technical critique** focused on code quality and user experience.
- Zero tolerance for harassment, derogatory language, or exclusionary behavior.

---

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please run our built-in diagnostic tool:

```bash
blueshift doctor
```

When filing an issue on [GitHub Issues](https://github.com/uckix/blueshift/issues), please provide:
1. **Linux Distribution & Kernel Version**: e.g., Arch Linux `6.11.0-arch1` or Parrot OS `6.1`.
2. **Bluetooth Controller Details**: Output of `bluetoothctl show` or `hciconfig -a`.
3. **Desktop Environment**: Wayland (Sway, Hyprland, GNOME, KDE) or X11.
4. **Steps to Reproduce**: Detailed reproduction flow.
5. **Debug Logs**: Run `blueshift daemon --log-level DEBUG` and attach the output.

### Suggesting Enhancements

Have an idea for multi-host switching, screen-edge traversal, or clipboard synchronization? Open a feature request under [Discussions / Issues](https://github.com/uckix/blueshift/issues) describing:
- The problem you are trying to solve.
- Your proposed solution or user experience flow.
- Any potential Bluetooth or kernel constraints.

### Submitting Pull Requests

1. Fork the repository and create a descriptive branch:
   ```bash
   git checkout -b feat/screen-edge-traversal
   # or
   git checkout -b fix/evdev-exclusive-grab-deadlock
   ```
2. Write clean, idiomatic Python with complete type hints (`mypy`).
3. Add or update unit and integration tests.
4. Ensure all linters and tests pass locally.
5. Open a Pull Request referencing any related issues.

---

## Architecture & Design Principles

BlueShift is engineered with three core principles:
1. **Zero Wi-Fi Dependency**: Everything operates over standard Bluetooth Low Energy GATT (HOGP).
2. **Kernel-Level Precision**: Input events are captured via Linux `evdev` (`EVIOCGRAB`), ensuring hotkey reliability across Wayland, X11, and TTYs.
3. **Driverless Target**: The target machine requires zero software; BlueShift behaves as a standard compliant Bluetooth 5.0 Human Interface Device.

### Core Modules

- `blueshift.evdev`: Captures physical keyboard and mouse events using `/dev/input/event*`, filters out security tokens (e.g. YubiKeys), and passes events to the router.
- `blueshift.uinput`: Manages local virtual devices via `/dev/uinput` to replay input back to the host machine when in Host Mode.
- `blueshift.bluetooth`: Implements the BlueZ D-Bus GATT Server (`org.bluez.GattManager1`) and LE Advertising (`org.bluez.LEAdvertisement1`) adhering to the Bluetooth HID Over GATT Profile (HOGP) specification.
- `blueshift.router`: The state engine that dispatches events between local `uinput` and remote Bluetooth GATT HID reports.
- `blueshift.hotkey`: Non-blocking chord and single-key interceptor that handles state toggles (`Scroll Lock`, `Ctrl+Alt+S`).
- `blueshift.gui` / `blueshift.cli`: User interfaces built with GTK4 / PyQt6 and Click/Typer.

---

## Development Environment Setup

### 1. System Dependencies

#### Arch Linux:
```bash
sudo pacman -S base-devel python bluez bluez-utils pkgconf libbluetooth-dev
```

#### Debian / Ubuntu / Parrot OS:
```bash
sudo apt update
sudo apt install -y python3-dev python3-pip python3-venv bluez libbluetooth-dev pkg-config
```

#### Fedora:
```bash
sudo dnf install -y python3-devel python3-pip bluez bluez-libs-devel pkgconf
```

### 2. Permissions (Non-Root Operation)

To capture input events and interact with the Bluetooth subsystem without running as `root`, add your user to the appropriate groups:

```bash
sudo usermod -aG input,bluetooth $USER
```

Install the project udev rule to allow access to `/dev/uinput`:

```bash
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-blueshift-uinput.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

> [!NOTE]
> Log out and log back in (or run `newgrp input`) for group membership changes to take effect.

### 3. Python Virtual Environment

```bash
git clone https://github.com/uckix/blueshift.git
cd blueshift

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"
```

Or using Poetry:

```bash
poetry install --with dev
poetry shell
```

---

## Running Tests & Linting

We enforce strict formatting and static typing across the entire codebase.

### Linting & Formatting

```bash
# Run Ruff for formatting and lint checks
ruff check .
ruff format --check .

# Run static type checking with Mypy
mypy blueshift
```

To auto-format code:
```bash
ruff format .
ruff check --fix .
```

### Running Test Suite

```bash
# Run all tests
pytest -v

# Run with coverage report
pytest --cov=blueshift --cov-report=term-missing
```

---

## Testing Without a Second PC (Mock Testing)

You don't need two physical computers to test BlueShift! We provide comprehensive mock fixtures:

1. **Virtual Input Simulation**: `blueshift.testing.MockEvdevDevice` creates virtual `/dev/uinput` test devices that emit synthetic keystrokes and mouse movements.
2. **D-Bus Mocking**: Our pytest test suite utilizes `dbus-mock` to emulate BlueZ's `GattManager1` and `LEAdvertisingManager1` without requiring a physical Bluetooth dongle.

```bash
pytest tests/unit/
```

To test Bluetooth advertising locally without a target:
```bash
blueshift daemon --dry-run --log-level DEBUG
```

---

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <short description>

[optional body]

[optional footer(s)]
```

### Common Types:
- `feat`: A new feature (e.g., `feat(ble): implement adaptive connection interval`)
- `fix`: A bug fix (e.g., `fix(evdev): release stuck modifier keys on switch`)
- `docs`: Documentation updates (e.g., `docs(readme): add Wayland troubleshooting tips`)
- `refactor`: Code reorganization without functional changes
- `test`: Adding or updating test cases
- `perf`: Performance optimizations

---

## Security Disclosures

If you discover a security vulnerability in BlueShift (such as accidental input event leakage, unauthenticated pairing bypass, or privilege escalation vectors), please **do not** create a public GitHub issue.

Instead, please send an encrypted email or open a private advisory at:
- **Security Contact**: `security@uckix.org`
- Or use GitHub's private vulnerability reporting feature under the **Security** tab.

We will acknowledge reports within 48 hours and work with you on a coordinated disclosure timeline.

---

*Thank you for helping make BlueShift the fastest, most reliable open-source Bluetooth KVM for Linux!*
