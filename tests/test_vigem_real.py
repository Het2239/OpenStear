"""End-to-end check of the real virtual pad: drive it, read it back via XInput.

Needs Windows with the ViGEmBus driver. Enabled with OPENSTEER_VIGEM_TEST=1
(CI sets it after installing the driver).
"""

import ctypes
import os
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("OPENSTEER_VIGEM_TEST") != "1",
    reason="needs Windows + ViGEmBus (set OPENSTEER_VIGEM_TEST=1)",
)


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]


def read_pads():
    xinput = ctypes.windll.xinput1_4
    pads = {}
    for i in range(4):
        st = XINPUT_STATE()
        if xinput.XInputGetState(i, ctypes.byref(st)) == 0:
            g = st.Gamepad
            pads[i] = (g.wButtons, g.bLeftTrigger, g.bRightTrigger, g.sThumbLX)
    return pads


def wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = pred()
        if result:
            return result
        time.sleep(0.05)
    return pred()


def test_virtual_pad_is_seen_by_xinput():
    from host.gamepad import ViGEmPad
    from host.mapper import PadState

    before = read_pads()
    pad = ViGEmPad()
    try:
        state = PadState(lx=-20000, lt=40, rt=250, buttons=frozenset({"A", "RB"}))
        pad.apply(state)
        expected = (0x1000 | 0x0200, 40, 250, -20000)
        slot = wait_for(lambda: next(
            (i for i, v in read_pads().items() if v == expected and i not in before), None))
        assert slot is not None, f"pad not visible via XInput: {read_pads()}"

        pad.reset()
        assert wait_for(lambda: read_pads().get(slot) == (0, 0, 0, 0))
    finally:
        pad.close()
        del pad
    assert wait_for(lambda: slot not in read_pads())
