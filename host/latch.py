"""Keep button presses and gaps long enough for games to see them.

The phone already spaces button edges (web/buttons.js), but Wi-Fi can
deliver several packets at once, squeezing a press and its release into the
same millisecond. This replays the edges seen across packets so each press
lasts at least MIN_DOWN_S and each gap at least MIN_UP_S on the virtual pad.
"""

MIN_DOWN_S = 0.030
MIN_UP_S = 0.025
MAX_QUEUE = 12  # edges waiting per button (~6 presses)


class ButtonLatch:
    def __init__(self):
        self.reset()

    def reset(self):
        self.target = frozenset()   # buttons the latest packet says are down
        self.out = frozenset()      # buttons we report
        self.since = {}             # button -> time `out` last changed for it
        self.queue = {}             # button -> pending edges (True = press)

    def update(self, buttons, now):
        """Record a packet's buttons; returns the buttons to show now."""
        for b in buttons ^ self.target:
            q = self.queue.setdefault(b, [])
            # Edges alternate, so when full, dropping the last one together
            # with this new one removes a whole tap and keeps the final state.
            if len(q) >= MAX_QUEUE:
                q.pop()
            else:
                q.append(b in buttons)
        self.target = frozenset(buttons)
        return self.output(now)

    def output(self, now):
        out = set(self.out)
        for b in list(self.queue):
            q = self.queue[b]
            while q:
                down = b in out
                if q[0] == down:
                    q.pop(0)
                    continue
                min_s = MIN_DOWN_S if down else MIN_UP_S
                if now - self.since.get(b, float("-inf")) < min_s:
                    break
                out.symmetric_difference_update({b})
                self.since[b] = now
                q.pop(0)
            if not q:
                del self.queue[b]
        self.out = frozenset(out)
        return self.out

    def next_due(self):
        """Time when a queued edge becomes allowed, or None if nothing waits."""
        due = None
        for b, q in self.queue.items():
            if q:
                min_s = MIN_DOWN_S if b in self.out else MIN_UP_S
                t = self.since.get(b, float("-inf")) + min_s
                due = t if due is None else min(due, t)
        return due
