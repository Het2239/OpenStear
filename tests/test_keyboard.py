import asyncio
import ctypes
import os
import sys
import time

import pytest

from host import server
from host.gamepad import LogPad
from host.keyboard_out import Keyboard


class Rec:
    def __init__(self):
        self.events = []

    def send(self, press, release):
        self.events.append((set(press), set(release)))

    def close(self):
        pass


def test_keys_from_two_phones_are_combined():
    rec = Rec()
    kb = Keyboard(rec)
    kb.set("a", {"W"})
    kb.set("b", {"W", "SPACE"})
    kb.set("a", set())            # W still held by b: no release yet
    kb.set("b", set())
    assert rec.events == [({"W"}, set()), ({"SPACE"}, set()), (set(), {"W", "SPACE"})]


def test_unknown_keys_are_ignored():
    rec = Rec()
    Keyboard(rec).set("a", {"NOT_A_KEY"})
    assert rec.events == []


async def test_keys_from_packets_and_release_on_disconnect(aiohttp_client):
    rec = Rec()
    client = await aiohttp_client(server.create_app("k", LogPad, keyboard=Keyboard(rec)))
    ws = await client.ws_connect("/ws?k=k")
    await ws.send_json({"t": "hello", "id": "p"})
    await ws.receive_json()
    await ws.send_json({"t": "s", "seq": 1, "k": ["W", "<script>"]})
    await asyncio.sleep(0.05)
    assert rec.events == [({"W"}, set())]
    await ws.close()                      # phone gone with W held
    await asyncio.sleep(0.05)
    assert rec.events[-1] == (set(), {"W"})


@pytest.mark.skipif(not sys.platform.startswith("linux") or os.environ.get("OPENSTEER_UINPUT_TEST") != "1",
                    reason="needs Linux + /dev/uinput (set OPENSTEER_UINPUT_TEST=1)")
def test_linux_virtual_keyboard_is_created():
    """The keyboard device appears with our keys. (Desktops don't let normal
    users read keyboards back, so this can't check the presses themselves.)
    Only F23/F24 are pressed: real keys would type into the focused window."""
    import re
    from pathlib import Path

    from host.keyboard_out import UInputKeys

    name = f"OpenSteer test keyboard {os.getpid()}"
    keys = UInputKeys(name)
    try:
        block = None
        for _ in range(40):
            block = next((b for b in Path("/proc/bus/input/devices").read_text().split("\n\n")
                          if f'N: Name="{name}"' in b), None)
            if block:
                break
            time.sleep(0.05)
        assert block, "virtual keyboard did not appear"
        assert "kbd" in block
        bits = re.search(r"B: KEY=([0-9a-f ]+)", block).group(1).split()
        mask = int("".join(w.rjust(16, "0") for w in bits), 16)
        for code in (17, 57, 103, 193, 194):          # W, SPACE, UP, F23, F24
            assert mask >> code & 1, code
        keys.send({"F23", "F24"}, set())
        keys.send(set(), {"F23", "F24"})
    finally:
        keys.close()


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("OPENSTEER_KEYBOARD_TEST") != "1",
                    reason="needs Windows desktop (set OPENSTEER_KEYBOARD_TEST=1)")
def test_windows_sendinput_presses_keys():
    from host.keyboard_out import WinKeys

    VK_F13 = 0x7C
    state = ctypes.windll.user32.GetAsyncKeyState
    keys = WinKeys()
    keys.send({"F13"}, set())
    time.sleep(0.05)
    assert state(VK_F13) & 0x8000
    keys.send(set(), {"F13"})
    time.sleep(0.05)
    assert not state(VK_F13) & 0x8000
