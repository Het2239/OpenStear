"""Virtual pad backends behind one interface, so the driver can be swapped.

`ViGEmPad` drives a real virtual Xbox 360 pad (Windows + ViGEmBus).
`LogPad` prints state changes and is used on other platforms or for testing.
"""

import logging
import sys
import time

from .mapper import NEUTRAL, PadState

log = logging.getLogger(__name__)


class Pad:
    def apply(self, state: PadState):
        raise NotImplementedError

    def reset(self):
        self.apply(NEUTRAL)

    def close(self):
        pass


class ViGEmPad(Pad):
    def __init__(self):
        import vgamepad as vg

        self._vg = vg
        self._pad = vg.VX360Gamepad()
        self._buttons = {
            "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            "DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
            "DPAD_DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
            "DPAD_LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
            "DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
        }

    def apply(self, state):
        p = self._pad
        p.left_joystick(x_value=state.lx, y_value=0)
        p.left_trigger(value=state.lt)
        p.right_trigger(value=state.rt)
        for name, button in self._buttons.items():
            if name in state.buttons:
                p.press_button(button=button)
            else:
                p.release_button(button=button)
        p.update()

    def close(self):
        self.reset()
        # Dropping the last reference unplugs the virtual pad.
        self._pad = None


class LogPad(Pad):
    def __init__(self, name="pad"):
        self.name = name
        self.state = NEUTRAL
        self._last_print = 0.0

    def apply(self, state):
        changed = state != self.state
        self.state = state
        now = time.monotonic()
        # Print at most 10x/sec, but always print a return to neutral.
        if changed and (state == NEUTRAL or now - self._last_print > 0.1):
            self._last_print = now
            log.info(
                "%s lx=%6d lt=%3d rt=%3d btn=%s",
                self.name, state.lx, state.lt, state.rt,
                ",".join(sorted(state.buttons)) or "-",
            )


def vigem_available():
    if sys.platform != "win32":
        return False
    try:
        import vgamepad  # noqa: F401
    except Exception as e:  # vgamepad raises if the ViGEmBus driver is missing
        log.warning("vgamepad unavailable: %s", e)
        return False
    return True


def make_factory(backend="auto"):
    """Return a callable(name) -> Pad for the chosen backend."""
    if backend == "auto":
        backend = "vigem" if vigem_available() else "log"
    if backend == "vigem":
        log.info("Using ViGEmBus virtual Xbox 360 pads")
        return lambda name: ViGEmPad()
    log.info("Using log-only pads (no virtual controller)")
    return LogPad
