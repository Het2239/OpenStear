"""Build full F1 packets from the spec's field lists and check the decoder."""

import struct

import pytest

from host.telemetry.f1 import F1Decoder

PLAYER = 5


def header(fmt, pid, year=None):
    year = year if year is not None else fmt % 100
    # packetFormat, gameYear, major, minor, packetVersion, packetId, sessionUID,
    # sessionTime, frameIdentifier, overallFrameIdentifier, playerCarIndex, secondary
    return struct.pack("<HBBBBBQfIIBB", fmt, year, 1, 2, 1, pid, 123456789, 12.5, 100, 100, PLAYER, 255)


def cars(make):
    """22 car records; every car but the player gets junk-ish values."""
    return b"".join(make(i == PLAYER, i) for i in range(22))


def telemetry_car(player, i):
    if not player:
        return struct.pack("<HfffBbHBBH4H4B4BH4f4B", 99, .1, 0, .1, 0, 1, 4000, 0, 5, 0,
                           *[300] * 4, *[50] * 4, *[60] * 4, 70, *[20.0] * 4, *[0] * 4)
    return struct.pack("<HfffBbHBBH4H4B4BH4f4B",
                       287, 0.9, -0.2, 0.0, 0, 7, 11250, 1, 86, 0x3FF,
                       610, 620, 630, 640,           # brakes RL RR FL FR
                       91, 92, 93, 94,               # tyre surface temps RL RR FL FR
                       95, 96, 97, 98, 105,          # inner temps, engine temp
                       22.1, 22.2, 22.3, 22.4, 0, 0, 0, 0)


def status_car(player, i):
    fuel, laps, energy, mode = (31.5, 4.25, 3_000_000.0, 3) if player else (90.0, 20.0, 0.0, 0)
    return struct.pack("<BBBBBfffHHBBHBBBb fff B fff B",
                       0, 0, 1, 56, 1 if player else 0, fuel, 110.0, laps,
                       13000, 4000, 8, 1 if player else 0, 0,
                       16, 16 if player else 17, 3 if player else 9, 0,
                       500000.0, 120000.0, energy, mode, 1.0, 2.0, 3.0, 0)


def lap_car(fmt):
    def make(player, i):
        last, cur, pos, lap, invalid = (83456, 41234, 3, 12, 1) if player else (90000, 1000, 15, 2, 0)
        if fmt == 2023:
            sectors = struct.pack("<HBHBHH", 1, 0, 2, 0, 3, 4)            # 10 bytes
        else:
            sectors = struct.pack("<HBHBHBHB", 1, 0, 2, 0, 3, 0, 4, 0)    # 12 bytes
        rec = struct.pack("<II", last, cur) + sectors + struct.pack("<fff", 1.0, 2.0, 0.0)
        rec += struct.pack("<7B", pos, lap, 0, 0, 1, invalid, 0)          # ... penalties
        rec += struct.pack("<2B", 0, 0)                                   # totalWarnings, cornerCutting
        rec += struct.pack("<6BHHB", 0, 0, 1, 4, 2, 0, 0, 0, 0)
        if fmt != 2023:
            rec += struct.pack("<fB", 310.5, 3)                           # speed trap (2024+)
        return rec
    return make


def damage_car(player, i):
    wear = (11.0, 12.0, 13.0, 14.0) if player else (90.0, 90.0, 90.0, 90.0)   # RL RR FL FR
    return struct.pack("<4f", *wear) + bytes(42 - 16)


