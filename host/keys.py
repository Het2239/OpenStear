"""Keyboard keys a control can send: name -> (Windows scan code, extended, Linux KEY_ code).

Scan codes (set 1) are what games reading raw/DirectInput keyboards expect.
web/keys.js lists the same names; tests check they match.
"""

_KEYS = []
# Letters and digits, in keyboard order.
for name, sc in zip("QWERTYUIOP", range(0x10, 0x1A)):
    _KEYS.append((name, sc, False, sc))
for name, sc in zip("ASDFGHJKL", range(0x1E, 0x27)):
    _KEYS.append((name, sc, False, sc))
for name, sc in zip("ZXCVBNM", range(0x2C, 0x33)):
    _KEYS.append((name, sc, False, sc))
for i, sc in enumerate(range(0x02, 0x0C)):
    _KEYS.append((str((i + 1) % 10), sc, False, sc))
for i in range(10):
    _KEYS.append((f"F{i + 1}", 0x3B + i, False, 59 + i))
_KEYS += [("F11", 0x57, False, 87), ("F12", 0x58, False, 88)]
for i in range(11):
    _KEYS.append((f"F{13 + i}", 0x64 + i, False, 183 + i))
_KEYS.append(("F24", 0x76, False, 194))

_KEYS += [
    ("ESC", 0x01, False, 1), ("TAB", 0x0F, False, 15), ("CAPSLOCK", 0x3A, False, 58),
    ("SHIFT", 0x2A, False, 42), ("CTRL", 0x1D, False, 29), ("ALT", 0x38, False, 56),
    ("RSHIFT", 0x36, False, 54), ("RCTRL", 0x1D, True, 97), ("RALT", 0x38, True, 100),
    ("SPACE", 0x39, False, 57), ("ENTER", 0x1C, False, 28), ("BACKSPACE", 0x0E, False, 14),
    ("MINUS", 0x0C, False, 12), ("EQUAL", 0x0D, False, 13),
    ("LBRACKET", 0x1A, False, 26), ("RBRACKET", 0x1B, False, 27),
    ("SEMICOLON", 0x27, False, 39), ("APOSTROPHE", 0x28, False, 40), ("GRAVE", 0x29, False, 41),
    ("BACKSLASH", 0x2B, False, 43), ("COMMA", 0x33, False, 51), ("PERIOD", 0x34, False, 52),
    ("SLASH", 0x35, False, 53),
    ("UP", 0x48, True, 103), ("DOWN", 0x50, True, 108),
    ("LEFT", 0x4B, True, 105), ("RIGHT", 0x4D, True, 106),
    ("INSERT", 0x52, True, 110), ("DELETE", 0x53, True, 111),
    ("HOME", 0x47, True, 102), ("END", 0x4F, True, 107),
    ("PAGEUP", 0x49, True, 104), ("PAGEDOWN", 0x51, True, 109),
    ("KP0", 0x52, False, 82), ("KP1", 0x4F, False, 79), ("KP2", 0x50, False, 80),
    ("KP3", 0x51, False, 81), ("KP4", 0x4B, False, 75), ("KP5", 0x4C, False, 76),
    ("KP6", 0x4D, False, 77), ("KP7", 0x47, False, 71), ("KP8", 0x48, False, 72),
    ("KP9", 0x49, False, 73), ("KPPLUS", 0x4E, False, 78), ("KPMINUS", 0x4A, False, 74),
    ("KPMULTIPLY", 0x37, False, 55), ("KPDOT", 0x53, False, 83), ("KPENTER", 0x1C, True, 96),
]

KEYS = {name: (sc, ext, code) for name, sc, ext, code in _KEYS}
KEY_NAMES = [name for name, *_ in _KEYS]
