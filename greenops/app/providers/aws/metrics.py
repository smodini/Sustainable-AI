"""CloudWatch telemetry for EC2, fetched in bulk with GetMetricData.

The previous implementation issued three get_metric_statistics calls per instance
(sequential, N+1), took only ``datapoints[0]`` of the network sum, and returned 0.0 for
"no data" -- which the detector then read as idle. This version:

  * batches up to 125 instances (4 queries each, under the 500-query API limit) per call,
  * follows NextToken so long windows are not truncated,
  * sums every network datapoint, and
  * returns ``None`` (not 0) when CloudWatch has no data, so the detector yields UNKNOWN.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from typing import Any, Optional, Sequence

from app.models.idleness import Telemetry
from app.providers.common import build_telemetry

log = logging.getLogger(__name__)

PERIOD_SECONDS = 3600
QUERIES_PER_INSTANCE = 4
MAX_QUERIES_PER_CALL = 500
INSTANCES_PER_CALL = MAX_QUERIES_PER_CALL // QUERIES_PER_INSTANCE  # 125

# (query-id suffix, metric name, statistic)
_QUERIES = (
    ("cpu_avg", "CPUUtilization", "Average"),
    ("cpu_max", "CPUUtilization", "Maximum"),
    ("net_in", "NetworkIn", "Sum"),
    ("net_out", "NetworkOut", "Sum"),
)


def _queries_for(batch: Sequence[tuple[str, Optional[dt.datetime]]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for idx, (instance_id, _created) in enumerate(batch):
        for suffix, metric, stat in _QUERIES:
            queries.append(
                {
                    "Id": f"i{idx}_{suffix}",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/EC2",
                            "MetricName": metric,
                            "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                        },
                        "Period": PERIOD_SECONDS,
                        "Stat": stat,
                    },
                    "ReturnData": True,
                }
            )
    return queries


def _run(
    cw: Any, queries: list[dict[str, Any]], start: dt.datetime, end: dt.datetime
) -> dict[str, list[float]]:
    """Execute one GetMetricData request, following NextToken; return values per query id."""
    values: dict[str, list[float]] = defaultdict(list)
    token: Optional[str] = None
    while True:
        kwargs: dict[str, Any] = {
            "MetricDataQueries": queries,
            "StartTime": start,
            "EndTime": end,
            "ScanBy": "TimestampAscending",
        }
        if token:
            kwargs["NextToken"] = token
        resp = cw.get_metric_data(**kwargs)
        for result in resp.get("MetricDataResults", []):
            status = result.get("StatusCode")
            if status not in (None, "Complete", "PartialData"):
                log.warning("CloudWatch query %s returned status %s", result.get("Id"), status)
                continue
            values[result["Id"]].extend(float(v) for v in result.get("Values", []))
        token = resp.get("NextToken")
        if not token:
            return values


def fetch_ec2_telemetry(
    cw: Any,
    instances: Sequence[tuple[str, Optional[dt.datetime]]],
    start: dt.datetime,
    end: dt.datetime,
) -> dict[str, Telemetry]:
    """Telemetry per instance id. ``instances`` is a sequence of (instance_id, launch_time)."""
    out: dict[str, Telemetry] = {}
    for offset in range(0, len(instances), INSTANCES_PER_CALL):
        batch = instances[offset : offset + INSTANCES_PER_CALL]
        values = _run(cw, _queries_for(batch), start, end)
        for idx, (instance_id, created) in enumerate(batch):
            cpu_avgs = values.get(f"i{idx}_cpu_avg", [])
            cpu_maxs = values.get(f"i{idx}_cpu_max", [])
            net_in = values.get(f"i{idx}_net_in", [])
            net_out = values.get(f"i{idx}_net_out", [])
            out[instance_id] = build_telemetry(
                window_start=start,
                window_end=end,
                created_at=created,
                cpu_average_pct=(sum(cpu_avgs) / len(cpu_avgs)) if cpu_avgs else None,
                cpu_maximum_pct=max(cpu_maxs) if cpu_maxs else None,
                network_total_bytes=(sum(net_in) + sum(net_out)) if (net_in or net_out) else None,
                cpu_points=len(cpu_avgs),
            )
    return out
