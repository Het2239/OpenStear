import asyncio

import pytest
from aiohttp import WSServerHandshakeError

from host import server
from host.gamepad import LogPad
from host.mapper import NEUTRAL

TOKEN = "secret"


@pytest.fixture
def pads():
    return {}


@pytest.fixture
async def client(aiohttp_client, pads):
    def factory(name):
        pads[name] = LogPad(name)
        return pads[name]

    return await aiohttp_client(server.create_app(TOKEN, factory))


async def hello(client, cid="phone1"):
    ws = await client.ws_connect(f"/ws?k={TOKEN}")
    await ws.send_json({"t": "hello", "id": cid})
    assert (await ws.receive_json())["t"] == "welcome"
    return ws


async def settle():
    await asyncio.sleep(0.02)


async def test_serves_web_app(client):
    resp = await client.get("/")
    assert resp.status == 200
    assert "OpenSteer" in await resp.text()
    assert (await client.get("/app.js")).status == 200


async def test_rejects_bad_token(client):
    with pytest.raises(WSServerHandshakeError) as e:
        await client.ws_connect("/ws?k=wrong")
    assert e.value.status == 403


async def test_state_is_applied(client, pads):
    ws = await hello(client)
    await ws.send_json({"t": "s", "seq": 1, "steer": 1.0, "thr": 0.5, "btn": 1})
    await settle()
    s = pads["pad1"].state
    assert (s.lx, s.rt, s.buttons) == (32767, 128, {"A"})
    await ws.close()


async def test_state_before_hello_is_ignored(client, pads):
    ws = await client.ws_connect(f"/ws?k={TOKEN}")
    await ws.send_json({"t": "s", "seq": 1, "thr": 1.0})
    await settle()
    assert pads == {}
    await ws.close()


async def test_old_packets_dropped(client, pads):
    ws = await hello(client)
    await ws.send_json({"t": "s", "seq": 5, "thr": 1.0})
    await ws.send_json({"t": "s", "seq": 4, "thr": 0.0})
    await settle()
    assert pads["pad1"].state.rt == 255
    await ws.close()


async def test_ping_pong(client):
    ws = await hello(client)
    await ws.send_json({"t": "ping", "id": 7, "ts": 123.5})
    assert await ws.receive_json() == {"t": "pong", "id": 7, "ts": 123.5}
    await ws.close()


async def test_failsafe_releases_inputs(client, pads):
    ws = await hello(client)
    await ws.send_json({"t": "s", "seq": 1, "thr": 1.0, "btn": 3})
    await settle()
    assert pads["pad1"].state.rt == 255
    await asyncio.sleep(server.FAILSAFE_S + 2 * server.WATCHDOG_S)
    assert pads["pad1"].state == NEUTRAL
    await ws.close()


async def test_disconnect_releases_inputs(client, pads):
    ws = await hello(client)
    await ws.send_json({"t": "s", "seq": 1, "thr": 1.0})
    await settle()
    await ws.close()
    await settle()
    assert pads["pad1"].state == NEUTRAL


async def test_one_pad_per_phone_and_reuse_on_reconnect(client, pads):
    a = await hello(client, "a")
    b = await hello(client, "b")
    assert set(pads) == {"pad1", "pad2"}
    await a.close()
    a = await hello(client, "a")
    assert set(pads) == {"pad1", "pad2"}
    await a.close()
    await b.close()


async def test_reconnect_takes_over_old_session(client, pads):
    old = await hello(client, "a")
    new = await hello(client, "a")
    msg = await old.receive()
    assert old.closed or msg.type.name in ("CLOSE", "CLOSED", "CLOSING")
    await new.send_json({"t": "s", "seq": 1, "thr": 1.0})
    await settle()
    assert pads["pad1"].state.rt == 255
    await new.close()


async def test_settings_roundtrip(aiohttp_client, tmp_path):
    app = server.create_app(TOKEN, LogPad, tmp_path / "phones.json")
    client = await aiohttp_client(app)
    ws = await client.ws_connect(f"/ws?k={TOKEN}")
    await ws.send_json({"t": "hello", "id": "p1"})
    assert await ws.receive_json() == {"t": "welcome", "settings": None}
    await ws.send_json({"t": "settings", "values": {"range": 60, "rate": 250}, "ts": 5})
    await settle()
    await ws.close()

    ws = await client.ws_connect(f"/ws?k={TOKEN}")
    await ws.send_json({"t": "hello", "id": "p1"})
    msg = await ws.receive_json()
    assert msg["settings"]["ts"] == 5
    assert msg["settings"]["values"]["range"] == 60 and msg["settings"]["values"]["rate"] == 250
    await ws.close()
