"""Per-phone tuning settings, kept on the PC so they survive a new browser.

The phone owns the settings (web/settings.js); the host validates what it is
sent and stores it per phone id. Keys and limits match web/settings.js.
"""

import json
import logging
import math

log = logging.getLogger(__name__)

SCHEMA = {
    "range": {"min": 30, "max": 180, "default": 90},
    "deadzone": {"min": 0.0, "max": 0.3, "default": 0.03},
    "gamma": {"min": 0.5, "max": 3.0, "default": 1.0},
    "smoothing": {"min": 0.0, "max": 0.95, "default": 0.5},
    "rate": {"options": [60, 100, 125, 250], "default": 100},
    "haptics": {"bool": True, "default": True},
    "debug": {"bool": True, "default": False},
}
MAX_PHONES = 32


def sanitize(values):
    out = {k: d["default"] for k, d in SCHEMA.items()}
    if not isinstance(values, dict):
        return out
    for key, d in SCHEMA.items():
        v = values.get(key)
        if d.get("bool"):
            if isinstance(v, bool):
                out[key] = v
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        elif "options" in d:
            if v in d["options"]:
                out[key] = int(v)
        else:
            out[key] = min(d["max"], max(d["min"], v))
    return out


class SettingsStore:
    """{phone id: {"values": {...}, "ts": ms}} in one JSON file."""

    def __init__(self, path):
        self.path = path
        try:
            data = json.loads(path.read_text()) if path else {}
            self._data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self._data = {}

    def get(self, phone_id):
        """This phone's settings, else the most recently saved ones.

        A new browser or an installed home-screen app starts with a new phone
        id and empty storage; the latest settings are the best guess for it.
        """
        if phone_id in self._data:
            return self._data[phone_id]
        if not self._data:
            return None
        return max(self._data.values(), key=lambda e: e["ts"])

    def put(self, phone_id, values, ts):
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            ts = 0
        current = self._data.get(phone_id)
        if current and current["ts"] > ts:
            return current  # keep the newer copy
        entry = {"values": sanitize(values), "ts": ts}
        self._data[phone_id] = entry
        # Drop the oldest phones beyond the cap so the file stays small.
        if len(self._data) > MAX_PHONES:
            for old in sorted(self._data, key=lambda k: self._data[k]["ts"])[:-MAX_PHONES]:
                del self._data[old]
        self._save()
        return entry

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=1))
            tmp.replace(self.path)
        except OSError as e:
            log.warning("Could not save phone settings: %s", e)
