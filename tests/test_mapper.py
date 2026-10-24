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
