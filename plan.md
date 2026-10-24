# Plan: Open-Source Phone Steering Wheel / PC Controller

> Working name: **OpenWheel** (placeholder, pick your own). Do not use the names, logos, screenshots or artwork of RojX or Tilt Wheel Controller. We are rebuilding the *idea and features*, with our own code and design.

## 1. What we are building

A phone turns into a game controller for a Windows PC:

- **Phone side:** a web app (PWA) that opens in the phone's browser. It reads the phone's tilt for steering and shows touch controls (pedals, buttons, shifter).
- **PC side:** a small host app that serves that web app, shows a QR code to connect, receives the phone's input and feeds it to a **virtual Xbox 360 controller**, so any game that supports a controller works.

No app store, no account, no activation. Free and open source.

### Connection modes

| Mode | Phones | How | HTTPS needed? |
|---|---|---|---|
| **USB (ADB)** | Android | `adb reverse` forwards the port over the cable; phone opens `http://localhost:PORT` | No (localhost counts as secure) |
| **USB (tethering)** | Android + iPhone | Phone's USB tethering / Personal Hotspot creates a network over the cable | Yes |
| **Wi-Fi** | Android + iPhone | Phone and PC on the same network | Yes |

Build order: USB (ADB) first, then Wi-Fi, then tethering.

## 2. Architecture

```
┌──────────────── Phone (browser / PWA) ────────────────┐
│  Sensors (devicemotion) → tilt angle                  │
│  Touch controls → throttle, brake, buttons            │
│  State packet sent ~100x/sec over WebSocket           │
└────────────────────────┬──────────────────────────────┘
                         │ USB (adb reverse) / tethering / Wi-Fi
┌────────────────────────▼──────────────────────────────┐
│  PC Host (Python)                                     │
│  ├─ HTTP(S) server: serves the phone web app          │
│  ├─ WebSocket server: receives input packets          │
│  ├─ Mapper: sensitivity, dead zone, curves, remaps    │
│  ├─ Virtual pad: vgamepad → ViGEmBus → Xbox 360 pad   │
│  ├─ Keyboard output (for keys mapped to buttons)      │
│  ├─ ADB manager: detect phone, run adb reverse        │
│  ├─ Telemetry (later): F1 UDP → forward to phone dash │
│  └─ Small desktop window: QR code, status, settings   │
└───────────────────────────────────────────────────────┘
```

## 3. Tech stack and references

### PC host

| Need | Choice | Reference |
|---|---|---|
| Language | Python 3.11+ | https://www.python.org |
| Virtual Xbox controller (driver) | ViGEmBus (BSD-3). No longer actively developed, but stable and widely used | https://github.com/nefarius/ViGEmBus |
| Python bindings for the driver | `vgamepad` (MIT) | https://github.com/yannbouteiller/vgamepad |
| Web + WebSocket server | `aiohttp` (one library for both) | https://docs.aiohttp.org |
| QR code | `qrcode` + `Pillow` | https://pypi.org/project/qrcode/ |
| Keyboard output | `pydirectinput` (sends scan codes that games read) | https://pypi.org/project/PyDirectInput/ |
| USB connection | Android Platform Tools (`adb`), bundled with the app | https://developer.android.com/tools/releases/platform-tools |
| Local HTTPS certs | Generate with `cryptography` in Python, mkcert as reference for the approach | https://github.com/FiloSottile/mkcert |
| Desktop window | `tkinter` to start (built in); can move to PySide6 later | https://docs.python.org/3/library/tkinter.html |
| Packaging | PyInstaller → single folder; Inno Setup → installer that also installs ViGEmBus | https://pyinstaller.org , https://jrsoftware.org/isinfo.php |

### Phone web app

| Need | Choice | Reference |
|---|---|---|
| UI | Plain HTML/CSS/JS to start (no build step), canvas or DOM controls | — |
| Tilt | `devicemotion` (`accelerationIncludingGravity`) and `deviceorientation` | https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent |
| iPhone sensor permission | `DeviceMotionEvent.requestPermission()` on a button tap | https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent/requestPermission_static |
| Secure context rules | Why sensors need HTTPS or localhost | https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts |
| Landscape lock / fullscreen | Screen Orientation API + Fullscreen API (Android) | https://developer.mozilla.org/en-US/docs/Web/API/Screen_Orientation_API |
| Keep screen on | Screen Wake Lock API | https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API |
| Haptics | Vibration API (Android only) | https://developer.mozilla.org/en-US/docs/Web/API/Vibration_API |
| Installable app | Web app manifest + service worker | https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps |

### Telemetry (phase 6)

