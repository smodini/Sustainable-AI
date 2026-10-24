"""Deterministic synthetic grid for orchestration tests (no network, no randomness)."""
from __future__ import annotations

import datetime as dt
import math

from app.orchestration.models import IntensityPoint

UTC = dt.timezone.utc
# region -> (base gCO2/kWh, solar dip depth, noise amplitude)
PROFILES = {"solar-west": (380.0, 200.0, 8.0), "steady-east": (420.0, 25.0, 8.0)}


def truth(region: str, t: dt.datetime) -> float:
    """Noise-free intensity: solar dip centred 13:00 UTC, cleaner on weekends."""
    base, dip, _ = PROFILES[region]
    h = t.hour + t.minute / 60
    y = base - dip * max(0.0, math.cos((h - 13) * 2 * math.pi / 24))
    return y - (25.0 if t.weekday() >= 5 else 0.0)


def noise(region: str, t: dt.datetime) -> float:
    amp = PROFILES[region][2]
    i = int(t.timestamp() // 3600) + (7 if region == "steady-east" else 0)
    return ((math.sin(i * 12.9898) * 43758.5453) % 1.0 - 0.5) * 2 * amp


def observed(region: str, t: dt.datetime) -> float:
    return truth(region, t) + noise(region, t)


class SyntheticProvider:
    """IntensityProvider: hourly points on [start, end)."""

    def __init__(self, regions=("solar-west", "steady-east"), scale: float = 1.0, broken=()):
        self.regions, self.scale, self.broken = regions, scale, set(broken)
        self.calls = []

    def history(self, region, start, end):
        self.calls.append((region, start, end))
        if region in self.broken:
            return []
        out, t = [], start.replace(minute=0, second=0, microsecond=0)
        while t < end:
            out.append(IntensityPoint(time=t, g_co2_per_kwh=max(observed(region, t) * self.scale, 0.0)))
            t += dt.timedelta(hours=1)
        return out


def hourly(region: str, start: dt.datetime, hours: int, fn=observed) -> list[IntensityPoint]:
    return [IntensityPoint(time=start + dt.timedelta(hours=h), g_co2_per_kwh=fn(region, start + dt.timedelta(hours=h)))
            for h in range(hours)]
