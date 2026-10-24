// Run by tests/test_js.py with node.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { validateLayout } from "../../web/layoutlib.js";

// Every shipped layout passes validation unchanged in its controls' meaning.
const dir = new URL("../../web/layouts/", import.meta.url);
for (const f of readdirSync(dir).filter((f) => f.endsWith(".json") && f !== "index.json")) {
  const raw = JSON.parse(readFileSync(new URL(f, dir)));
  const v = validateLayout(raw);
  assert.equal(v.controls.length, raw.controls.length, f);
  assert.equal(v.controls.filter((c) => c.type === "status").length, 1, f);
}

// Hostile or broken input is cleaned up or rejected.
assert.throws(() => validateLayout({}), /Not an OpenSteer layout/);
assert.throws(() => validateLayout({ controls: [{ type: "status", x: 0, y: 0, w: 10, h: 10 }] }), /no usable controls/);
const v = validateLayout({
  name: "x".repeat(100),
  controls: [
    { type: "button", map: "A", x: -50, y: 200, w: 500, h: "big", label: "<img src=x onerror=alert(1)>" },
    { type: "button", map: "NOPE", x: 1, y: 1, w: 5, h: 5 },
    { type: "script", x: 1, y: 1, w: 5, h: 5 },
    { type: "wheel", lock: 99999, x: 10, y: 10, w: 30, h: 30 },
  ],
});
assert.equal(v.name.length, 40);
assert.equal(v.controls.length, 3);                         // bad button and unknown type dropped; status added
const [btn, wheel, status] = v.controls;
assert.deepEqual([btn.x, btn.y], [0, 98]);
assert.ok(btn.x + btn.w <= 100 && btn.y + btn.h <= 100);
assert.equal(btn.label.length, 12);                          // labels are shown as text, never HTML
assert.equal(wheel.lock, 1440);
assert.equal(status.type, "status");
assert.equal(v.group, "Custom");
console.log("ok");
