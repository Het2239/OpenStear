// Run by tests/test_js.py with node.
import assert from "node:assert/strict";
import { ButtonLatch, MIN_DOWN_MS, MIN_UP_MS } from "../../web/buttons.js";

const A = 1;
function run(events, until) {
  const latch = new ButtonLatch();
  const edges = [];
  let prev = 0, i = 0;
  for (let t = 0; t <= until; t += 1) {
    while (i < events.length && events[i][0] <= t) { latch.hold("btn", events[i][1], t); i++; }
    const out = latch.output(t);
    if (out !== prev) { edges.push([t, !!(out & A)]); prev = out; }
  }
  return edges;
}

// A tap shorter than one packet still becomes a full press.
let e = run([[0, A], [2, 0]], 200);
assert.deepEqual(e[0], [0, true]);
assert.ok(e[1][0] >= MIN_DOWN_MS && e[1][1] === false);

// Spam: 6 taps in 6 ms -> 6 separate presses with minimum spacing.
const burst = [];
for (let k = 0; k < 12; k++) burst.push([k * 0.5, k % 2 ? 0 : A]);
e = run(burst, 1000);
assert.equal(e.filter(([, d]) => d).length, 6);
for (let k = 1; k < e.length; k++) {
  assert.ok(e[k][0] - e[k - 1][0] >= (e[k - 1][1] ? MIN_DOWN_MS : MIN_UP_MS));
}

// Normal presses pass straight through.
e = run([[10, A], [200, 0], [300, A], [400, 0]], 500);
assert.deepEqual(e, [[10, true], [200, false], [300, true], [400, false]]);

// Two controls holding the same button (e.g. DRS and PIT both = Y): one press.
const l = new ButtonLatch();
l.hold("drs", A, 0); l.hold("pit", A, 5); l.hold("drs", 0, 10);
assert.equal(l.output(100), A);
l.hold("pit", 0, 110);
assert.equal(l.output(200), 0);
// Endless spam stays bounded and never leaves the button stuck down.
const s = new ButtonLatch();
for (let k = 0; k < 301; k++) s.hold("b", k % 2 ? 0 : A, 0);
s.hold("b", 0, 0);
assert.ok(s.queue.get(A).length <= 12);
assert.equal(s.output(100000), 0);
console.log("ok");
