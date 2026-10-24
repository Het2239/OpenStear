"""Fake F1 25 telemetry for trying the phone dash without the game.

    python -m host.telemetry.sim [--port 20777] [--host 127.0.0.1]

Drives an imaginary car round laps: revs climb through the gears, the
shift lights and buzz kick in near the limiter, fuel and ERS drain, tyres
warm up and wear. Packets follow EA's F1 25 UDP layout (player car only;
the other 21 cars are zero).
"""

import argparse
import math
import socket
import struct
import time

FORMAT, YEAR = 2025, 25
PLAYER = 0


def header(pid, frame, player=PLAYER, fmt=FORMAT, year=YEAR):
    return struct.pack("<HBBBBBQfIIBB", fmt, year, 1, 0, 1, pid, 0xC0FFEE, frame / 60, frame, frame, player, 255)


def _cars(record, size, player=PLAYER):
    return b"".join(record if i == player else bytes(size) for i in range(22))


def telemetry_packet(frame, speed, gear, rpm, rev, drs, temps, player=PLAYER, fmt=FORMAT, year=YEAR):
    """temps: tyre surface temperatures in spec order RL, RR, FL, FR."""
    car = struct.pack("<HfffBbHBBH4H4B4BH4f4B", speed, 1.0, 0.0, 0.0, 0, gear, rpm, drs, rev, 0,
                      *[500] * 4, *temps, *temps, 100, *[23.0] * 4, *[0] * 4)
    return header(6, frame, player, fmt, year) + _cars(car, 60, player) + bytes([0, 255, 0])


def status_packet(frame, fuel, fuel_laps, ers_j, ers_mode, drs_allowed, compound=16, age=3,
                  player=PLAYER, fmt=FORMAT, year=YEAR):
    car = struct.pack("<BBBBBfffHHBBHBBBbfffBfffB", 0, 0, 1, 56, 0, fuel, 110.0, fuel_laps,
                      13000, 4000, 8, drs_allowed, 0, compound, compound, age, 0,
                      500000.0, 120000.0, ers_j, ers_mode, 0.0, 0.0, 0.0, 0)
    return header(7, frame, player, fmt, year) + _cars(car, 55, player)


def lap_packet(frame, last_ms, cur_ms, pos, lap, invalid=0, player=PLAYER, fmt=FORMAT, year=YEAR):
    sectors = (struct.pack("<HBHBHH", 0, 0, 0, 0, 0, 0) if fmt == 2023
               else struct.pack("<HBHBHBHB", 0, 0, 0, 0, 0, 0, 0, 0))
    car = struct.pack("<II", last_ms, cur_ms) + sectors + struct.pack("<fff", 0.0, 0.0, 0.0)
    car += struct.pack("<7B", pos, lap, 0, 0, 0, invalid, 0) + struct.pack("<2B", 0, 0)
    car += struct.pack("<6BHHB", 0, 0, 1, 4, 2, 0, 0, 0, 0)
    if fmt != 2023:
        car += struct.pack("<fB", 0.0, 0)
    return header(2, frame, player, fmt, year) + _cars(car, len(car), player) + bytes([255, 255])


def session_packet(frame, total_laps, player=PLAYER, fmt=FORMAT, year=YEAR):
    return header(1, frame, player, fmt, year) + bytes([0, 30, 22, total_laps]) + bytes(700)


def damage_packet(frame, wear, player=PLAYER, fmt=FORMAT, year=YEAR):
    """wear: tyre wear % in spec order RL, RR, FL, FR."""
    car = struct.pack("<4f", *wear) + bytes(42 - 16)
    return header(10, frame, player, fmt, year) + _cars(car, 42, player)


def run(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    lap_ms = 82_000
    start = time.monotonic()
    frame = 0
    print(f"Sending fake F1 25 telemetry to {host}:{port} (Ctrl+C to stop)")
    while True:
        t = time.monotonic() - start
        lap_t = (t * 1000) % lap_ms
        lap = int(t * 1000 // lap_ms) + 1
        # Accelerate through 8 gears every 9 s, then brake for a corner.
        phase = (t % 9) / 9
        gear = min(8, 1 + int(phase * 8))
        in_gear = (phase * 8) % 1
        rpm = int(8000 + 4500 * in_gear)
        rev = int(min(100, max(0, (rpm - 8000) / 45)))
        speed = int(80 + 230 * phase)
        temps = [int(85 + 15 * math.sin(t / 7 + i)) for i in range(4)]
        frame += 1
        sock.sendto(telemetry_packet(frame, speed, gear, rpm, rev, int(phase > 0.6), temps), (host, port))
        if frame % 6 == 0:
            fuel = max(0.0, 40 - t * 0.05)
            sock.sendto(status_packet(frame, fuel, fuel / 2.0 - 1.5, (math.sin(t / 5) + 1) * 2e6,
                                      2, int(phase > 0.4)), (host, port))
            sock.sendto(lap_packet(frame, lap_ms + 345 if lap > 1 else 0, int(lap_t), 3, lap), (host, port))
            sock.sendto(damage_packet(frame, [min(99.0, t * 0.2 + i) for i in range(4)]), (host, port))
        if frame % 120 == 0:
            sock.sendto(session_packet(frame, 58), (host, port))
        time.sleep(1 / 60)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=20777)
    args = p.parse_args()
    try:
        run(args.host, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