- F1 games (F1 23/24/25) send UDP telemetry when enabled in the game's settings (default port 20777). EA/Codemasters publish the packet format spec on their F1 forums each year; search "F1 25 UDP specification".
- Other games later: Assetto Corsa (shared memory), Forza (UDP "Data Out"), BeamNG (OutGauge UDP).

## 4. Repo structure

```
openwheel/
├─ host/
│  ├─ main.py              # entry point, starts everything
│  ├─ server.py            # aiohttp: static files + /ws WebSocket
│  ├─ gamepad.py           # vgamepad wrapper, neutral/reset logic
│  ├─ mapper.py            # dead zone, sensitivity, curves, remapping
│  ├─ keyboard_out.py      # key output for remapped buttons
│  ├─ adb.py               # find adb, list devices, adb reverse
│  ├─ network.py           # list local IPs, detect tethering interface
│  ├─ certs.py             # generate/load local HTTPS cert
│  ├─ ui.py                # tkinter window: QR, status, mode picker
│  ├─ config.py            # load/save settings JSON
│  └─ telemetry/           # phase 6
├─ web/                    # phone app, served by host
│  ├─ index.html
│  ├─ app.js               # connection, packet loop
│  ├─ sensors.js           # tilt reading + calibration
│  ├─ controls/            # wheel, slider, button, shifter components
│  ├─ layouts/             # preset layouts as JSON
│  ├─ manifest.json
│  └─ sw.js
├─ vendor/platform-tools/  # bundled adb (not committed; fetched by build script)
├─ installer/              # Inno Setup script
├─ docs/
├─ LICENSE                 # MIT suggested
└─ README.md
```

## 5. Protocol (phone → PC)

Send the **full state** every frame, not individual press/release events. If a packet is lost, the next one fixes it.

Start with JSON (easy to debug), switch to binary later if needed.

```json
{
  "t": "s",          // type: state
  "seq": 1042,       // sequence number, host drops older packets
  "lx": -0.31,       // left stick X = steering, -1.0 (full left) .. 1.0, already calibrated
  "ly": 0.0,         // left stick Y, +1 is up
  "rx": 0.0,         // right stick, -1..1
  "ry": 0.0,
  "lt": 0.0,         // left trigger = brake, 0..1
  "rt": 0.80,        // right trigger = throttle, 0..1
  "btn": 5           // bitmask of Xbox buttons, bit order in host/mapper.py DEFAULT_BUTTONS
}
```

The host also accepts `steer`/`thr`/`brk` as names for `lx`/`rt`/`lt`.

Other messages: `hello` (with pairing token and layout id), `ping`/`pong` (measure latency, shown in the UI), `config` (PC → phone: settings), `tele` (PC → phone: telemetry).

Binary version later: 1 byte type, 2 bytes seq, 3 × int16 axes, 4 bytes button mask = 13 bytes.

### Rules on the host

- **Pairing token:** the QR URL includes a random token (`?k=...`). Connections without it are rejected, so nobody else on the network can control the PC.
- **Failsafe:** if no packet arrives for 300 ms, set all axes to neutral and release all buttons. A dropped connection must never leave the throttle stuck on.
- **One controller per phone:** each phone gets its own virtual pad (vgamepad supports several).

### Default mapping (Xbox 360)

| Phone input | Xbox output | Range |
|---|---|---|
| Steering | Left stick X | -32768 .. 32767 |
| Throttle | Right trigger | 0 .. 255 |
| Brake | Left trigger | 0 .. 255 |
| Buttons | A, B, X, Y, LB, RB, Back, Start, D-pad | on/off |

## 6. Tilt steering: how to compute it

Phone is held in landscape like a wheel.

1. Read gravity from `devicemotion` → `accelerationIncludingGravity` (x, y).
2. Angle = `atan2(x, y)` (swap/negate axes depending on landscape-left vs landscape-right, read from `screen.orientation.angle`).
3. **Calibrate:** a "Center" button stores the current angle as zero.
4. **Steering range:** angle ÷ max angle (e.g. 90°) → -1..1, clamp.
5. **Dead zone:** values below e.g. 0.03 become 0, rescale the rest.
6. **Curve:** `sign(v) * |v|^gamma` (gamma 1.0 = linear, >1 = gentler near center).
7. **Smoothing:** exponential moving average, `s = s + a * (v - s)`, `a` from settings.

Do steps 3–7 on the phone so the dash shows exactly what is sent. The host only scales to Xbox ranges.

## 7. Build phases

