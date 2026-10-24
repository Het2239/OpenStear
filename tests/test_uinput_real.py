"""End-to-end check of the Linux virtual pad: drive it, read it back from the kernel.

Needs Linux with write access to /dev/uinput. Enabled with OPENSTEAR_UINPUT_TEST=1.
"""

import os
import re
import struct
import sys
import time
from pathlib import Path

import pytest

fcntl = pytest.importorskip("fcntl")   # Linux only

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.environ.get("OPENSTEAR_UINPUT_TEST") != "1",
    reason="needs Linux + /dev/uinput (set OPENSTEAR_UINPUT_TEST=1)",
)

_ABSINFO = struct.Struct("6i")


def _ior(nr, size):
    return (2 << 30) | (size << 16) | (ord("E") << 8) | nr


def find_event_node(name, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for block in Path("/proc/bus/input/devices").read_text().split("\n\n"):
            if f'N: Name="{name}"' in block:
                m = re.search(r"H: Handlers=.*?(event\d+)", block)
                if m and os.access(f"/dev/input/{m.group(1)}", os.R_OK):
                    return f"/dev/input/{m.group(1)}", block
        time.sleep(0.05)
    return None, None


def read_abs(fd, code):
    buf = bytearray(_ABSINFO.size)
    fcntl.ioctl(fd, _ior(0x40 + code, _ABSINFO.size), buf)
    return _ABSINFO.unpack(buf)[0]


def read_keys(fd):
    buf = bytearray(96)
    fcntl.ioctl(fd, _ior(0x18, len(buf)), buf)
    return {i for i in range(len(buf) * 8) if buf[i // 8] >> (i % 8) & 1}


def test_virtual_pad_is_seen_by_the_kernel():
    from host.mapper import PadState
    from host.uinput_pad import ABS_HAT0X, ABS_HAT0Y, ABS_RZ, ABS_X, ABS_Y, ABS_Z, UInputPad

    name = f"OpenStear test pad {os.getpid()}"
    pad = UInputPad(name)
    try:
        node, block = find_event_node(name)
        assert node, "virtual pad did not appear in /proc/bus/input/devices"
        assert "Vendor=045e Product=028e" in block
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        try:
            pad.apply(PadState(lx=-20000, ly=12000, lt=40, rt=250,
                               buttons=frozenset({"A", "RB", "DPAD_LEFT", "DPAD_UP"})))
            time.sleep(0.05)
            assert read_abs(fd, ABS_X) == -20000
            assert read_abs(fd, ABS_Y) == -12000        # up is negative on Linux
            assert read_abs(fd, ABS_Z) == 40
            assert read_abs(fd, ABS_RZ) == 250
            assert read_abs(fd, ABS_HAT0X) == -1
            assert read_abs(fd, ABS_HAT0Y) == -1
            assert read_keys(fd) == {0x130, 0x137}        # BTN_A, BTN_TR

            pad.reset()
            time.sleep(0.05)
            assert read_abs(fd, ABS_X) == 0 and read_abs(fd, ABS_RZ) == 0
            assert read_keys(fd) == set()
        finally:
            os.close(fd)
    finally:
        pad.close()
    gone, _ = find_event_node(name, timeout=1.0)
    assert gone is None


# struct ff_effect with an FF_RUMBLE payload: type, id, direction,
# trigger.button, trigger.interval, replay.length, replay.delay, pad,
# strong, weak, rest of the union.
_FF_EFFECT = struct.Struct("HhHHHHH2xHH28x")
EVIOCSFF = (1 << 30) | (48 << 16) | (ord("E") << 8) | 0x80
EVIOCRMFF = (1 << 30) | (4 << 16) | (ord("E") << 8) | 0x81


async def test_rumble_from_a_game_reaches_on_rumble():
    import asyncio

    from host.uinput_pad import EV_FF, FF_RUMBLE, UInputPad, _EVENT

    name = f"OpenStear rumble test {os.getpid()}"
    pad = UInputPad(name)
    seen = []
    pad.on_rumble = lambda strong, weak: seen.append((round(strong, 2), round(weak, 2)))
    try:
        node, _ = await asyncio.to_thread(find_event_node, name)
        fd = os.open(node, os.O_RDWR)
        try:
            # Upload a rumble effect like a game would (blocks until the pad answers,
            # so run it off the event loop thread).
            effect = bytearray(_FF_EFFECT.pack(FF_RUMBLE, -1, 0, 0, 0, 200, 0, 0xC000, 0x4000))
            await asyncio.to_thread(fcntl.ioctl, fd, EVIOCSFF, effect)
            eid = struct.unpack_from("h", effect, 2)[0]
            assert eid >= 0

            os.write(fd, _EVENT.pack(0, 0, EV_FF, eid, 1))      # play
            await asyncio.sleep(0.05)
            assert seen[-1] == (0.75, 0.25)
            await asyncio.sleep(0.3)                            # 200 ms effect ends by itself
            assert seen[-1] == (0.0, 0.0)

            os.write(fd, _EVENT.pack(0, 0, EV_FF, eid, 1))      # play again, then stop early
            await asyncio.sleep(0.05)
            os.write(fd, _EVENT.pack(0, 0, EV_FF, eid, 0))
            await asyncio.sleep(0.05)
            assert seen[-1] == (0.0, 0.0) and seen[-2] == (0.75, 0.25)

            await asyncio.to_thread(fcntl.ioctl, fd, EVIOCRMFF, eid)   # erase
        finally:
            # Closing makes the kernel ask the pad to erase this fd's effects,
            # which the pad answers on the event loop: close off the loop.
            await asyncio.to_thread(os.close, fd)
    finally:
        pad.close()
