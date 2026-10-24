"""Virtual pad backends behind one interface, so the driver can be swapped.

`ViGEmPad` drives a real virtual Xbox 360 pad (Windows + ViGEmBus).
`UInputPad` (uinput_pad.py) does the same on Linux through /dev/uinput.
`LogPad` prints state changes; used when neither is available, or for testing.
"""

import asyncio
import logging
import sys
import time

from .mapper import NEUTRAL, PadState

log = logging.getLogger(__name__)


class Pad:
    # Set by the server: called with (strong, weak) motor strengths, 0..1,
    # when a game rumbles this pad. Backends that can't receive rumble never call it.
    on_rumble = None

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
            "LS": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
            "RS": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
            "GUIDE": vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
        }

        self._state = NEUTRAL  # VX360Gamepad() starts with a neutral report
        self._register_rumble()

    def _register_rumble(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        # ViGEm calls this on its own thread with motor values 0..255. vgamepad
        # checks the parameter names, so they must match its dummy_callback.
        def notify(client, target, large_motor, small_motor, led_number, user_data):
            loop.call_soon_threadsafe(self._rumble, large_motor / 255, small_motor / 255)

        try:
            self._pad.register_notification(callback_function=notify)
            self._notify = notify  # keep a reference alive
        except Exception as e:
            log.warning("Rumble from games unavailable: %s", e)

    def _rumble(self, strong, weak):
        if self.on_rumble is not None and self._pad is not None:
            self.on_rumble(strong, weak)

    def apply(self, state):
        if state == self._state or self._pad is None:
            return
        p = self._pad
        p.left_joystick(x_value=state.lx, y_value=state.ly)
        p.right_joystick(x_value=state.rx, y_value=state.ry)
        p.left_trigger(value=state.lt)
        p.right_trigger(value=state.rt)
        for name, button in self._buttons.items():
            if name in state.buttons:
                p.press_button(button=button)
            else:
                p.release_button(button=button)
        p.update()
        self._state = state

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
                "%s L=(%6d,%6d) R=(%6d,%6d) lt=%3d rt=%3d btn=%s",
                self.name, state.lx, state.ly, state.rx, state.ry, state.lt, state.rt,
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


UINPUT_HELP = (
    "Cannot open /dev/uinput, so no virtual controller on Linux. Allow it with:\n"
    "  echo 'KERNEL==\"uinput\", SUBSYSTEM==\"misc\", TAG+=\"uaccess\", OPTIONS+=\"static_node=uinput\"' "
    "| sudo tee /etc/udev/rules.d/60-opensteer-uinput.rules\n"
    "  sudo modprobe uinput && sudo udevadm control --reload && sudo udevadm trigger\n"
    "then log out and back in. Running with --pad log for now."
)


def make_factory(backend="auto"):
    """Return a callable(name) -> Pad for the chosen backend."""
    if backend == "auto":
        if sys.platform == "win32":
            backend = "vigem" if vigem_available() else "log"
        elif sys.platform.startswith("linux"):
            from . import uinput_pad
            if uinput_pad.available():
                backend = "uinput"
            else:
                log.warning(UINPUT_HELP)
                backend = "log"
        else:
            backend = "log"
    if backend == "vigem":
        log.info("Using ViGEmBus virtual Xbox 360 pads")
        return lambda name: ViGEmPad()
    if backend == "uinput":
        from .uinput_pad import UInputPad
        log.info("Using uinput virtual Xbox 360 pads")
        return lambda name: UInputPad(f"OpenSteer virtual pad ({name})")
    log.info("Using log-only pads (no virtual controller)")
    return LogPad
