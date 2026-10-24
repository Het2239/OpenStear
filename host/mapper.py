"""Turn phone state packets into Xbox 360 pad values.

Steering curves, dead zone and smoothing are applied on the phone, so the
host only clamps and scales to Xbox ranges.

Packet axes (all optional, missing = 0):
  lx, ly, rx, ry   sticks, -1..1, +y is up
  lt, rt           triggers, 0..1
  steer, thr, brk  wheel names for lx, rt, lt (used when lx/rt/lt are absent)
"""

from dataclasses import dataclass, field

# Control index on the phone -> Xbox button. Bit i of the packet's "btn" mask
# is button i. web/controls.js has the same list; tests check they match.
DEFAULT_BUTTONS = [
    "A", "B", "X", "Y",
    "LB", "RB", "BACK", "START",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
    "LS", "RS", "GUIDE",
]


@dataclass(frozen=True)
class PadState:
    lx: int = 0             # sticks, -32768 .. 32767, +y is up
    ly: int = 0
    rx: int = 0
    ry: int = 0
    lt: int = 0             # triggers, 0 .. 255
    rt: int = 0
    buttons: frozenset = field(default_factory=frozenset)


NEUTRAL = PadState()


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _num(packet, key, fallback=None):
    v = packet.get(key)
    if v is None and fallback is not None:
        v = packet.get(fallback)
    # bool is an int subclass; reject it along with NaN.
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
        return 0.0
    return float(v)


def axis_to_stick(v):
    v = _clamp(v, -1.0, 1.0)
    return round(v * 32767) if v >= 0 else round(v * 32768)


def axis_to_trigger(v):
    return round(_clamp(v, 0.0, 1.0) * 255)


def map_state(packet, buttons=DEFAULT_BUTTONS):
    mask = packet.get("btn", 0)
    if not isinstance(mask, int) or isinstance(mask, bool) or mask < 0:
        mask = 0
    pressed = frozenset(name for i, name in enumerate(buttons) if mask >> i & 1)
    return PadState(
        lx=axis_to_stick(_num(packet, "lx", "steer")),
        ly=axis_to_stick(_num(packet, "ly")),
        rx=axis_to_stick(_num(packet, "rx")),
        ry=axis_to_stick(_num(packet, "ry")),
        lt=axis_to_trigger(_num(packet, "lt", "brk")),
        rt=axis_to_trigger(_num(packet, "rt", "thr")),
        buttons=pressed,
    )
