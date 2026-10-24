"""Find adb and keep `adb reverse` set up for every connected Android phone."""

import asyncio
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "platform-tools"
POLL_S = 2.0


def find_adb():
    exe = "adb.exe" if sys.platform == "win32" else "adb"
    bundled = VENDOR_DIR / exe
    if bundled.is_file():
        return str(bundled)
    return shutil.which("adb")


def parse_devices(output):
    """Parse `adb devices` output into {serial: state}."""
    devices = {}
    lines = output.splitlines()
    # Skip everything up to the header; adb can print "* daemon ..." lines first.
    for i, line in enumerate(lines):
        if line.startswith("List of devices"):
            lines = lines[i + 1:]
            break
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and not line.startswith("*"):
            devices[parts[0]] = parts[1]
    return devices


# Keep adb from opening a console window when the host runs without one.
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


async def _run(*args):
    """Run a command; returns (exit code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **_NO_WINDOW,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def keep_reversed(port, adb=None, status=None):
    """Poll for devices and run `adb reverse` on each newly connected one.

    If `status` is a dict, it is kept up to date with "adb" (path or None)
    and "devices" ({serial: "ready" | "unauthorized" | other adb state}).
    """
    status = {} if status is None else status
    adb = adb or find_adb()
    status["adb"] = adb
    status["devices"] = {}
    if adb is None:
        log.warning("adb not found; USB (ADB) mode unavailable. Put platform-tools "
                    "in vendor/platform-tools or on PATH.")
        return
    log.info("Using adb at %s", adb)
    reversed_ = set()
    warned = set()
    while True:
        try:
            code, out, _ = await _run(adb, "devices")
        except OSError as e:
            log.warning("Could not run adb: %s", e)
            return
        devices = parse_devices(out) if code == 0 else {}
        for serial, state in devices.items():
            if state == "device" and serial not in reversed_:
                code, out, err = await _run(adb, "-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}")
                if code == 0:
                    reversed_.add(serial)
                    warned.discard(serial)
                    log.info("USB phone %s ready: open http://localhost:%d on it", serial, port)
                else:
                    log.warning("adb reverse failed for %s: %s", serial, (err or out).strip())
            elif state == "unauthorized" and serial not in warned:
                warned.add(serial)
                log.warning("Phone %s: accept the USB debugging prompt on the phone", serial)
        # Forget unplugged phones so they are reversed again on reconnect.
        reversed_ &= {s for s, st in devices.items() if st == "device"}
        status["devices"] = {s: "ready" if s in reversed_ else st for s, st in devices.items()}
        await asyncio.sleep(POLL_S)
