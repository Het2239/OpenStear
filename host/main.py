"""Entry point: `python -m host.main`."""

import argparse
import asyncio
import logging
import secrets

from aiohttp import web

from . import adb, config
from .gamepad import make_factory
from .server import create_app

log = logging.getLogger("opensteer")


def print_qr(url):
    try:
        import qrcode
    except ImportError:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)


async def run(port, token, pad_backend, use_adb):
    app = create_app(token, make_factory(pad_backend))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()

    url = f"http://localhost:{port}/?k={token}"
    print_qr(url)
    log.info("Open on the phone: %s", url)

    tasks = [asyncio.create_task(adb.keep_reversed(port))] if use_adb else []
    try:
        await asyncio.Event().wait()
    finally:
        for t in tasks:
            t.cancel()
        await runner.cleanup()


def main():
    cfg = config.load()
    p = argparse.ArgumentParser(description="OpenSteer PC host")
    p.add_argument("--port", type=int, default=cfg["port"])
    p.add_argument("--pad", choices=["auto", "vigem", "log"], default=cfg["pad"],
                   help="virtual pad backend (log = print only)")
    p.add_argument("--no-adb", action="store_true", help="do not run adb reverse")
    p.add_argument("--new-token", action="store_true", help="generate a new pairing token")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if args.new_token:
        cfg["token"] = secrets.token_urlsafe(8)
        config.save(cfg)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(run(args.port, cfg["token"], args.pad, not args.no_adb))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
