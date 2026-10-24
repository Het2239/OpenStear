"""Virtual Xbox 360 pad on Linux through /dev/uinput (no extra packages).

The device uses the Xbox 360 USB ids and the same event codes as the kernel's
xpad driver, so browsers, SDL and Steam apply their standard Xbox mapping.

It also accepts rumble (force feedback): games upload FF_RUMBLE effects and
play them; we answer the kernel's upload/erase requests and report the motor
strengths through `on_rumble(strong, weak)`, each 0..1.
"""

import asyncio
import errno
import fcntl
import logging
import os
import struct

from .mapper import NEUTRAL

UINPUT = "/dev/uinput"

log = logging.getLogger(__name__)

EV_SYN, EV_KEY, EV_ABS, EV_FF, EV_UINPUT = 0x00, 0x01, 0x03, 0x15, 0x0101
SYN_REPORT = 0
UI_FF_UPLOAD, UI_FF_ERASE = 1, 2
FF_RUMBLE, FF_GAIN = 0x50, 0x60
FF_EFFECTS_MAX = 16
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
# struct uinput_ff_upload: request_id, retval, then struct ff_effect (48 bytes)
# at offset 8 and the old effect at 56. In ff_effect: type @0, id @2,
# replay.length @10, and for FF_RUMBLE strong/weak magnitude @16/@18.
_FF_UPLOAD_SIZE, _FF_EFFECT_OFF = 104, 8
_FF_ERASE = struct.Struct("IiI")             # struct uinput_ff_erase

UI_DEV_CREATE = _ioc(0, 1, 0)
UI_DEV_DESTROY = _ioc(0, 2, 0)
UI_DEV_SETUP = _ioc(1, 3, _SETUP.size)
UI_ABS_SETUP = _ioc(1, 4, _ABS_SETUP.size)
UI_SET_EVBIT = _ioc(1, 100, _INT)
UI_SET_KEYBIT = _ioc(1, 101, _INT)
UI_SET_ABSBIT = _ioc(1, 103, _INT)
UI_SET_FFBIT = _ioc(1, 107, _INT)
UI_BEGIN_FF_UPLOAD = _ioc(3, 200, _FF_UPLOAD_SIZE)
UI_END_FF_UPLOAD = _ioc(1, 201, _FF_UPLOAD_SIZE)
UI_BEGIN_FF_ERASE = _ioc(3, 202, _FF_ERASE.size)
UI_END_FF_ERASE = _ioc(1, 203, _FF_ERASE.size)


def available():
    return os.path.exists(UINPUT) and os.access(UINPUT, os.W_OK)


def _clamp16(v):
    return max(-32768, min(32767, v))


class UInputPad:
    """Pad interface (apply/reset/close) backed by a uinput device."""

    def __init__(self, name="OpenStear virtual pad"):
        self.on_rumble = None
        self._effects = {}       # effect id -> (strong, weak, length ms), magnitudes 0..1
        self._gain = 1.0
        self._playing = None     # effect id currently driving the motors
        self._stop_timer = None
        self._loop = None
        # Read/write: rumble requests from games arrive on this same fd.
        self._fd = os.open(UINPUT, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
            for code in BUTTON_CODES.values():
                fcntl.ioctl(self._fd, UI_SET_KEYBIT, code)
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_ABS)
            for code, lo, hi in AXES:
                fcntl.ioctl(self._fd, UI_SET_ABSBIT, code)
                fcntl.ioctl(self._fd, UI_ABS_SETUP, _ABS_SETUP.pack(code, 0, lo, hi, 0, 0, 0))
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_FF)
            fcntl.ioctl(self._fd, UI_SET_FFBIT, FF_RUMBLE)
            fcntl.ioctl(self._fd, UI_SET_FFBIT, FF_GAIN)
            fcntl.ioctl(self._fd, UI_DEV_SETUP, _SETUP.pack(
                BUS_USB, VENDOR, PRODUCT, VERSION, name.encode()[:79], FF_EFFECTS_MAX))
            fcntl.ioctl(self._fd, UI_DEV_CREATE)
        except OSError:
            os.close(self._fd)
            raise
        self._state = NEUTRAL
        try:
            self._loop = asyncio.get_running_loop()
            self._loop.add_reader(self._fd, self._read)
        except RuntimeError:
            pass  # no event loop (e.g. a quick test): rumble requests go unanswered

    # --- rumble ------------------------------------------------------------

    def _read(self):
        while self._fd is not None:
            try:
                data = os.read(self._fd, _EVENT.size * 32)
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                    log.warning("uinput read failed: %s", e)
                return
            for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                _, _, etype, code, value = _EVENT.unpack_from(data, off)
                try:
                    if etype == EV_UINPUT and code == UI_FF_UPLOAD:
                        self._upload(value)
                    elif etype == EV_UINPUT and code == UI_FF_ERASE:
                        self._erase(value)
                    elif etype == EV_FF:
                        self._play(code, value)
                except OSError as e:
                    log.warning("rumble request failed: %s", e)

    def _upload(self, request_id):
        buf = bytearray(_FF_UPLOAD_SIZE)
        struct.pack_into("I", buf, 0, request_id)
        fcntl.ioctl(self._fd, UI_BEGIN_FF_UPLOAD, buf)
        etype, eid = struct.unpack_from("Hh", buf, _FF_EFFECT_OFF)
        length = struct.unpack_from("H", buf, _FF_EFFECT_OFF + 10)[0]
        if etype == FF_RUMBLE:
            strong, weak = struct.unpack_from("HH", buf, _FF_EFFECT_OFF + 16)
            self._effects[eid] = (strong / 0xFFFF, weak / 0xFFFF, length)
            retval = 0
        else:
            retval = -errno.EINVAL
        struct.pack_into("i", buf, 4, retval)
        fcntl.ioctl(self._fd, UI_END_FF_UPLOAD, buf)

    def _erase(self, request_id):
        buf = bytearray(_FF_ERASE.pack(request_id, 0, 0))
        fcntl.ioctl(self._fd, UI_BEGIN_FF_ERASE, buf)
        _, _, eid = _FF_ERASE.unpack(buf)
        self._effects.pop(eid, None)
        if self._playing == eid:
            self._rumble(None)
        fcntl.ioctl(self._fd, UI_END_FF_ERASE, _FF_ERASE.pack(request_id, 0, eid))

    def _play(self, code, value):
        if code == FF_GAIN:
            self._gain = value / 0xFFFF
            return
        effect = self._effects.get(code)
        if effect is None:
            return
        if value > 0:
            self._rumble(code)
            length = effect[2]
            if length and self._loop is not None:
                self._stop_timer = self._loop.call_later(length / 1000, self._rumble, None)
        elif self._playing == code:
            self._rumble(None)

    def _rumble(self, eid):
        if self._stop_timer is not None:
            self._stop_timer.cancel()
            self._stop_timer = None
        self._playing = eid
        strong, weak = (0.0, 0.0) if eid is None else self._effects[eid][:2]
        if self.on_rumble is not None:
            self.on_rumble(strong * self._gain, weak * self._gain)

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
        if self._stop_timer is not None:
            self._stop_timer.cancel()
        if self._loop is not None:
            try:
                self._loop.remove_reader(self._fd)
            except (RuntimeError, ValueError):
                pass
        try:
            fcntl.ioctl(self._fd, UI_DEV_DESTROY)
        finally:
            os.close(self._fd)
            self._fd = None