### Phase 1: MVP over USB (Android)
- [x] Host: aiohttp serves `web/`, WebSocket at `/ws`
- [x] Host: vgamepad virtual pad, apply state packets, 300 ms failsafe
- [x] Host: find `adb`, detect device, run `adb reverse tcp:PORT tcp:PORT`, re-run when phone reconnects
- [x] Host: print URL + show QR (console is fine at first)
- [x] Phone: landscape page with tilt steering, throttle and brake sliders, 4 buttons
- [x] Phone: send state at ~100 Hz with `requestAnimationFrame` + timer fallback
- [x] Phone: live readout (steer, throttle, brake, connection, ping)

**Done when:** steering a car in BeamNG/Forza/Assetto Corsa works over USB, and unplugging the cable releases all inputs.

### Phase 2: Wi-Fi and tethering
- [x] Generate a local CA + cert for the PC's IPs; serve HTTPS
- [x] Guided "trust certificate" page for Android and iPhone
- [x] iPhone: "Tap to enable motion" button calling `requestPermission()`
- [x] List network interfaces; detect a tethering interface and prefer it in USB-tethering mode
- [x] Mode picker in host UI: USB (ADB) / USB (tethering) / Wi-Fi; QR updates per mode
- [x] Auto-reconnect on the phone with backoff

**Done when:** an iPhone steers over Wi-Fi and over Personal Hotspot USB.

### Phase 3: Tuning and settings
- [x] Settings screen on phone: range, dead zone, curve, smoothing, send rate (60/100/125/250 Hz), vibration
- [x] Calibrate/center button
- [x] Settings saved on phone (localStorage) and on host (JSON)
- [x] Wake Lock, fullscreen, PWA install (add to Home Screen)

### Phase 4: Layouts
- [x] Layout format as JSON: list of controls with type, position, size, mapping
- [x] Presets: Classic wheel, F1 wheel, F1 simple, Touch wheel, Arcade, Xbox style, PlayStation style
- [x] Alternative steering: on-screen wheel (with configurable rotation, e.g. 900°, and auto-centre) and hold ◀ / ▶ buttons
- [x] Drag-and-drop editor: move, resize, add, delete controls; save as custom layout
- [x] Page switcher: several layouts, switch mid-game (on foot / car / plane)
- [x] Import/export layouts as files so people can share them

### Phase 5: Remapping
- [x] Each control maps to any Xbox button, axis, or keyboard key
- [x] Modes: Normal (hold), Toggle, Pulse (one short press)
- [x] Host UI to manage profiles per game

### Phase 6: Telemetry and dash
- [ ] Host listens on UDP 20777, parses F1 packets (car telemetry, lap data, car status)
- [ ] Forward a small summary to the phone ~20 Hz: gear, speed, RPM, lap time, fuel, tyres, ERS
- [ ] Dash widget on phone; vibrate faster as RPM rises (Android)
- [x] Game rumble → phone vibration (ViGEmBus notifications on Windows, uinput force feedback on Linux)
- [ ] Optional: understeer/oversteer estimate per lap from steering vs yaw rate

### Phase 7: Packaging and release
- [ ] PyInstaller build including `web/` and `adb`
- [ ] Inno Setup installer: installs app, installs ViGEmBus if missing, firewall rule for the port
- [ ] GitHub Actions: build installer on each tag, attach to release
- [ ] README with setup steps, GIFs, troubleshooting (USB debugging, cert trust, firewall)

## 8. Testing checklist

- Latency: show round-trip ping in UI; target < 15 ms on USB, < 30 ms on Wi-Fi
- Check the virtual pad with Windows "Set up USB game controllers" (`joy.cpl`) and https://gamepad-tester.com
- Games to test: BeamNG.drive, Assetto Corsa, Forza Horizon, Euro Truck Simulator 2, F1 (for telemetry)
- Phones: one Android (Chrome), one iPhone (Safari), both orientations
- Failure cases: cable unplugged, Wi-Fi drop, phone locks, app in background, two phones at once

## 9. Known risks

| Risk | Plan |
|---|---|
| ViGEmBus is retired | Still works on Windows 10/11; keep the gamepad code behind one interface (`gamepad.py`) so the driver can be swapped later |
| Sensors need HTTPS | Use USB-ADB (localhost) first; ship a clear cert-trust guide for Wi-Fi |
| Browser throttles background tabs | Wake Lock + warning when page is hidden; host failsafe resets inputs |
| Some games read DirectInput only | Most modern games read XInput; document exceptions |
| Users without USB debugging | Offer tethering and Wi-Fi modes, with step-by-step screens |

## 10. License

MIT for our code. ViGEmBus is BSD-3 and vgamepad is MIT, both compatible. Include their license files when bundling. `adb` is distributed under Google's platform-tools terms; check them before bundling, or have the installer download it.