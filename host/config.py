"""Load/save host settings as JSON in the user's config directory."""

import json
import os
import secrets
import sys
from pathlib import Path

DEFAULTS = {"port": 8765, "token": None, "pad": "auto", "mode": "usb", "telemetry_port": 20777}


def config_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "OpenSteer" / "config.json"


def cert_dir():
    return config_path().parent / "certs"


def load(path=None):
    path = path or config_path()
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(path.read_text()))
    except (OSError, ValueError):
        pass
    if not cfg["token"]:
        cfg["token"] = secrets.token_urlsafe(8)
        save(cfg, path)
    return cfg


def save(cfg, path=None):
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))
