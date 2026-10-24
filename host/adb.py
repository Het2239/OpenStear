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
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices[parts[0]] = parts[1]
    return devices


async def _run(*args):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace")


async def keep_reversed(port, adb=None):
    """Poll for devices and run `adb reverse` on each newly connected one."""
    adb = adb or find_adb()
    if adb is None:
        log.warning("adb not found; USB (ADB) mode unavailable. Put platform-tools "
                    "in vendor/platform-tools or on PATH.")
        return
    log.info("Using adb at %s", adb)
    reversed_ = set()
    warned = set()
    while True:
        code, out = await _run(adb, "devices")
        devices = parse_devices(out) if code == 0 else {}
        for serial, state in devices.items():
            if state == "device" and serial not in reversed_:
                code, out = await _run(adb, "-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}")
                if code == 0:
                    reversed_.add(serial)
                    warned.discard(serial)
                    log.info("USB phone %s ready: open http://localhost:%d on it", serial, port)
                else:
                    log.warning("adb reverse failed for %s: %s", serial, out.strip())
            elif state == "unauthorized" and serial not in warned:
                warned.add(serial)
                log.warning("Phone %s: accept the USB debugging prompt on the phone", serial)
        # Forget unplugged phones so they are reversed again on reconnect.
        reversed_ &= {s for s, st in devices.items() if st == "device"}
        await asyncio.sleep(POLL_S)
