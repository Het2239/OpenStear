import json
import re
from pathlib import Path

from host.phone_settings import MAX_PHONES, SCHEMA, SettingsStore, sanitize

SETTINGS_JS = (Path(__file__).resolve().parent.parent / "web" / "settings.js").read_text()


def js_settings():
    """{key: (min, max) or options or "bool"} parsed from web/settings.js."""
    body = SETTINGS_JS.split("export const SETTINGS = {", 1)[1].split("\n};", 1)[0]
    out = {}
    for key, block in re.findall(r"\n  (\w+): \{(.*?)\n  \},", body, re.S):
        if "bool: true" in block:
            out[key] = "bool"
        elif m := re.search(r"options: \[([^\]]*)\]", block):
            out[key] = [int(x) for x in m.group(1).split(",")]
        else:
            lo, hi = re.search(r"min: ([\d.]+), max: ([\d.]+)", block).groups()
            out[key] = (float(lo), float(hi))
    return out


def test_phone_and_host_agree_on_settings():
    js = js_settings()
    assert set(js) == set(SCHEMA)
    for key, d in SCHEMA.items():
        if d.get("bool"):
            assert js[key] == "bool"
        elif "options" in d:
            assert js[key] == d["options"]
        else:
            assert js[key] == (d["min"], d["max"]), key


def test_sanitize_clamps_and_drops():
    v = sanitize({"range": 1000, "deadzone": -1, "gamma": "x", "rate": 77,
                  "haptics": 1, "smoothing": float("nan"), "evil": 1})
    assert v == {"range": 180, "deadzone": 0.0, "gamma": 1.0, "rate": 100,
                 "haptics": True, "smoothing": 0.5}
    assert sanitize({"rate": 250, "haptics": False})["rate"] == 250
    assert sanitize(None) == sanitize({})


def test_store_keeps_newer_and_persists(tmp_path):
    path = tmp_path / "phones.json"
    store = SettingsStore(path)
    store.put("a", {"range": 60}, 200)
    store.put("a", {"range": 120}, 100)          # older: ignored
    assert store.get("a")["values"]["range"] == 60
    assert SettingsStore(path).get("a")["values"]["range"] == 60
    assert json.loads(path.read_text())["a"]["ts"] == 200


def test_unknown_phone_gets_latest(tmp_path):
    store = SettingsStore(tmp_path / "p.json")
    assert store.get("new") is None
    store.put("a", {"range": 60}, 100)
    store.put("b", {"range": 150}, 300)
    assert store.get("new")["values"]["range"] == 150


def test_store_is_capped(tmp_path):
    store = SettingsStore(tmp_path / "p.json")
    for i in range(MAX_PHONES + 5):
        store.put(f"p{i}", {}, i)
    data = json.loads((tmp_path / "p.json").read_text())
    assert len(data) == MAX_PHONES and "p0" not in data
