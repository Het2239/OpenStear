"""aiohttp app: serves the phone web app and receives input on /ws."""

import asyncio
import hmac
import json
import logging
import time
from dataclasses import replace
from pathlib import Path

from aiohttp import WSMsgType, web

from .latch import ButtonLatch
from .mapper import NEUTRAL, map_state
from .phone_settings import SettingsStore

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
FAILSAFE_S = 0.3
WATCHDOG_S = 0.05
MAX_PADS = 4  # XInput only sees four pads
MAX_MSG = 4096


class PadManager:
    """One virtual pad per phone, keyed by the id the phone sends in hello.

    Pads outlive connections so a phone that reconnects gets the same pad
    and the game does not see a controller unplug.
    """

    def __init__(self, factory):
        self._factory = factory
        self._pads = {}
        self._owners = {}

    def claim(self, client_id, owner):
        """Give `owner` the pad for `client_id`. Returns (pad, previous_owner)."""
        pad = self._pads.get(client_id)
        if pad is None:
            if len(self._pads) >= MAX_PADS:
                return None, None
            pad = self._factory(f"pad{len(self._pads) + 1}")
            self._pads[client_id] = pad
        previous = self._owners.get(client_id)
        self._owners[client_id] = owner
        return pad, previous

    def connected(self):
        """Client ids of phones with an open connection."""
        return list(self._owners)

    def release(self, client_id, owner):
        if self._owners.get(client_id) is owner:
            del self._owners[client_id]
            pad = self._pads[client_id]
            pad.on_rumble = None
            pad.reset()

    def close_all(self):
        for pad in self._pads.values():
            pad.close()
        self._pads.clear()
        self._owners.clear()


