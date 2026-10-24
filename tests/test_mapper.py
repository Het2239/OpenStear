from host.mapper import NEUTRAL, axis_to_stick, axis_to_trigger, map_state


def test_stick_range():
    assert axis_to_stick(-1.0) == -32768
    assert axis_to_stick(1.0) == 32767
    assert axis_to_stick(0.0) == 0
    assert axis_to_stick(5.0) == 32767
    assert axis_to_stick(-5.0) == -32768


def test_trigger_range():
    assert axis_to_trigger(0.0) == 0
    assert axis_to_trigger(1.0) == 255
    assert axis_to_trigger(-1.0) == 0
    assert axis_to_trigger(2.0) == 255


def test_map_state():
    s = map_state({"t": "s", "steer": -0.5, "thr": 1.0, "brk": 0.0, "btn": 0b1001})
    assert s.lx == -16384
    assert s.rt == 255
    assert s.lt == 0
    assert s.buttons == {"A", "Y"}


def test_garbage_is_neutral():
    assert map_state({"steer": "x", "thr": None, "brk": float("nan"), "btn": -3}) == NEUTRAL
    assert map_state({"steer": True, "btn": True}) == NEUTRAL


def test_gamepad_axes():
    s = map_state({"lx": 0.5, "ly": -1.0, "rx": -0.5, "ry": 1.0, "lt": 0.5, "rt": 0.2,
                   "btn": 1 << 12 | 1 << 14})
    assert (s.lx, s.ly, s.rx, s.ry) == (16384, -32768, -16384, 32767)
    assert (s.lt, s.rt) == (128, 51)
    assert s.buttons == {"LS", "GUIDE"}


def test_explicit_axes_win_over_wheel_names():
    s = map_state({"steer": 1.0, "lx": -1.0, "thr": 1.0, "rt": 0.0})
    assert (s.lx, s.rt) == (-32768, 0)
