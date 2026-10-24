"""Azure Monitor telemetry for VMs: one metrics call per VM (3 metrics each), run with
bounded concurrency. (The regional ``metrics:getBatch`` API could cut call count further;
per-VM keeps the failure domain small: one bad VM leaves only itself UNKNOWN.)

Azure returns a row for every hour in the timespan, with the aggregation keys *absent*
when there was no data; only rows that actually carry a value are counted, so gaps lower
coverage instead of reading as zero.
"""

from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, Sequence

from app.models.idleness import Telemetry
from app.providers.azure.normalize import AZURE_VM_METRICS, azure_telemetry
from app.providers.rest import RestClient

log = logging.getLogger(__name__)

ARM = "https://management.azure.com"
METRICS_API = "2018-01-01"
MAX_WORKERS = 8


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _values(response: dict[str, Any], metric: str, aggregation: str) -> list[float]:
    for item in response.get("value", []):
        if item.get("name", {}).get("value") == metric:
            return [
                float(row[aggregation])
                for ts in item.get("timeseries", [])
                for row in ts.get("data", [])
                if row.get(aggregation) is not None
            ]
    return []


def fetch_vm_telemetry(
    rest: RestClient,
    vm_id: str,
    created_at: Optional[dt.datetime],
    start: dt.datetime,
    end: dt.datetime,
) -> Telemetry:
    resp = rest.get_json(
        f"{ARM}{vm_id}/providers/microsoft.insights/metrics",
        {
            "api-version": METRICS_API,
            "metricnames": ",".join(AZURE_VM_METRICS),
            "aggregation": "Average,Maximum,Total",
            "interval": "PT1H",
            "timespan": f"{_iso(start)}/{_iso(end)}",
        },
    )
    cpu, rx, tx = AZURE_VM_METRICS
    return azure_telemetry(
        window_start=start,
        window_end=end,
        created_at=created_at,
        cpu_average_points=_values(resp, cpu, "average"),
        cpu_maximum_points=_values(resp, cpu, "maximum"),
        network_in_total_bytes=_values(resp, rx, "total"),
        network_out_total_bytes=_values(resp, tx, "total"),
    )


def fetch_azure_telemetry(
    rest: RestClient,
    vms: Sequence[tuple[str, Optional[dt.datetime]]],
    start: dt.datetime,
    end: dt.datetime,
    max_workers: int = MAX_WORKERS,
) -> tuple[dict[str, Telemetry], dict[str, str]]:
    """(telemetry by vm id, error message by vm id). A failed VM is absent from the first
    dict so the detector yields UNKNOWN for it."""
    telemetry: dict[str, Telemetry] = {}
    failures: dict[str, str] = {}

    def one(item: tuple[str, Optional[dt.datetime]]) -> None:
        vm_id, created = item
        try:
            telemetry[vm_id] = fetch_vm_telemetry(rest, vm_id, created, start, end)
        except Exception as exc:
            log.warning("Azure metrics failed for %s: %s", vm_id, exc)
            failures[vm_id] = f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(one, vms))
    return telemetry, failures
