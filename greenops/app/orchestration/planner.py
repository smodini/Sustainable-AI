"""Window and region search: where and when is the workload least carbon-intensive?

For every allowed region and every whole-hour start between the earliest feasible start
and (deadline - duration), score the contiguous window by its mean forecast intensity and
pick the lowest. Windows must lie entirely inside the forecast; a window the forecast does
not cover is never guessed at.

Emissions follow the patent's energy shape:  kWh = P x PUE x T,  kg = kWh x gCO2e/kWh / 1000.
"""

from __future__ import annotations

import datetime as dt
from typing import Mapping, Optional, Sequence

from app.config import energy_policy
from app.orchestration.models import (
    FlexibleWorkload,
    ForecastSource,
    IntensityPoint,
    Placement,
    ceil_hour,
)

HOUR = dt.timedelta(hours=1)


class NoFeasiblePlacement(RuntimeError):
    pass


def _by_hour(points: Sequence[IntensityPoint]) -> dict[dt.datetime, float]:
    return {p.time: p.g_co2_per_kwh for p in points}


def window_mean(series: Mapping[dt.datetime, float], start: dt.datetime, hours: int) -> Optional[float]:
    """Mean intensity over [start, start+hours), or None if the forecast does not cover it."""
    vals = []
    for h in range(hours):
        v = series.get(start + h * HOUR)
        if v is None:
            return None
        vals.append(v)
    return sum(vals) / hours


def emissions_kg(power_kw: float, pue: float, hours: int, avg_g_per_kwh: float) -> float:
    return power_kw * pue * hours * avg_g_per_kwh / 1000.0


def plan(
    workload: FlexibleWorkload,
    forecasts: Mapping[str, Sequence[IntensityPoint]],
    now: dt.datetime,
    source: ForecastSource,
    *,
    pue: float = energy_policy.pue,
    risk_margin: Optional[Mapping[str, float]] = None,
    not_before: Optional[dt.datetime] = None,
) -> Placement:
    """Best placement for ``workload``.

    ``risk_margin[region]`` (e.g. recent forecast MAPE as a fraction) inflates a region's
    forecast *for ranking only*, so a region the model has been getting wrong must promise
    proportionally more savings to win. Reported figures are un-inflated expectations.
    """
    margin = risk_margin or {}
    first = ceil_hour(max(now, workload.earliest_start, not_before or workload.earliest_start))
    last_start = workload.deadline - workload.duration_hours * HOUR
    if first > last_start:
        raise NoFeasiblePlacement(f"{workload.name}: no start time fits before the deadline")

    if not workload.flexible:
        last_start = first  # inflexible: immediate start only, in the home region only
    regions = (workload.home_region,) if not workload.flexible else workload.allowed_regions
    series = {r: _by_hour(forecasts[r]) for r in regions if forecasts.get(r)}
    if workload.home_region not in series:
        raise NoFeasiblePlacement(f"{workload.name}: no forecast for home region {workload.home_region}")

    # Baseline: start as soon as possible in the home region.
    base_avg = window_mean(series[workload.home_region], first, workload.duration_hours)
    if base_avg is None:
        raise NoFeasiblePlacement(f"{workload.name}: forecast does not cover an immediate run")
    baseline_kg = emissions_kg(workload.power_kw, pue, workload.duration_hours, base_avg)

    best: Optional[tuple[float, dt.datetime, int, str, float]] = None  # (score, start, home_rank, region, avg)
    s = first
    while s <= last_start:
        for region, ser in series.items():
            avg = window_mean(ser, s, workload.duration_hours)
            if avg is None:
                continue
            score = avg * (1.0 + margin.get(region, 0.0))
            rank = 0 if region == workload.home_region else 1
            cand = (score, s, rank, region, avg)
            # lowest score; ties -> earlier start, then prefer home region (no needless move)
            if best is None or (cand[0], cand[1], cand[2]) < (best[0], best[1], best[2]):
                best = cand
        s += HOUR
    if best is None:
        raise NoFeasiblePlacement(f"{workload.name}: forecast covers no full window before the deadline")

    _, start, _, region, avg = best
    kg = emissions_kg(workload.power_kw, pue, workload.duration_hours, avg)
    saved = baseline_kg - kg
    return Placement(
        workload=workload.name,
        region=region,
        start=start,
        end=start + workload.duration_hours * HOUR,
        expected_avg_g_per_kwh=round(avg, 3),
        expected_kg_co2e=round(kg, 4),
        baseline_region=workload.home_region,
        baseline_start=first,
        baseline_kg_co2e=round(baseline_kg, 4),
        savings_kg_co2e=round(saved, 4),
        savings_pct=round(100.0 * saved / baseline_kg, 2) if baseline_kg > 0 else 0.0,
        forecast_source=source,
        decided_at=now,
        reason=(
            f"lowest forecast intensity {avg:.1f} gCO2e/kWh in {region} starting {start:%Y-%m-%d %H:%M}Z "
            f"vs {base_avg:.1f} running now in {workload.home_region}"
            if workload.flexible
            else "workload is not flexible: runs as soon as possible in its home region"
        ),
    )
