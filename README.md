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

## Layouts

Pick a layout with the **☰** button on the phone (or "Layout" on the start
screen). The choice is remembered.

| Layout | Steering | What's on it |
|---|---|---|
| Classic wheel | tilt | Brake and gas pedals, A/B/X/Y |
| F1 wheel | tilt | Gear paddles, pedals, DRS, radio, pit, ERS, overtake, MFD pad, OK, camera, menu |
| F1 simple | tilt | Big gear paddles, pedals, DRS, OK, pit, radio, MFD pad, menu |
| Xbox style | touch | Two sticks, D-pad, A/B/X/Y, LB/RB, analog LT/RT, stick clicks, View/Home/Menu |
| PlayStation style | touch | The same with PlayStation labels (✕ ○ □ △, L1/R1, L2/R2, Share/Options) |

The PC always sees an Xbox 360 controller. The F1 layouts send F1 25's default
Xbox controls, so they work without rebinding:

| On the phone | Xbox button | F1 25 action |
|---|---|---|
| − / + paddles | X / A | Gear down / gear up (A is also clutch) |
| DRS, PIT | Y | DRS, pit limiter (same button in game) |
| OT | B | Overtake |
| RADIO | LB | Radio / voice commands |
| CAM | RB | Change camera |
| LOOK | RS click | Look back |
| FLASH | View | Flashback / replay |
| MENU | Menu | Pause |
| MFD pad | D-pad | Multi-function display |

F1 24 swaps radio (RB) and overtake (LB). If your game uses other bindings,
change them in its control settings or edit the layout file.

Layouts are JSON files in `web/layouts/` (positions in percent of the screen).
To preview one in a desktop browser, open
`http://localhost:8765/#preview&layout=f1`.

## Settings

Tap **⚙** on the phone. Changes apply immediately, with a live steering
preview:

| Setting | Default | What it does |
|---|---|---|
| Steering range | 90° | Tilt needed for full lock (lower = more sensitive) |
| Dead zone | 3% | Small tilts around center are ignored |
| Response curve | linear | Above 1 = gentler near center |
| Smoothing | 50% | Filters sensor jitter (time-based, same feel at any send rate) |
| Send rate | 100 Hz | 60 / 100 / 125 / 250 Hz. A wired Xbox pad reports at ~125 Hz |
| Vibrate on press | on | Android only |

Settings are saved on the phone and on the PC (`phones.json` next to
`config.json`). A new browser, or the installed home-screen app, picks up the
last saved settings from the PC.

**Install as an app:** Android Chrome menu → *Install app* / *Add to Home
screen*; iPhone Safari → Share → *Add to Home Screen*. It opens full screen in
landscape.

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

### Linux

On Linux the host creates a virtual Xbox 360 pad through `/dev/uinput` (no
driver to install). Browsers, Steam, SDL games and gamepad testers see it as a
standard Xbox controller. Most desktops already let your user open
`/dev/uinput`; if the host says it can't, it prints the one-time udev rule to
add. Check with `ls -l /dev/uinput` and `getfacl /dev/uinput`.

The window needs tkinter (`sudo apt install python3-tk` on Debian/Ubuntu);
without it the host runs in the console. On macOS the host runs with a
log-only pad that prints what it would send.

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

On Linux, `OPENSTEER_UINPUT_TEST=1 pytest -v tests/test_uinput_real.py` creates
a pad and reads it back from the kernel.

## License

MIT. ViGEmBus (BSD-3) and vgamepad (MIT) are separate projects.