@pytest.mark.parametrize("fmt", [2023, 2024, 2025])
def test_decodes_the_player_car(fmt):
    d = F1Decoder()
    assert d.feed(header(fmt, 6) + cars(telemetry_car) + bytes([0, 255, 8]))
    assert d.feed(header(fmt, 7) + cars(status_car))
    assert d.feed(header(fmt, 2) + cars(lap_car(fmt)) + bytes([255, 255]))
    session = bytes([0, 30, 22, 58]) + bytes(600)          # weather, track °C, air °C, totalLaps
    assert d.feed(header(fmt, 1) + session)
    assert d.feed(header(fmt, 10) + cars(damage_car))
    s = d.summary()
    assert (s["speed"], s["gear"], s["rpm"], s["rev"], s["drs"]) == (287, 7, 11250, 86, True)
    assert s["throttle"] == 0.9
    assert s["tyreTemp"] == [93, 94, 91, 92]               # FL FR RL RR
    assert (s["fuel"], s["fuelLaps"], s["maxRpm"]) == (31.5, 4.25, 13000)
    assert (s["compound"], s["tyreAge"], s["pitLimiter"], s["drsAllowed"]) == ("S", 3, True, True)
    assert (s["ers"], s["ersMode"]) == (0.75, 3)
    assert (s["lastLap"], s["curLap"], s["pos"], s["lap"], s["invalid"]) == (83456, 41234, 3, 12, True)
    assert s["totalLaps"] == 58
    assert s["tyreWear"] == [13.0, 14.0, 11.0, 12.0]
    assert d.game == f"F1 {fmt % 100}"


def test_ignores_other_games_and_garbage():
    d = F1Decoder()
    assert not d.feed(b"hello")
    assert not d.feed(header(2022, 6) + bytes(1400))       # older format: different header
    assert not d.feed(header(2024, 6)[:-2] + bytes([30, 255]) + bytes(10))   # spectator / short
    assert not d.feed(header(2024, 6) + bytes(100))        # truncated
    assert d.summary() == {}


async def test_listener_receives_forwards_and_reports():
    import asyncio
    import socket

    from host.telemetry.listener import TelemetryListener

    # A second socket stands in for another telemetry app.
    other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    other.bind(("127.0.0.1", 0))
    other.setblocking(False)
    listener = TelemetryListener(0, "127.0.0.1", forward=other.getsockname())
    await listener.start()
    port = listener._transport.get_extra_info("sockname")[1]
    assert listener.message() == {"t": "tele", "off": True}

    packet = header(2025, 6) + cars(telemetry_car) + bytes([0, 255, 8])
    game = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    game.sendto(packet, ("127.0.0.1", port))
    for _ in range(50):
        if listener.live:
            break
        await asyncio.sleep(0.01)
    msg = listener.message()
    assert msg["game"] == "F1 25" and msg["gear"] == 7 and msg["speed"] == 287
    assert "receiving from F1 25" in listener.status()
    await asyncio.sleep(0.05)
    assert other.recv(4096) == packet           # passed on unchanged
    listener.stop()
    game.close()
    other.close()


async def test_port_in_use_is_reported():
    import socket

    from host.telemetry.listener import TelemetryListener

    taken = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    taken.bind(("127.0.0.1", 0))
    listener = TelemetryListener(taken.getsockname()[1], "127.0.0.1")
    await listener.start()
    assert "in use" in listener.status()
    taken.close()


@pytest.mark.parametrize("fmt", [2023, 2024, 2025])
def test_simulator_packets_decode(fmt):
    from host.telemetry import sim

    d = F1Decoder()
    kw = {"player": 4, "fmt": fmt, "year": fmt % 100}
    assert d.feed(sim.telemetry_packet(1, 250, 6, 11000, 70, 1, [80, 81, 82, 83], **kw))
    assert d.feed(sim.status_packet(1, 20.0, 3.5, 2e6, 2, 1, **kw))
    assert d.feed(sim.lap_packet(1, 81000, 4000, 2, 7, **kw))
    assert d.feed(sim.damage_packet(1, [1, 2, 3, 4], **kw))
    s = d.summary()
    assert (s["gear"], s["pos"], s["lap"], s["ers"], s["tyreTemp"]) == (6, 2, 7, 0.5, [82, 83, 80, 81])
