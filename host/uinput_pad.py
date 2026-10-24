"""Virtual Xbox 360 pad on Linux through /dev/uinput (no extra packages).

The device uses the Xbox 360 USB ids and the same event codes as the kernel's
xpad driver, so browsers, SDL and Steam apply their standard Xbox mapping.
"""

import fcntl
import os
import struct

from .mapper import NEUTRAL

UINPUT = "/dev/uinput"

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BUS_USB = 0x03
VENDOR, PRODUCT, VERSION = 0x045E, 0x028E, 0x0110

ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

# Same codes xpad uses for an Xbox 360 pad.
BUTTON_CODES = {
    "A": 0x130,       # BTN_A / BTN_SOUTH
    "B": 0x131,       # BTN_B / BTN_EAST
    "X": 0x133,       # BTN_X / BTN_NORTH
    "Y": 0x134,       # BTN_Y / BTN_WEST
    "LB": 0x136,      # BTN_TL
    "RB": 0x137,      # BTN_TR
    "BACK": 0x13A,    # BTN_SELECT
    "START": 0x13B,   # BTN_START
    "GUIDE": 0x13C,   # BTN_MODE
    "LS": 0x13D,      # BTN_THUMBL
    "RS": 0x13E,      # BTN_THUMBR
}
# (code, min, max)
AXES = [
    (ABS_X, -32768, 32767), (ABS_Y, -32768, 32767),
    (ABS_RX, -32768, 32767), (ABS_RY, -32768, 32767),
    (ABS_Z, 0, 255), (ABS_RZ, 0, 255),
    (ABS_HAT0X, -1, 1), (ABS_HAT0Y, -1, 1),
]


def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("U") << 8) | nr


_INT = struct.calcsize("i")
_SETUP = struct.Struct("4H80sI")             # struct uinput_setup
_ABS_SETUP = struct.Struct("H2x6i")          # struct uinput_abs_setup
_EVENT = struct.Struct("llHHi")              # struct input_event (64-bit time)

UI_DEV_CREATE = _ioc(0, 1, 0)
UI_DEV_DESTROY = _ioc(0, 2, 0)
UI_DEV_SETUP = _ioc(1, 3, _SETUP.size)
UI_ABS_SETUP = _ioc(1, 4, _ABS_SETUP.size)
UI_SET_EVBIT = _ioc(1, 100, _INT)
UI_SET_KEYBIT = _ioc(1, 101, _INT)
UI_SET_ABSBIT = _ioc(1, 103, _INT)


def available():
    return os.path.exists(UINPUT) and os.access(UINPUT, os.W_OK)


def _clamp16(v):
    return max(-32768, min(32767, v))


class UInputPad:
    """Pad interface (apply/reset/close) backed by a uinput device."""

    def __init__(self, name="OpenSteer virtual pad"):
        self._fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
            for code in BUTTON_CODES.values():
                fcntl.ioctl(self._fd, UI_SET_KEYBIT, code)
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_ABS)
            for code, lo, hi in AXES:
                fcntl.ioctl(self._fd, UI_SET_ABSBIT, code)
                fcntl.ioctl(self._fd, UI_ABS_SETUP, _ABS_SETUP.pack(code, 0, lo, hi, 0, 0, 0))
            fcntl.ioctl(self._fd, UI_DEV_SETUP, _SETUP.pack(
                BUS_USB, VENDOR, PRODUCT, VERSION, name.encode()[:79], 0))
            fcntl.ioctl(self._fd, UI_DEV_CREATE)
        except OSError:
            os.close(self._fd)
            raise
        self._state = NEUTRAL

    def _events(self, state):
        # xpad reports stick Y with down positive; our state has up positive.
        yield EV_ABS, ABS_X, state.lx
        yield EV_ABS, ABS_Y, _clamp16(-state.ly)
        yield EV_ABS, ABS_RX, state.rx
        yield EV_ABS, ABS_RY, _clamp16(-state.ry)
        yield EV_ABS, ABS_Z, state.lt
        yield EV_ABS, ABS_RZ, state.rt
        b = state.buttons
        yield EV_ABS, ABS_HAT0X, ("DPAD_RIGHT" in b) - ("DPAD_LEFT" in b)
        yield EV_ABS, ABS_HAT0Y, ("DPAD_DOWN" in b) - ("DPAD_UP" in b)
        for name, code in BUTTON_CODES.items():
            yield EV_KEY, code, int(name in b)
        yield EV_SYN, SYN_REPORT, 0

    def apply(self, state):
        if state == self._state or self._fd is None:
            return
        # The kernel drops events whose value didn't change, so sending all is fine.
        data = b"".join(_EVENT.pack(0, 0, t, c, v) for t, c, v in self._events(state))
        os.write(self._fd, data)
        self._state = state

    def reset(self):
        self.apply(NEUTRAL)

    def close(self):
        if self._fd is None:
            return
        self.reset()
        try:
            fcntl.ioctl(self._fd, UI_DEV_DESTROY)
        finally:
            os.close(self._fd)
            self._fd = None
