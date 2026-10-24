import socket
import ssl

import aiohttp
import pytest

from host import core, network
from host.gamepad import LogPad

TOKEN = "secret"


def free_base_port():
    """A base port P where P, P+1 and P+2 are all free."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        if base + 2 > 65535:
            continue
        try:
            socks = []
            for p in (base, base + 1, base + 2):
                s = socket.socket()
                socks.append(s)
                s.bind(("0.0.0.0", p))
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    raise RuntimeError("no free ports")


@pytest.fixture
async def host(tmp_path, monkeypatch):
    ifaces = [network.Iface("wlan0", "127.0.0.1", network.LAN)]
    monkeypatch.setattr(network, "list_ifaces", lambda: ifaces)
    h = core.Host(free_base_port(), TOKEN, LogPad, tmp_path, use_adb=False)
    await h.start()
    yield h
    await h.stop()


async def test_usb_mode_is_local_only(host):
    assert host.url() == f"http://localhost:{host.port}/#k={TOKEN}"
    assert host._https_site is None
    async with aiohttp.ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{host.port}/") as r:
            assert r.status == 200


async def test_wifi_mode_serves_https_and_trust_page(host, tmp_path):
    await host.set_mode(core.WIFI)
    assert host.problem() is None
    assert host.url() == f"http://127.0.0.1:{host.port + 2}/#k={TOKEN}&p={host.port + 1}"

    ctx = ssl.create_default_context(cafile=str(tmp_path / "ca.crt"))
    async with aiohttp.ClientSession() as s:
        async with s.get(f"https://127.0.0.1:{host.port + 1}/health", ssl=ctx) as r:
            assert r.status == 204
        async with s.ws_connect(f"wss://127.0.0.1:{host.port + 1}/ws?k={TOKEN}", ssl=ctx) as ws:
            await ws.send_json({"t": "hello", "id": "p"})
            assert (await ws.receive_json())["t"] == "welcome"

        base = f"http://127.0.0.1:{host.port + 2}"
        async with s.get(f"{base}/") as r:
            assert "certificate" in (await r.text()).lower()
        async with s.get(f"{base}/ca.crt") as r:
            assert r.content_type == "application/x-x509-ca-cert"
            assert b"BEGIN CERTIFICATE" in await r.read()
        # The plain-HTTP listener must not expose the controller.
        async with s.get(f"{base}/ws?k={TOKEN}") as r:
            assert r.status == 404
        async with s.get(f"{base}/app.js") as r:
            assert r.status == 404


async def test_back_to_usb_closes_lan_ports(host):
    await host.set_mode(core.WIFI)
    await host.set_mode(core.USB)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", host.port + 1), timeout=1).close()


async def test_tether_mode_without_link_explains(host):
    await host.set_mode(core.TETHER)
    assert host.url() is None
    assert "tethering" in host.problem()
