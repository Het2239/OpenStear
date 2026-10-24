"""The host: listeners for each connection mode, plus status for the UI.

Ports (base port P, default 8765):
  P     HTTP,  127.0.0.1 only. USB (ADB) mode; the phone reaches it via adb reverse.
  P+1   HTTPS, all interfaces. Wi-Fi and USB tethering modes.
  P+2   HTTP,  all interfaces. Certificate guide and CA download only.

The LAN listeners run only while a LAN mode is selected, so USB (ADB) mode
never opens a port to the network.
"""

import asyncio
import logging

from aiohttp import web

from . import adb, certs, network
from .server import create_app, create_trust_app

log = logging.getLogger(__name__)

USB, TETHER, WIFI = "usb", "tether", "wifi"
MODES = {USB: "USB (ADB)", TETHER: "USB tethering", WIFI: "Wi-Fi"}
NET_POLL_S = 3.0

HINTS = {
    USB: "Android: enable USB debugging, plug the phone in, accept the prompt, "
         "then scan the QR code or open the link on the phone.",
    TETHER: "Turn on USB tethering (Android) or Personal Hotspot (iPhone) with the "
            "cable plugged in, then scan the QR code.",
    WIFI: "Put the phone on the same Wi-Fi as this PC, then scan the QR code.",
}


class Host:
    def __init__(self, port, token, pad_factory, cert_dir, mode=USB, use_adb=True):
        self.port = port
        self.token = token
        self.cert_dir = cert_dir
        self.mode = mode if mode in MODES else USB
        self.use_adb = use_adb
        self.selected_ip = None  # None = pick automatically
        self.ifaces = []
        self.adb_status = {"adb": None, "devices": {}}
        self.error = None
        self.app = create_app(token, pad_factory)
        self._runner = web.AppRunner(self.app, access_log=None)
        self._https_site = None
        self._trust_runner = None
        self._ssl = None
        self._cert_ips = set()
        self._tasks = []

    # --- lifecycle -----------------------------------------------------------

    async def start(self):
        await self._runner.setup()
        await self._start_site(self._runner, "127.0.0.1", self.port)
        self.ifaces = await asyncio.to_thread(network.list_ifaces)
        if self.use_adb:
            self._tasks.append(asyncio.create_task(
                adb.keep_reversed(self.port, status=self.adb_status)))
        self._tasks.append(asyncio.create_task(self._watch_network()))
        await self.set_mode(self.mode)

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await self._stop_lan()
        await self._runner.cleanup()

    async def _start_site(self, runner, host, port, ssl_context=None):
        site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
        try:
            await site.start()
        except OSError as e:
            raise PortInUse(host, port, e) from e
        return site

    # --- modes ---------------------------------------------------------------

    async def set_mode(self, mode, ip=None):
        self.mode, self.selected_ip, self.error = mode, ip, None
        try:
            if mode == USB:
                await self._stop_lan()
            else:
                await self._start_lan()
        except PortInUse as e:
            self.error = str(e)
            log.error("%s", e)

    async def _start_lan(self):
        if self._https_site is not None:
            return
        await self._refresh_cert()
        self._https_site = await self._start_site(self._runner, "0.0.0.0", self.port + 1, self._ssl)
        self._trust_runner = web.AppRunner(create_trust_app(self.cert_dir / "ca.crt"), access_log=None)
        await self._trust_runner.setup()
        try:
            await self._start_site(self._trust_runner, "0.0.0.0", self.port + 2)
        except PortInUse:
            await self._stop_lan()
            raise
        log.info("Listening on the network: HTTPS :%d, setup page :%d", self.port + 1, self.port + 2)

    async def _stop_lan(self):
        if self._https_site is not None:
            await self._https_site.stop()
            self._https_site = None
        if self._trust_runner is not None:
            await self._trust_runner.cleanup()
            self._trust_runner = None

    async def _refresh_cert(self):
        ips = {i.ip for i in self.ifaces if i.kind in (network.LAN, network.TETHER)}
        if self._ssl is not None and ips <= self._cert_ips:
            return
        cert, key = await asyncio.to_thread(certs.ensure_server_cert, self.cert_dir, ips)
        if self._ssl is None:
            self._ssl = certs.ssl_context(cert, key)
        else:
            # New handshakes pick up the new certificate; no restart needed.
            self._ssl.load_cert_chain(cert, key)
        self._cert_ips = ips

    async def _watch_network(self):
        while True:
            await asyncio.sleep(NET_POLL_S)
            try:
                self.ifaces = await asyncio.to_thread(network.list_ifaces)
                if self._https_site is not None:
                    await self._refresh_cert()
            except Exception:
                log.exception("Network refresh failed")

    # --- status for the UI and console --------------------------------------

    def ip_choices(self):
        return [] if self.mode == USB else network.candidates(self.mode, self.ifaces)

    def current_ip(self):
        choices = self.ip_choices()
        if self.selected_ip and any(i.ip == self.selected_ip for i in choices):
            return self.selected_ip
        return choices[0].ip if choices else None

    def url(self):
        """URL for the QR code, or None if this mode has no usable network."""
        if self.mode == USB:
            return f"http://localhost:{self.port}/#k={self.token}"
        ip = self.current_ip()
        if ip is None or self._https_site is None:
            return None
        # The token goes in the fragment so it never crosses the network in plain HTTP.
        return f"http://{ip}:{self.port + 2}/#k={self.token}&p={self.port + 1}"

    def problem(self):
        """A short explanation when the mode can't work right now, else None."""
        if self.error:
            return self.error
        if self.mode == USB:
            if self.use_adb and self.adb_status["adb"] is None:
                return "adb not found. Put Android platform-tools in vendor/platform-tools."
            return None
        if not self.ip_choices():
            if self.mode == TETHER:
                return "No USB tethering link found. Turn on USB tethering / Personal Hotspot."
            return "No network connection found."
        return None

    def phones(self):
        return self.app["pads"].connected()


class PortInUse(Exception):
    def __init__(self, host, port, err):
        super().__init__(f"Cannot listen on {host}:{port} ({err.strerror or err}). "
                         f"Another program may be using it; try --port {port + 10}.")
