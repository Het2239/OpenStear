# OpenSteer

Turn your phone into a tilt steering wheel for your PC. The phone opens a web
page; the PC host feeds its input to a virtual Xbox 360 controller, so any game
with controller support works. Free and open source, no app or account needed.

Status: Phase 2 (USB via ADB, USB tethering and Wi-Fi). See [plan.md](plan.md)
for the roadmap.

## Install (Windows)

1. Install the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases)
   (it provides the virtual Xbox 360 controller).
2. Install Python 3.11+ from python.org, then in the repo folder:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
   If ViGEmBus is missing, installing `vgamepad` opens the ViGEmBus installer;
   accept it.
3. For USB (ADB) mode, put Android
   [platform-tools](https://developer.android.com/tools/releases/platform-tools)
   in `vendor\platform-tools\` (so `vendor\platform-tools\adb.exe` exists), or
   have `adb` on PATH.
4. Start the host:
   ```
   .venv\Scripts\python -m host.main
   ```
   A window opens with the connection mode, a QR code and status.

Check the controller in `joy.cpl` ("Set up USB game controllers") or
https://gamepad-tester.com.

## Connecting a phone

| Mode | Phones | Steps |
|---|---|---|
| **USB (ADB)** | Android | Enable USB debugging, plug in, accept the prompt, scan the QR code. |
| **USB tethering** | Android, iPhone | Plug in, turn on USB tethering (Android) or Personal Hotspot (iPhone), scan the QR code. |
| **Wi-Fi** | Android, iPhone | Same Wi-Fi as the PC, scan the QR code. |

Tethering and Wi-Fi use HTTPS, because phones only give motion sensors to
secure pages. The first time, the QR code opens a setup page that walks you
through trusting the PC's certificate on the phone (once per PC). The
certificate is created on your PC, and it can only vouch for private network
addresses, not websites.

Windows asks to allow Python through the firewall the first time you pick
tethering or Wi-Fi. Allow it on private networks.

Holding the phone: landscape, like a wheel. Tap **Start** (iPhone: **Enable
motion & Start**) while holding it level; **Center** re-levels it any time.

## Options

```
python -m host.main [--mode usb|tether|wifi] [--port 8765] [--pad auto|vigem|log]
                    [--no-ui] [--no-adb] [--new-token] [-v]
```

Ports: 8765 (USB, local only), 8766 (HTTPS), 8767 (certificate setup page).
Settings, the pairing token and certificates are stored in
`%APPDATA%\OpenSteer\` (`~/.config/OpenSteer/` elsewhere). `--new-token`
unpairs all phones.

On Linux/macOS the host runs with a log-only pad (it prints what it would send),
which is handy for working on the phone app. The window needs tkinter
(`sudo apt install python3-tk` on Debian/Ubuntu); without it the host runs in
the console.

## Development

```
pip install -r requirements-dev.txt
pytest
```

CI runs the tests on Linux and Windows. To check the real virtual pad on a
Windows PC with ViGEmBus installed (it drives a pad and reads it back through
XInput):

```
set OPENSTEER_VIGEM_TEST=1
pytest -v tests/test_vigem_real.py
```

## License

MIT. ViGEmBus (BSD-3) and vgamepad (MIT) are separate projects.
