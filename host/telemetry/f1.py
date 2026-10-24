"""Decoder for EA/Codemasters F1 23, F1 24 and F1 25 UDP telemetry.

Enable it in the game: Settings -> Telemetry Settings -> UDP Telemetry On,
port 20777, format 2023/2024/2025. Only the player's car is decoded, from
these packets: Session (1), Lap Data (2), Car Telemetry (6), Car Status (7)
and Car Damage (10). Layouts follow EA's published specification; per-car
sizes are worked out from the packet length, so small additions at the end
of a car's record in later games don't break decoding.
"""

import struct

HEADER = struct.Struct("<HBBBBBQfIIBB")      # 29 bytes (2023+)
NUM_CARS = 22
FORMATS = (2023, 2024, 2025)

SESSION, LAP_DATA, CAR_TELEMETRY, CAR_STATUS, CAR_DAMAGE = 1, 2, 6, 7, 10

# Car telemetry (60 bytes per car): speed, throttle, steer, brake, clutch,
# gear, engineRPM, drs, revLightsPercent, revLightsBitValue,
# brakesTemperature[4], tyresSurfaceTemperature[4], tyresInnerTemperature[4],
# engineTemperature, tyresPressure[4], surfaceType[4]
CAR_TELEMETRY_CAR = struct.Struct("<HfffBbHBBH4H4B4BH4f4B")
# Car status (55 bytes per car), up to tyresAgeLaps, then the ERS part.
CAR_STATUS_A = struct.Struct("<BBBBBfffHHBBHBBBb")    # ... vehicleFiaFlags
# then enginePowerICE, enginePowerMGUK, ersStoreEnergy, ersDeployMode
CAR_STATUS_ERS = struct.Struct("<fffB")
ERS_MAX_J = 4_000_000

# Tyre arrays in the spec are ordered RL, RR, FL, FR; we send FL, FR, RL, RR.
_TYRE_ORDER = (2, 3, 0, 1)
COMPOUNDS = {16: "S", 17: "M", 18: "H", 7: "I", 8: "W", 15: "W", 19: "S", 20: "M", 21: "H", 22: "H"}


def _tyres(values):
    return [values[i] for i in _TYRE_ORDER]


class F1Decoder:
    """Feed it datagrams; `summary()` is the latest state for the phone."""

    def __init__(self):
        self.state = {}
        self.game = None        # e.g. "F1 25"
        self.packets = 0

    def feed(self, data):
        if len(data) < HEADER.size:
            return False
        fmt, year, _, _, _, pid, _, _, _, _, player, _ = HEADER.unpack_from(data)
        if fmt not in FORMATS and not (fmt > 2025 and year >= 25):
            return False
        if player >= NUM_CARS:
            return False   # spectating: no player car
        body = memoryview(data)[HEADER.size:]
        try:
            if pid == CAR_TELEMETRY:
                self._telemetry(body, player)
            elif pid == CAR_STATUS:
                self._status(body, player)
            elif pid == LAP_DATA:
                self._lap(body, player, fmt)
            elif pid == SESSION:
                self._session(body)
            elif pid == CAR_DAMAGE:
                self._damage(body, player)
            else:
                return False
        except struct.error:
            return False
        self.game = f"F1 {year}" if year else "F1"
        self.packets += 1
        return True

    def _stride(self, body, trailer, minimum):
        stride = (len(body) - trailer) // NUM_CARS
        if stride < minimum:
            raise struct.error("packet too short")
        return stride

    def _telemetry(self, body, player):
        stride = self._stride(body, 3, CAR_TELEMETRY_CAR.size)
        v = CAR_TELEMETRY_CAR.unpack_from(body, player * stride)
        speed, throttle, _, brake, _, gear, rpm, drs, rev = v[:9]
        surface = v[14:18]
        self.state.update(speed=speed, throttle=round(throttle, 3), brake=round(brake, 3),
                          gear=gear, rpm=rpm, drs=bool(drs), rev=rev, tyreTemp=_tyres(surface))

    def _status(self, body, player):
        stride = self._stride(body, 0, 55)
        off = player * stride
        v = CAR_STATUS_A.unpack_from(body, off)
        (_, _, _, _, pit_limiter, fuel, _, fuel_laps, max_rpm, _, _, drs_allowed, _,
         _, visual, tyre_age, _) = v
        _, _, energy, deploy = CAR_STATUS_ERS.unpack_from(body, off + CAR_STATUS_A.size)
        self.state.update(pitLimiter=bool(pit_limiter), fuel=round(fuel, 2),
                          fuelLaps=round(fuel_laps, 2), maxRpm=max_rpm, drsAllowed=bool(drs_allowed),
                          compound=COMPOUNDS.get(visual, "?"), tyreAge=tyre_age,
                          ers=round(max(0.0, min(1.0, energy / ERS_MAX_J)), 3), ersMode=deploy)

    def _lap(self, body, player, fmt):
        stride = self._stride(body, 2, 50)
        off = player * stride
        last, cur = struct.unpack_from("<II", body, off)
        # Sector/delta fields: 10 bytes in 2023, 12 in 2024+ (minute parts added).
        base = off + 8 + (10 if fmt == 2023 else 12) + 12
        pos, lap, _, _, _, invalid = struct.unpack_from("<6B", body, base)
        self.state.update(lastLap=last, curLap=cur, pos=pos, lap=lap, invalid=bool(invalid))

    def _session(self, body):
        # weather, trackTemperature, airTemperature, totalLaps
        total = struct.unpack_from("<B", body, 3)[0]
        self.state["totalLaps"] = total

    def _damage(self, body, player):
        stride = self._stride(body, 0, 16)
        wear = struct.unpack_from("<4f", body, player * stride)
        self.state["tyreWear"] = [round(w, 1) for w in _tyres(wear)]

    def summary(self):
        return dict(self.state)
