"""Entry point: `python -m host.main`."""

import argparse
import asyncio
import io
import logging
import secrets
import threading

from . import config
from .core import MODES, Host, PortInUse
from .gamepad import make_factory

log = logging.getLogger("opensteer")


def print_qr(url):
    try:
        import qrcode
    except ImportError:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    try:
        print(buf.getvalue())
    except UnicodeEncodeError:
        pass  # console can't show block characters; the URL is still logged


async def run_console(host):
    await host.start()
    shown = (None, None)
    try:
        while True:
            now = (host.url(), host.problem())
            if now != shown:
                shown = now
                url, problem = now
                if url:
                    print_qr(url)
                    log.info("%s: open on the phone: %s", MODES[host.mode], url)
                if problem:
                    log.warning("%s", problem)
            await asyncio.sleep(1)
    finally:
        await host.stop()


def run_window(host, cfg):
    """Run the Tk window; returns False if no window can be shown here."""
    try:
        import tkinter as tk
        from .ui import Window
        tk.Tk().destroy()  # fails fast with TclError when there is no display
    except Exception as e:
        log.info("No desktop window (%s); running in the console", e)
        return False

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        asyncio.run_coroutine_threadsafe(host.start(), loop).result()
    except PortInUse as e:
        raise SystemExit(str(e))

    def remember(mode):
        cfg["mode"] = mode
        config.save(cfg)

    try:
        Window(host, loop, on_mode_change=remember).run()
    finally:
        asyncio.run_coroutine_threadsafe(host.stop(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
    return True


def main():
    cfg = config.load()
    p = argparse.ArgumentParser(description="OpenSteer PC host")
    p.add_argument("--mode", choices=list(MODES), default=cfg["mode"],
                   help="usb = USB (ADB), tether = USB tethering, wifi = Wi-Fi")
    p.add_argument("--port", type=int, default=cfg["port"],
                   help="base port; the next two ports are used for HTTPS and setup")
    p.add_argument("--pad", choices=["auto", "vigem", "uinput", "log"], default=cfg["pad"],
                   help="virtual pad backend: vigem (Windows), uinput (Linux), log (print only)")
    p.add_argument("--no-adb", action="store_true", help="do not run adb reverse")
    p.add_argument("--no-ui", action="store_true", help="console only, no window")
    p.add_argument("--new-token", action="store_true", help="generate a new pairing token")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if args.new_token:
        cfg["token"] = secrets.token_urlsafe(8)
        config.save(cfg)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    host = Host(args.port, cfg["token"], make_factory(args.pad), config.cert_dir(),
                mode=args.mode, use_adb=not args.no_adb)
    try:
        if args.no_ui or not run_window(host, cfg):
            asyncio.run(run_console(host))
    except PortInUse as e:
        raise SystemExit(str(e))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
