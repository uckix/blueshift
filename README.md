<div align="center">

# ⚡ BlueShift

### One keyboard and mouse, two Linux PCs — over Bluetooth

</div>

BlueShift turns the PC your keyboard and mouse are plugged into (the **host**) into a
Bluetooth LE keyboard + mouse. Press **Ctrl + Alt + S** and your input moves to the other PC
(the **target**); press it again and it comes back. No Wi-Fi, no network, no IP address.

- Works on Wayland and X11 (it reads `/dev/input` directly)
- Grabs *all* keyboards and mice, and picks up receivers that are unplugged/replugged
- If the target disconnects while it has control, control snaps back to the host
- Hardware security keys (YubiKey, Nitrokey, …) are never forwarded

## Install

On **both** PCs, from this folder:

```bash
# Host (the PC with the keyboard & mouse)
./install.sh --role server --peer <TARGET_BT_MAC> --peer-name <target-name>

# Target (the PC that should receive them)
./install.sh --role client --peer <HOST_BT_MAC> --peer-name <host-name>
```

Find a PC's Bluetooth MAC with `bluetoothctl show`. The installer:

- installs Python/Qt/BlueZ packages with your package manager (pacman, apt or dnf)
- adds a udev rule so the logged-in user can read keyboards/mice (`uaccess`, not world-readable)
- on the target, lowers the BLE connection interval to 7.5–15 ms in `/etc/bluetooth/main.conf`
  (BlueZ defaults to 30–50 ms, which makes the mouse feel laggy; a backup is kept)
- installs to `~/.local/share/blueshift`, adds `blueshift` to `~/.local/bin`, an app-menu
  entry, and a systemd user service that starts at login

The first time, the target pairs with the host over Bluetooth LE. If the host shows a
pairing prompt, accept it.

## Use

Open **BlueShift** from the app menu. There is one screen:

- **Host:** two tiles, *this PC* and *the other PC*. Click one (or press the switch key)
  to send your keyboard and mouse there.
- **Target:** shows whether it's using the host's keyboard & mouse, with **Connect** and
  **Re-pair** buttons.
- **⚙** sets which PC this is, which PC is the other one, and the switch key
  (Ctrl + Alt + S, Scroll Lock, Pause, or Right Alt).

From a terminal or a keyboard shortcut:

```bash
blueshift toggle        # or: local / remote
blueshift status
blueshift connect       # target: connect now;  blueshift repair: forget + pair again
```

## How it works

```
Host PC                                               Target PC
keyboard/mouse ─► evdev (EVIOCGRAB) ─► BlueShift ─► BlueZ GATT (HID over GATT)
                                                         │ BLE notifications
                                                         ▼
                                     BlueZ HOG ─► kernel uhid ─► normal keyboard & mouse
```

The target needs nothing special to *receive* input — any OS that supports Bluetooth
keyboards works. The BlueShift service on a Linux target only makes pairing reliable:
PCs that were paired over classic Bluetooth otherwise keep connecting over classic, which
cannot carry HID-over-GATT, so the keyboard never shows up.

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| Host says *Waiting for …* forever | On the target press **Re-pair**. Accept any pairing prompt on the host. |
| *Can't read the keyboard* | Log out and back in once after installing (the udev ACL applies to new sessions). |
| Mouse feels laggy | Re-run `./install.sh --role client …` on the target to apply the latency tuning. |
| Anything else | `journalctl --user -u blueshift -f` on either PC. |

Settings live in `~/.config/blueshift/config.json`. Uninstall with `./uninstall.sh`
(`--purge` also deletes settings).

## Development

```bash
python3 -m unittest discover tests     # no Bluetooth or input hardware needed
python3 src/main.py daemon -v          # run the service in the foreground
```

## License

MIT — Copyright © 2026 uckix
