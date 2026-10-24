// Run by tests/test_js.py with node.
import assert from "node:assert/strict";
import { parseTarget } from "../../web/controls.js";

assert.equal(parseTarget("A").kind, "button");
assert.deepEqual(parseTarget("key:W"), { kind: "key", key: "W" });
assert.equal(parseTarget("key:NOPE"), null);
assert.deepEqual(parseTarget("axis:-lx"), { kind: "axis", axis: "lx", value: -1 });
assert.deepEqual(parseTarget("axis:+rt"), { kind: "axis", axis: "rt", value: 1 });
assert.equal(parseTarget("axis:-rt"), null);      // triggers only go one way
assert.equal(parseTarget("axis:+zz"), null);
assert.equal(parseTarget(undefined), null);
console.log("ok");
