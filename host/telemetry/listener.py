"""UDP listener for game telemetry, with optional forwarding.

Games send telemetry to one port; other tools (SimHub, lap timers) often want
it too. With `forward`, every packet received is passed on unchanged.
"""

import asyncio
import logging
import time

from .f1 import F1Decoder

log = logging.getLogger(__name__)

STALE_S = 2.0


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, listener):
        self.listener = listener
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.listener._received(data, self.transport)

    def error_received(self, exc):
        log.debug("telemetry socket error: %s", exc)


class TelemetryListener:
    def __init__(self, port=20777, bind="127.0.0.1", forward=None):
        self.port = port
        self.bind = bind
        self.forward = forward      # (host, port) or None
        self.decoder = F1Decoder()
        self.last_rx = 0.0
        self.error = None
        self._transport = None

    async def start(self):
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _Protocol(self), local_addr=(self.bind, self.port))
        except OSError as e:
            self.error = (f"Telemetry port {self.port} is in use ({e.strerror or e}). "
                          f"Close the other telemetry app, or use --telemetry-port.")
            log.warning("%s", self.error)
            return
        log.info("Listening for game telemetry on UDP %s:%d%s", self.bind, self.port,
                 f", forwarding to {self.forward[0]}:{self.forward[1]}" if self.forward else "")

    def stop(self):
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _received(self, data, transport):
        if self.forward:
            try:
                transport.sendto(data, self.forward)
            except OSError:
                pass
        if self.decoder.feed(data):
            self.last_rx = time.monotonic()

    @property
    def live(self):
        return time.monotonic() - self.last_rx < STALE_S

    def message(self):
        """Message for phones: the dash summary, or {"off": true} when stale."""
        if not self.live:
            return {"t": "tele", "off": True}
        return {"t": "tele", "game": self.decoder.game, **self.decoder.summary()}

    def status(self):
        if self.error:
            return self.error
        if self.live:
            return f"Telemetry: receiving from {self.decoder.game}"
        return f"Telemetry: waiting on UDP port {self.port} (turn on UDP telemetry in the game)"