class Session:
    def __init__(self, ws):
        self.ws = ws
        self.pad = None
        self.client_id = None
        self.last_seq = -1
        self.last_rx = 0.0
        self.live = False  # inputs applied since the last neutral reset
        self.latch = ButtonLatch()
        self.state = NEUTRAL
        self._timer = None
        self.audit = TapAudit()
        self._rumble_sent = (0.0, 0.0)

    def rumble(self, strong, weak):
        """The game rumbled this phone's pad: tell the phone (on change only)."""
        value = (round(strong, 2), round(weak, 2))
        if value == self._rumble_sent or self.ws.closed:
            return
        self._rumble_sent = value
        asyncio.ensure_future(self._send({"t": "rumble", "l": value[0], "s": value[1]}))

    async def _send(self, msg):
        try:
            await self.ws.send_json(msg)
        except (ConnectionError, RuntimeError):
            pass  # phone went away; it stops vibrating on its own

    def apply(self, packet):
        seq = packet.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            if seq <= self.last_seq:
                return
            self.last_seq = seq
        # perf_counter: monotonic() only ticks every ~16 ms on Windows.
        now = time.perf_counter()
        self.state = map_state(packet)
        self._show(self.latch.update(self.state.buttons, now))
        self.audit.phone(packet.get("tp"), packet.get("tc"), now)
        self.last_rx = time.monotonic()
        self.live = True
        self._schedule()

    def _schedule(self):
        """Wake up when a press/release held back by the latch is due."""
        due = self.latch.next_due()
        if due is None or self._timer is not None:
            return
        delay = max(0.0, due - time.perf_counter())
        self._timer = asyncio.get_running_loop().call_later(delay, self._replay)

    def _replay(self):
        self._timer = None
        if self.live and self.pad is not None:
            self._show(self.latch.output(time.perf_counter()))
            self._schedule()

    def _show(self, buttons):
        self.audit.pad(buttons, self.client_id)
        self.pad.apply(replace(self.state, buttons=buttons))

    def stop(self):
        """Forget queued button edges (disconnect, failsafe)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.latch.reset()
        self.state = NEUTRAL

    def failsafe(self):
        if self.latch.next_due() is None:
            self.audit.check(self.client_id, time.perf_counter())
        if self.live and time.monotonic() - self.last_rx > FAILSAFE_S:
            self.stop()
            self.pad.reset()
            self.live = False
            log.info("%s: no input for %d ms, inputs released",
                     self.client_id, FAILSAFE_S * 1000)


class TapAudit:
    """Compare taps the phone registered with presses that reached the pad.

    The phone sends its running tap count (tp) and cancelled-touch count (tc)
    in every packet. A shortfall means a press was lost between the phone and
    the virtual pad; cancelled touches mean the phone's browser took touches
    back. Both are logged so a missed press can be traced.
    """

    SETTLE_S = 0.3

    def __init__(self):
        self.taps = self.tap_base = None
        self.cancels = self.cancel_base = None
        self.presses = self.press_base = 0
        self.shown = frozenset()
        self.changed = 0.0

    def phone(self, tp, tc, now):
        if not isinstance(tp, int) or isinstance(tp, bool):
            return
        if self.taps is None:
            self.tap_base, self.press_base = tp, self.presses
        if tp != self.taps:
            self.changed = now
        self.taps = tp
        if isinstance(tc, int) and not isinstance(tc, bool):
            if self.cancels is None:
                self.cancel_base = tc
            self.cancels = tc

    def pad(self, buttons, who):
        # D-pad rolls make several presses per touch, so only count buttons.
        new = {b for b in buttons - self.shown if not b.startswith("DPAD_")}
        self.shown = buttons
        if new:
            self.presses += len(new)
            log.debug("%s: press %s (pad presses %d, phone taps %s)",
                      who, ",".join(sorted(new)), self.presses - self.press_base,
                      None if self.taps is None else self.taps - self.tap_base)

    def check(self, who, now):
        if self.taps is None or now - self.changed < self.SETTLE_S:
            return
        missing = (self.taps - self.tap_base) - (self.presses - self.press_base)
        if missing > 0:
            log.warning("%s: %d tap(s) registered on the phone did not reach the pad as a press "
                        "(or two buttons with the same Xbox button were held together)", who, missing)
        if self.cancels is not None and self.cancels > self.cancel_base:
            log.warning("%s: the phone's browser cancelled %d touch(es); it treated them as a gesture",
                        who, self.cancels - self.cancel_base)
            self.cancel_base = self.cancels
        self.tap_base, self.press_base = self.taps, self.presses


async def _watchdog(session):
    while True:
        await asyncio.sleep(WATCHDOG_S)
        if session.pad is not None:
            session.failsafe()


async def ws_handler(request):
    app = request.app
    token = request.query.get("k", "")
    if not hmac.compare_digest(token.encode(), app["token"].encode()):
        log.warning("Rejected connection from %s: bad pairing token", request.remote)
        raise web.HTTPForbidden(text="bad pairing token")

    ws = web.WebSocketResponse(heartbeat=5, max_msg_size=MAX_MSG)
    await ws.prepare(request)
    session = Session(ws)
    pads = app["pads"]
    watchdog = asyncio.create_task(_watchdog(session))
    log.info("Phone connected from %s", request.remote)

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                packet = json.loads(msg.data)
            except ValueError:
                continue
            if not isinstance(packet, dict):
                continue
            kind = packet.get("t")

            if kind == "s":
                if session.pad is not None:
                    session.apply(packet)
            elif kind == "ping":
                await ws.send_json({"t": "pong", "id": packet.get("id"), "ts": packet.get("ts")})
            elif kind == "settings" and session.client_id is not None:
                app["settings"].put(session.client_id, packet.get("values"), packet.get("ts"))
            elif kind == "hello" and session.pad is None:
                client_id = str(packet.get("id") or request.remote)[:64]
                pad, previous = pads.claim(client_id, session)
                if pad is None:
                    await ws.send_json({"t": "error", "msg": f"at most {MAX_PADS} phones"})
                    break
                if previous is not None and previous is not session:
                    previous.pad = None
                    await previous.ws.close()
                session.pad, session.client_id = pad, client_id
                pad.on_rumble = session.rumble
                log.info("%s: hello (layout %s)", client_id, packet.get("layout"))
                # Saved settings let a phone get its tuning back in a new browser.
                await ws.send_json({"t": "welcome", "settings": app["settings"].get(client_id)})
    finally:
        watchdog.cancel()
        session.stop()
        if session.client_id is not None:
            pads.release(session.client_id, session)
        log.info("Phone disconnected (%s), inputs released", session.client_id or request.remote)
    return ws


async def index(request):
    return web.FileResponse(WEB_DIR / "index.html")


async def health(request):
    # The trust page probes this over HTTPS to see if the phone trusts our CA.
    return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})


@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def create_app(token, pad_factory, settings_path=None):
    app = web.Application(middlewares=[no_cache])
    app["token"] = token
    app["pads"] = PadManager(pad_factory)
    app["settings"] = SettingsStore(settings_path)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health)
    app.router.add_static("/", WEB_DIR)

    async def on_shutdown(app):
        app["pads"].close_all()

    app.on_shutdown.append(on_shutdown)
    return app


def create_trust_app(ca_path):
    """Plain-HTTP app for the LAN: only the certificate guide and the CA file.

    It never serves the controller or /ws, and the pairing token travels in
    the URL fragment, which browsers do not send to the server.
    """
    app = web.Application(middlewares=[no_cache])

    async def trust(request):
        return web.FileResponse(WEB_DIR / "trust.html")

    async def ca(request):
        return web.Response(
            body=ca_path.read_bytes(),
            content_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": 'attachment; filename="OpenSteer-CA.crt"'},
        )

    def static(name):
        async def handler(request):
            return web.FileResponse(WEB_DIR / name)
        return handler

    app.router.add_get("/", trust)
    app.router.add_get("/ca.crt", ca)
    for name in ("trust.js", "style.css"):
        app.router.add_get(f"/{name}", static(name))
    return app
