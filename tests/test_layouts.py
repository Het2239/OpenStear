"""Static checks for web/layouts/*.json and the phone/host button list."""

import json
import re
from itertools import combinations
from pathlib import Path

import pytest

from host.mapper import DEFAULT_BUTTONS

WEB = Path(__file__).resolve().parent.parent / "web"
CONTROLS_JS = (WEB / "controls.js").read_text()
IDS = json.loads((WEB / "layouts" / "index.json").read_text())
AXES = {"lx", "ly", "rx", "ry", "lt", "rt"}
TYPES = set(re.search(r"export const TYPES = \{([^}]*)\}", CONTROLS_JS).group(1).replace(" ", "").split(","))
DECORATIVE = {"panel"}


def js_list(name):
    body = re.search(rf"export const {name} = \[(.*?)\];", CONTROLS_JS, re.S).group(1)
    return re.findall(r'"([A-Z_]+)"', body)


def load(layout_id):
    return json.loads((WEB / "layouts" / f"{layout_id}.json").read_text())


def test_phone_and_host_agree_on_button_bits():
    assert js_list("BUTTONS") == DEFAULT_BUTTONS


def test_index_lists_every_layout_file():
    files = {p.stem for p in (WEB / "layouts").glob("*.json")} - {"index"}
    assert set(IDS) == files
    assert len(IDS) == len(set(IDS))


@pytest.mark.parametrize("layout_id", IDS)
def test_layout_is_valid(layout_id):
    layout = load(layout_id)
    assert layout["id"] == layout_id
    assert layout["name"] and layout["group"] in ("Racing", "Controller")
    assert isinstance(layout["tilt"], bool)
    assert sum(c["type"] == "status" for c in layout["controls"]) == 1, "needs one status bar"

    for c in layout["controls"]:
        where = f"{layout_id}: {c}"
        assert c["type"] in TYPES, where
        assert 0 <= c["x"] and 0 <= c["y"] and c["w"] > 0 and c["h"] > 0, where
        assert c["x"] + c["w"] <= 100.001 and c["y"] + c["h"] <= 100.001, where
        if c["type"] == "button":
            assert c["map"] in DEFAULT_BUTTONS, where
        if c["type"] == "pedal":
            assert c["axis"] in AXES, where
        if c["type"] == "stick":
            assert c["axes"] in (["lx", "ly"], ["rx", "ry"]), where


@pytest.mark.parametrize("layout_id", IDS)
def test_controls_do_not_overlap(layout_id):
    boxes = [c for c in load(layout_id)["controls"] if c["type"] not in DECORATIVE]

    def overlap(a, b):
        return (a["x"] < b["x"] + b["w"] - 0.001 and b["x"] < a["x"] + a["w"] - 0.001
                and a["y"] < b["y"] + b["h"] - 0.001 and b["y"] < a["y"] + a["h"] - 0.001)

    clashes = [(a.get("label", a["type"]), b.get("label", b["type"]))
               for a, b in combinations(boxes, 2) if overlap(a, b)]
    assert not clashes, f"{layout_id}: overlapping controls {clashes}"
