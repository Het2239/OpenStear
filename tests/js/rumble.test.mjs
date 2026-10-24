// Run by tests/test_js.py with node.
import assert from "node:assert/strict";
import { rumblePattern } from "../../web/rumble.js";

const total = (p) => p.reduce((a, b) => a + b, 0);
const duty = (p) => p.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b, 0) / total(p);

assert.deepEqual(rumblePattern(1), [2000]);                 // full: solid
assert.ok(Math.abs(duty(rumblePattern(0.5)) - 0.5) < 0.01); // half: half the time on
assert.ok(duty(rumblePattern(0.25)) < duty(rumblePattern(0.75)));
assert.ok(total(rumblePattern(0.3)) >= 2000);               // fills the window
assert.ok(rumblePattern(0.01)[0] >= 6);                     // never a pulse too short to feel
console.log("ok");
import { revPattern } from "../../web/rumble.js";
const gap = (p) => p[0] + p[1];
assert.ok(gap(revPattern(1)) < gap(revPattern(0.5)) && gap(revPattern(0.5)) < gap(revPattern(0)));
assert.ok(revPattern(1).reduce((a, b) => a + b, 0) >= 2000);
console.log("ok rev");
