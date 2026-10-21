"""Provider-agnostic helpers shared by every telemetry normalizer."""

from __future__ import annotations

import datetime as dt
import math
from typing import Optional

from app.models.idleness import Telemetry

BYTES_PER_MB = 1024 * 1024


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def observation_window(
    days: int, now: Optional[dt.datetime] = None
) -> tuple[dt.datetime, dt.datetime]:
    """Hour-aligned (start, end) window so period-3600 buckets are whole, not partial."""
    now = now or utc_now()
    end = now.replace(minute=0, second=0, microsecond=0)
    return end - dt.timedelta(days=days), end


def existed_hours(
    window_start: dt.datetime, window_end: dt.datetime, created_at: Optional[dt.datetime]
) -> float:
    """Hours of the window during which the resource existed."""
    start = created_at if created_at is not None and created_at > window_start else window_start
    return max((window_end - start).total_seconds() / 3600.0, 0.0)


def coverage(received_points: int, hours_existed: float) -> float:
    """Fraction (0-1) of expected hourly datapoints received."""
    expected = math.ceil(hours_existed)
    if expected <= 0:
        return 0.0
    return min(received_points / expected, 1.0)


def bytes_to_mb_per_day(total_bytes: float, hours_existed: float) -> Optional[float]:
    days = hours_existed / 24.0
    if days <= 0:
        return None
    return (total_bytes / BYTES_PER_MB) / days


def build_telemetry(
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    created_at: Optional[dt.datetime],
    cpu_average_pct: Optional[float],
    cpu_maximum_pct: Optional[float],
    network_total_bytes: Optional[float],
    cpu_points: int,
) -> Telemetry:
    """Assemble a Telemetry from already-unit-normalized numbers (CPU %, network bytes)."""
    hours = existed_hours(window_start, window_end, created_at)
    return Telemetry(
        window_start=window_start,
        window_end=window_end,
        cpu_average=None if cpu_average_pct is None else round(min(max(cpu_average_pct, 0.0), 100.0), 4),
        cpu_maximum=None if cpu_maximum_pct is None else round(min(max(cpu_maximum_pct, 0.0), 100.0), 4),
        network_mb_per_day=(
            None
            if network_total_bytes is None
            else (
                None
                if (v := bytes_to_mb_per_day(network_total_bytes, hours)) is None
                else round(v, 4)
            )
        ),
        coverage=coverage(cpu_points, hours),
    )
