from host.adb import parse_devices


def test_parse_devices():
    out = (
        "List of devices attached\n"
        "R58M123ABC\tdevice\n"
        "emulator-5554\tunauthorized\n"
        "\n"
    )
    assert parse_devices(out) == {"R58M123ABC": "device", "emulator-5554": "unauthorized"}


def test_parse_no_devices():
    assert parse_devices("List of devices attached\n\n") == {}
