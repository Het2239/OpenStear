"""Game profiles: a layout saved on the PC, optionally linked to a game.

A profile is {"layout": {...}, "exe": "F1_25.exe" or None}. The phone builds
and validates layouts (web/layoutlib.js); the host only checks size and
shape, stores them, and tells phones which profile is active.

Selection: "off" (phones use their own layout), "auto" (the profile whose
game is running), or a profile name (always that one).
"""

import json
import logging

log = logging.getLogger(__name__)

MAX_PROFILES = 50
MAX_LAYOUT_BYTES = 60_000
OFF, AUTO = "off", "auto"


def check_layout(layout):
    """Basic shape and size check; the phone does the full validation."""
    if not isinstance(layout, dict) or not isinstance(layout.get("controls"), list):
        return False
    if not 0 < len(layout["controls"]) <= 60:
        return False
    return len(json.dumps(layout)) <= MAX_LAYOUT_BYTES


def clean_name(name):
    if not isinstance(name, str):
        return None
    name = " ".join(name.split())[:40]
    return name or None


class Profiles:
    def __init__(self, path=None):
        self.path = path
        self.profiles = {}
        self.selection = AUTO
        self.running = frozenset()   # lower-case names of running processes
        self._load()

    # --- storage ----------------------------------------------------------

    def _load(self):
        if not self.path:
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.profiles = {n: p for n, p in data.get("profiles", {}).items()
                             if clean_name(n) == n and isinstance(p, dict) and check_layout(p.get("layout"))}
            sel = data.get("selection")
            if sel in (OFF, AUTO) or sel in self.profiles:
                self.selection = sel

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"selection": self.selection, "profiles": self.profiles}, indent=1))
            tmp.replace(self.path)
        except OSError as e:
            log.warning("Could not save profiles: %s", e)

    # --- editing ----------------------------------------------------------

    def save(self, name, layout):
        name = clean_name(name)
        if not name or not check_layout(layout):
            return None
        if name not in self.profiles and len(self.profiles) >= MAX_PROFILES:
            return None
        exe = self.profiles.get(name, {}).get("exe")
        self.profiles[name] = {"layout": {**layout, "name": name}, "exe": exe}
        self._save()
        return name

    def link(self, name, exe):
        if name in self.profiles:
            self.profiles[name]["exe"] = exe.strip() if isinstance(exe, str) and exe.strip() else None
            self._save()

    def delete(self, name):
        if self.profiles.pop(name, None) is not None:
            if self.selection == name:
                self.selection = AUTO
            self._save()

    def select(self, selection):
        if selection in (OFF, AUTO) or selection in self.profiles:
            self.selection = selection
            self._save()

    # --- which profile is active ------------------------------------------

    def active(self):
        """Name of the active profile, or None."""
        if self.selection == OFF:
            return None
        if self.selection != AUTO:
            return self.selection
        for name, p in sorted(self.profiles.items()):
            if p.get("exe") and p["exe"].lower() in self.running:
                return name
        return None

    def layout(self, name):
        p = self.profiles.get(name)
        return p and p["layout"]

    def names(self):
        return sorted(self.profiles)
