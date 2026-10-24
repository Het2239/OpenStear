"""ViGEmPad against a fake vgamepad module, so it runs on any OS.

tests/test_vigem_real.py checks the real driver on Windows.
"""

import sys
import types
from enum import IntFlag

import pytest

from host.gamepad import ViGEmPad
from host.mapper import NEUTRAL, PadState


class XUSB_BUTTON(IntFlag):
    XUSB_GAMEPAD_DPAD_UP = 0x0001
    XUSB_GAMEPAD_DPAD_DOWN = 0x0002
    XUSB_GAMEPAD_DPAD_LEFT = 0x0004
    XUSB_GAMEPAD_DPAD_RIGHT = 0x0008
    XUSB_GAMEPAD_START = 0x0010
    XUSB_GAMEPAD_BACK = 0x0020
    XUSB_GAMEPAD_LEFT_THUMB = 0x0040
    XUSB_GAMEPAD_RIGHT_THUMB = 0x0080
    XUSB_GAMEPAD_LEFT_SHOULDER = 0x0100
    XUSB_GAMEPAD_RIGHT_SHOULDER = 0x0200
    XUSB_GAMEPAD_GUIDE = 0x0400
    XUSB_GAMEPAD_A = 0x1000
    XUSB_GAMEPAD_B = 0x2000
    XUSB_GAMEPAD_X = 0x4000
    XUSB_GAMEPAD_Y = 0x8000


class FakeX360:
    def __init__(self):
        self.buttons = 0
        self.lx = self.ly = self.rx = self.ry = self.lt = self.rt = 0
        self.updates = []

    def press_button(self, button):
        self.buttons |= button

    def release_button(self, button):
        self.buttons &= ~button

    def left_joystick(self, x_value, y_value):
        self.lx, self.ly = x_value, y_value

    def right_joystick(self, x_value, y_value):
        self.rx, self.ry = x_value, y_value

    def left_trigger(self, value):
        self.lt = value

    def right_trigger(self, value):
        self.rt = value

    def update(self):
        self.updates.append((self.buttons, self.lx, self.lt, self.rt))
        self.sticks = (self.lx, self.ly, self.rx, self.ry)


@pytest.fixture
def fake_vgamepad(monkeypatch):
    mod = types.ModuleType("vgamepad")
    mod.XUSB_BUTTON = XUSB_BUTTON
    mod.VX360Gamepad = FakeX360
    monkeypatch.setitem(sys.modules, "vgamepad", mod)
    return mod


def test_apply_sends_report(fake_vgamepad):
    pad = ViGEmPad()
    pad.apply(PadState(lx=-32768, lt=10, rt=255, buttons=frozenset({"A", "LB", "DPAD_LEFT"})))
    buttons, lx, lt, rt = pad._pad.updates[-1]
    assert buttons == XUSB_BUTTON.XUSB_GAMEPAD_A | XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER \
        | XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
    assert (lx, lt, rt) == (-32768, 10, 255)


def test_reset_releases_everything(fake_vgamepad):
    pad = ViGEmPad()
    pad.apply(PadState(lx=100, rt=200, buttons=frozenset({"B"})))
    pad.reset()
    assert pad._pad.updates[-1] == (0, 0, 0, 0)


def test_unchanged_state_is_not_resent(fake_vgamepad):
    pad = ViGEmPad()
    pad.apply(NEUTRAL)
    assert pad._pad.updates == []
    s = PadState(rt=5)
    pad.apply(s)
    pad.apply(s)
    assert len(pad._pad.updates) == 1


def test_close_unplugs(fake_vgamepad):
    pad = ViGEmPad()
    pad.apply(PadState(rt=5))
    raw = pad._pad
    pad.close()
    assert raw.updates[-1] == (0, 0, 0, 0)
    assert pad._pad is None
    pad.apply(PadState(rt=9))  # must not raise after close


def test_sticks_and_extra_buttons(fake_vgamepad):
    pad = ViGEmPad()
    pad.apply(PadState(lx=1, ly=2, rx=3, ry=-4, buttons=frozenset({"LS", "RS", "GUIDE"})))
    assert pad._pad.sticks == (1, 2, 3, -4)
    assert pad._pad.buttons == XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB \
        | XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB | XUSB_BUTTON.XUSB_GAMEPAD_GUIDE
