import asyncio

from host import server
from host.latch import MIN_DOWN_S, MIN_UP_S, ButtonLatch

A = frozenset({"A"})
NONE = frozenset()


def run(latch, events, until, step=0.001):
    """Feed (time, buttons) packets; sample output every `step`; return rising/falling edges."""
    events = sorted(events, key=lambda e: e[0])  # stable: keeps press before release
    edges, prev, t, i = [], NONE, 0.0, 0
    while t <= until:
        while i < len(events) and events[i][0] <= t:
            latch.update(events[i][1], t)
            i += 1
        out = latch.output(t)
        if out != prev:
            edges.append((round(t, 3), "A" in out))
            prev = out
        t += step
    return edges


def test_press_and_release_in_same_instant_is_kept():
    edges = run(ButtonLatch(), [(0.0, A), (0.0, NONE)], until=0.2)
    assert edges[0] == (0.0, True)
    assert edges[1][1] is False and edges[1][0] >= MIN_DOWN_S


def test_burst_of_taps_becomes_separate_presses():
    # Five taps squeezed into 5 ms (e.g. packets bunched by Wi-Fi).
    burst = [(i * 0.0005, A if i % 2 == 0 else NONE) for i in range(10)]
    edges = run(ButtonLatch(), burst, until=1.0)
    presses = [t for t, down in edges if down]
    assert len(presses) == 5
    for (t0, d0), (t1, _) in zip(edges, edges[1:]):
        assert t1 - t0 >= (MIN_DOWN_S if d0 else MIN_UP_S) - 1e-9


def test_normal_presses_are_not_delayed():
    edges = run(ButtonLatch(), [(0.010, A), (0.200, NONE), (0.300, A), (0.400, NONE)], until=0.5)
    assert edges == [(0.01, True), (0.2, False), (0.3, True), (0.4, False)]


def test_spam_beyond_queue_is_bounded_and_never_sticks():
    latch = ButtonLatch()
    for i in range(201):                       # ends with a press...
        latch.update(A if i % 2 == 0 else NONE, 0.0)
    latch.update(NONE, 0.0)                    # ...then the final release
    assert len(latch.queue["A"]) <= 12
    assert "A" not in latch.output(10.0)       # released once the queue drains


class RecordingPad:
    def __init__(self, name):
        self.history = []

    def apply(self, state):
        if not self.history or self.history[-1][1] != state.buttons:
            self.history.append((asyncio.get_running_loop().time(), state.buttons))

    def reset(self):
        self.apply(server.NEUTRAL)

    def close(self):
        pass


async def test_server_spreads_bunched_presses(aiohttp_client):
    pads = []

    def factory(name):
        pads.append(RecordingPad(name))
        return pads[-1]

    client = await aiohttp_client(server.create_app("k", factory))
    ws = await client.ws_connect("/ws?k=k")
    await ws.send_json({"t": "hello", "id": "p"})
    await ws.receive_json()
    # Three taps arriving back to back, as a stalled Wi-Fi link would deliver them.
    for seq in range(1, 7):
        await ws.send_json({"t": "s", "seq": seq, "btn": 1 if seq % 2 else 0})
    await asyncio.sleep(0.5)
    presses = [b for _, b in pads[0].history if "A" in b]
    assert len(presses) == 3, pads[0].history
    await ws.close()


def test_audit_logs_lost_taps_and_cancels(caplog):
    audit = server.TapAudit()
    audit.phone(10, 0, 0.0)                       # baseline from the first packet
    audit.pad(frozenset({"A"}), "p")
    audit.pad(frozenset(), "p")
    audit.phone(13, 2, 0.1)                       # phone saw 3 taps, 2 cancels
    audit.pad(frozenset({"B"}), "p")              # 2 presses (A, B) for 3 taps
    audit.check("p", 0.2)                         # not settled yet: no verdict
    assert not caplog.records
    audit.check("p", 1.0)
    text = caplog.text
    assert "1 tap(s) registered on the phone did not reach the pad" in text
    assert "cancelled 2 touch(es)" in text
    caplog.clear()
    audit.check("p", 2.0)                         # already reported
    assert not caplog.records
