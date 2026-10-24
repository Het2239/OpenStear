"""Keyboard output for controls mapped to keys.

Windows: SendInput with hardware scan codes, which games that read the
keyboard directly (DirectInput / raw input) also see. Linux: a uinput virtual
keyboard. Elsewhere, or without access: keys are only logged.

There is one keyboard for all phones; `Keyboard.set(owner, keys)` records the
keys each phone holds and presses/releases the union.
"""

import ctypes
import logging
import os
import sys

from .keys import KEYS

log = logging.getLogger(__name__)


class Keyboard:
    def __init__(self, backend):
        self._backend = backend
        self._held = {}           # owner -> frozenset of key names
        self._down = frozenset()  # keys currently pressed on the backend

    def set(self, owner, keys):
        keys = frozenset(k for k in keys if k in KEYS)
        if keys:
            self._held[owner] = keys
        else:
            self._held.pop(owner, None)
        want = frozenset().union(*self._held.values()) if self._held else frozenset()
        release, press = self._down - want, want - self._down
        if release or press:
            self._backend.send(press, release)
            self._down = want

    def close(self):
        self._held.clear()
        if self._down:
            self._backend.send(frozenset(), self._down)
            self._down = frozenset()
        self._backend.close()


class LogKeys:
    def send(self, press, release):
        log.info("keys down %s up %s", ",".join(sorted(press)) or "-", ",".join(sorted(release)) or "-")

    def close(self):
        pass


# --- Windows -------------------------------------------------------------------

if sys.platform == "win32":
    from ctypes import wintypes

    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        # MOUSEINPUT is the largest member; it sets the size SendInput expects.
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class WinKeys:
    def __init__(self):
        self._send = ctypes.windll.user32.SendInput

    def send(self, press, release):
        events = [(k, True) for k in sorted(release)] + [(k, False) for k in sorted(press)]
        arr = (INPUT * len(events))()
        for i, (name, up) in enumerate(events):
            sc, ext, _ = KEYS[name]
            flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0) | (KEYEVENTF_KEYUP if up else 0)
            arr[i].type = INPUT_KEYBOARD
            arr[i].u.ki = KEYBDINPUT(0, sc, flags, 0, 0)
        sent = self._send(len(events), arr, ctypes.sizeof(INPUT))
        if sent != len(events):
            log.warning("SendInput sent %d of %d key events (blocked by a program running as admin?)",
                        sent, len(events))

    def close(self):
        pass


# --- Linux ---------------------------------------------------------------------

class UInputKeys:
    def __init__(self, name="OpenSteer virtual keyboard"):
        import fcntl

        from . import uinput_pad as u

        self._u = u
        self._fd = os.open(u.UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self._fd, u.UI_SET_EVBIT, u.EV_KEY)
            for _, _, code in KEYS.values():
                fcntl.ioctl(self._fd, u.UI_SET_KEYBIT, code)
            fcntl.ioctl(self._fd, u.UI_DEV_SETUP, u._SETUP.pack(
                u.BUS_USB, 0x1209, 0x0057, 1, name.encode()[:79], 0))
            fcntl.ioctl(self._fd, u.UI_DEV_CREATE)
        except OSError:
            os.close(self._fd)
            raise

    def send(self, press, release):
        u = self._u
        ev = [(u.EV_KEY, KEYS[k][2], 0) for k in sorted(release)]
        ev += [(u.EV_KEY, KEYS[k][2], 1) for k in sorted(press)]
        ev.append((u.EV_SYN, u.SYN_REPORT, 0))
        os.write(self._fd, b"".join(u._EVENT.pack(0, 0, t, c, v) for t, c, v in ev))

    def close(self):
        import fcntl

        if self._fd is not None:
            try:
                fcntl.ioctl(self._fd, self._u.UI_DEV_DESTROY)
            finally:
                os.close(self._fd)
                self._fd = None


def make_keyboard(backend="auto"):
    """A Keyboard with the best backend for this machine."""
    if backend == "auto":
        if sys.platform == "win32":
            backend = "win"
        elif sys.platform.startswith("linux"):
            from .uinput_pad import available
            backend = "uinput" if available() else "log"
        else:
            backend = "log"
    try:
        if backend == "win":
            return Keyboard(WinKeys())
        if backend == "uinput":
            return Keyboard(UInputKeys())
    except OSError as e:
        log.warning("Keyboard output unavailable (%s); keys will only be logged", e)
    return Keyboard(LogKeys())
