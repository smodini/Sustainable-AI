"""Cloud Monitoring telemetry for GCE instances, fetched project-wide.

Four ``timeSeries.list`` queries per project (CPU mean, CPU max, bytes received, bytes
sent), each hourly-aligned, regardless of how many instances there are -- not per-VM
calls. Series are keyed by (zone, instance_name) and merged per timestamp:

  * network metrics emit one series per ``loadbalanced`` label value, so values at the
    same timestamp are SUMMED;
  * a duplicated CPU series is reduced with max / mean as appropriate;
  * coverage counts distinct timestamps, so duplicates never inflate it.

An instance absent from a query's result gets an empty list, which the normalizer turns
into ``None`` (no data), never zero.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Callable, Optional, Sequence

from app.models.idleness import Telemetry
from app.providers.gcp.normalize import gcp_telemetry
from app.providers.rest import RestClient

MONITORING = "https://monitoring.googleapis.com/v3"
PERIOD = "3600s"

CPU = "compute.googleapis.com/instance/cpu/utilization"
RX = "compute.googleapis.com/instance/network/received_bytes_count"
TX = "compute.googleapis.com/instance/network/sent_bytes_count"

InstanceKey = tuple[str, str]  # (zone, instance_name)


def _rfc3339(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _point_value(point: dict[str, Any]) -> Optional[float]:
    v = point.get("value", {})
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "int64Value" in v:  # int64 is serialized as a string in JSON
        return float(v["int64Value"])
    return None


def _query(
    rest: RestClient,
    project: str,
    metric: str,
    aligner: str,
    start: dt.datetime,
    end: dt.datetime,
    reduce: Callable[[Sequence[float]], float],
    wanted: set[InstanceKey],
) -> dict[InstanceKey, list[float]]:
    params = {
        "filter": f'metric.type="{metric}" AND resource.type="gce_instance"',
        "interval.startTime": _rfc3339(start),
        "interval.endTime": _rfc3339(end),
        "aggregation.alignmentPeriod": PERIOD,
        "aggregation.perSeriesAligner": aligner,
        "view": "FULL",
    }
    by_ts: dict[InstanceKey, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for page in rest.paginate(f"{MONITORING}/projects/{project}/timeSeries", params):
        for series in page.get("timeSeries", []):
            key = (
                series.get("resource", {}).get("labels", {}).get("zone", ""),
                series.get("metric", {}).get("labels", {}).get("instance_name", ""),
            )
            if key not in wanted:
                continue
            for point in series.get("points", []):
                value = _point_value(point)
                if value is not None:
                    by_ts[key][point["interval"]["endTime"]].append(value)
    return {k: [reduce(vs) for _, vs in sorted(ts.items())] for k, ts in by_ts.items()}


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def fetch_gcp_telemetry(
    rest: RestClient,
    project: str,
    instances: Sequence[tuple[InstanceKey, Optional[dt.datetime]]],
    start: dt.datetime,
    end: dt.datetime,
) -> dict[InstanceKey, Telemetry]:
    """Telemetry per (zone, name). ``instances`` is (key, creation_time) pairs."""
    wanted = {key for key, _ in instances}
    cpu_mean = _query(rest, project, CPU, "ALIGN_MEAN", start, end, _mean, wanted)
    cpu_max = _query(rest, project, CPU, "ALIGN_MAX", start, end, max, wanted)
    rx = _query(rest, project, RX, "ALIGN_DELTA", start, end, sum, wanted)
    tx = _query(rest, project, TX, "ALIGN_DELTA", start, end, sum, wanted)
    return {
        key: gcp_telemetry(
            window_start=start,
            window_end=end,
            created_at=created,
            cpu_utilization_mean_points=cpu_mean.get(key, []),
            cpu_utilization_max_points=cpu_max.get(key, []),
            received_bytes=rx.get(key, []),
            sent_bytes=tx.get(key, []),
        )
        for key, created in instances
    }
