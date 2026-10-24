# OpenSteer

Turn your phone into a tilt steering wheel for your PC. The phone opens a web
page; the PC host feeds its input to a virtual Xbox 360 controller, so any game
with controller support works. Free and open source, no app or account needed.

Status: Phase 1 (Android over USB). See [plan.md](plan.md) for the roadmap.

## Run (Windows)

1. Install the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases).
2. Install Python 3.11+ and the host dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
3. Put Android [platform-tools](https://developer.android.com/tools/releases/platform-tools)
   in `vendor/platform-tools/` (or have `adb` on PATH).
4. On the phone, enable USB debugging and plug it in. Accept the prompt.
5. Start the host:
   ```
   .venv\Scripts\python -m host.main
   ```
6. Open the printed `http://localhost:8765/?k=...` link on the phone (scan the
   QR code), hold the phone level in landscape and tap **Start**.

Check the controller in `joy.cpl` or https://gamepad-tester.com.

On Linux/macOS the host runs with a log-only pad (prints what it would send),
which is useful for working on the phone app and protocol.

## Options

```
python -m host.main --port 8765 --pad auto|vigem|log --no-adb --new-token -v
```

Settings and the pairing token are stored in `%APPDATA%\OpenSteer\config.json`
(`~/.config/OpenSteer/config.json` elsewhere).

## Development

```
pip install -r requirements-dev.txt
pytest
```

## License

MIT. ViGEmBus (BSD-3) and vgamepad (MIT) are separate projects.
