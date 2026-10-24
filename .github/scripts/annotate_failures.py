"""Turn pytest junit failures into GitHub annotations (readable without login)."""

import sys
import xml.etree.ElementTree as ET


def esc(s):
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


root = ET.parse(sys.argv[1]).getroot()
for case in root.iter("testcase"):
    for tag in ("failure", "error"):
        node = case.find(tag)
        if node is not None:
            text = (node.get("message") or "") + "\n" + (node.text or "")
            print(f"::error title={case.get('classname')}.{case.get('name')}::{esc(text[-1500:])}")
