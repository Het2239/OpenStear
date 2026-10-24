import asyncio
import json

from host import server
from host.gamepad import LogPad
from host.profiles import AUTO, OFF, Profiles

LAYOUT = {"name": "x", "tilt": True, "controls": [{"type": "button", "map": "A", "x": 1, "y": 1, "w": 9, "h": 9}]}


def test_save_link_select_and_persist(tmp_path):
    path = tmp_path / "profiles.json"
    p = Profiles(path)
    assert p.save("  F1   25 ", LAYOUT) == "F1 25"
    assert p.save("bad", {"controls": "nope"}) is None
    assert p.active() is None                      # auto, but no game running
    p.link("F1 25", "F1_25.exe")
    p.running = frozenset({"steam.exe", "f1_25.exe"})
    assert p.active() == "F1 25"                   # matched case-insensitively
    p.select(OFF)
    assert p.active() is None
    p.select("F1 25")
    p.running = frozenset()
    assert p.active() == "F1 25"                   # chosen by hand: no game needed
    again = Profiles(path)
    assert again.selection == "F1 25" and again.profiles["F1 25"]["exe"] == "F1_25.exe"
    assert again.layout("F1 25")["name"] == "F1 25"
    again.delete("F1 25")
    assert again.selection == AUTO and again.names() == []


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"profiles": {"ok": {"layout": LAYOUT}, "bad": {"layout": 5}}, "selection": "bad"}))
    p = Profiles(path)
    assert p.names() == ["ok"] and p.selection == AUTO


async def test_phone_saves_profile_and_others_are_told(aiohttp_client, tmp_path):
    app = server.create_app("k", LogPad, profiles_path=tmp_path / "p.json")
    client = await aiohttp_client(app)

    async def phone(cid):
        ws = await client.ws_connect("/ws?k=k")
        await ws.send_json({"t": "hello", "id": cid})
        assert (await ws.receive_json())["t"] == "welcome"
        msg = await ws.receive_json()
        assert msg["t"] == "profile"
        return ws, msg

    a, first = await phone("a")
    b, _ = await phone("b")
    assert first == {"t": "profile", "names": [], "active": None, "layout": None}

    await a.send_json({"t": "saveProfile", "name": "Drift", "layout": LAYOUT})
    assert await a.receive_json() == {"t": "profileSaved", "name": "Drift", "error": None}
    for ws in (a, b):
        msg = await ws.receive_json()
        assert msg["names"] == ["Drift"] and msg["active"] is None

    app["profiles"].select("Drift")
    server.notify_profiles(app)
    for ws in (a, b):
        msg = await ws.receive_json()
        assert msg["active"] == "Drift" and msg["layout"]["controls"] == LAYOUT["controls"]
    await a.close()
    await b.close()
