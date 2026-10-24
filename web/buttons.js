// Button edges with minimum press/release lengths.
//
// Controls report presses and releases the moment they happen. Each button
// then plays those edges back so that every press lasts at least MIN_DOWN_MS
// and every gap at least MIN_UP_MS. That way a tap shorter than one packet,
// or a burst of taps, still reaches the game as separate presses long enough
// for a game polling once per frame (~16 ms) to see.

export const MIN_DOWN_MS = 40;
export const MIN_UP_MS = 35;
const MAX_QUEUE = 12;  // edges waiting per button (~6 presses)

export class ButtonLatch {
  constructor() {
    this.reset();
  }

  reset() {
    this.held = new Map();   // control id -> mask it holds right now
    this.raw = 0;            // OR of all held masks
    this.out = 0;            // mask we report
    this.since = new Map();  // bit -> time `out` last changed for it
    this.queue = new Map();  // bit -> pending edges (true = press)
  }

  // A control now holds `mask` (0 when released).
  hold(id, mask, now) {
    if (mask) this.held.set(id, mask);
    else this.held.delete(id);
    let raw = 0;
    for (const m of this.held.values()) raw |= m;
    const changed = raw ^ this.raw;
    this.raw = raw;
    for (let bit = 1; bit && bit <= changed; bit <<= 1) {
      if (!(changed & bit)) continue;
      const q = this.queue.get(bit) || [];
      // Edges alternate, so when full, dropping the last one together with
      // this new one removes a whole tap and keeps the final state right.
      if (q.length >= MAX_QUEUE) q.pop();
      else q.push(!!(raw & bit));
      this.queue.set(bit, q);
    }
    return this.output(now);
  }

  // Apply queued edges whose turn has come; returns the mask to send.
  output(now) {
    for (const [bit, q] of this.queue) {
      while (q.length) {
        const down = !!(this.out & bit);
        if (q[0] === down) { q.shift(); continue; }  // already there
        const minMs = down ? MIN_DOWN_MS : MIN_UP_MS;
        if (now - (this.since.get(bit) ?? -Infinity) < minMs) break;
        this.out ^= bit;
        this.since.set(bit, now);
        q.shift();
      }
      if (!q.length) this.queue.delete(bit);
    }
    return this.out;
  }

  // True while some edge is still waiting for its minimum time.
  get pending() {
    return this.queue.size > 0;
  }
}
