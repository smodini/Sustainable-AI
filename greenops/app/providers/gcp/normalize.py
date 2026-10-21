"""GCP Compute REST shapes + Cloud Monitoring metrics -> Idleness Schema (pure functions).

GCP idle storage condition: persistent disk with no ``users`` (not attached to any
instance), the counterpart of an AWS EBS ``available`` volume and an Azure ``Unattached``
managed disk. GCP calls tags "labels".

Cloud Monitoring metrics used (VM):
  compute.googleapis.com/instance/cpu/utilization            fraction 0-1  (converted to %)
  compute.googleapis.com/instance/network/received_bytes_count   bytes (DELTA, summed)
  compute.googleapis.com/instance/network/sent_bytes_count       bytes (DELTA, summed)
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Sequence

from app.models.idleness import (
    LifecycleState,
    Provider,
    ResourceIdentity,
    ResourceKind,
    Telemetry,
)
from app.providers.common import build_telemetry, parse_ts

GCP_VM_METRICS = (
    "compute.googleapis.com/instance/cpu/utilization",
    "compute.googleapis.com/instance/network/received_bytes_count",
    "compute.googleapis.com/instance/network/sent_bytes_count",
)

_STATUS_LIFECYCLE = {
    "RUNNING": LifecycleState.RUNNING,
    "TERMINATED": LifecycleState.STOPPED,  # GCP's name for a stopped instance
    "STOPPED": LifecycleState.STOPPED,
    "SUSPENDED": LifecycleState.STOPPED,
}


def _last(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _region_from_zone(zone_url: str) -> str:
    zone = _last(zone_url)  # e.g. us-central1-a
    return zone.rsplit("-", 1)[0]


_parse_ts = parse_ts


def normalize_instance(raw: dict[str, Any], project: str) -> ResourceIdentity:
    zone = _last(raw["zone"])
    status = raw["status"]
    return ResourceIdentity(
        provider=Provider.GCP,
        account_id=project,
        resource_id=f"//compute.googleapis.com/projects/{project}/zones/{zone}/instances/{raw['name']}",
        kind=ResourceKind.VM,
        name=raw["name"],
        region=_region_from_zone(raw["zone"]),
        resource_type=_last(raw["machineType"]) if raw.get("machineType") else None,
        provider_state=status,
        lifecycle=_STATUS_LIFECYCLE.get(status, LifecycleState.OTHER),
        created_at=_parse_ts(raw.get("creationTimestamp")),
        tags=dict(raw.get("labels") or {}),
    )


def normalize_disk(raw: dict[str, Any], project: str) -> ResourceIdentity:
    if "zone" in raw:
        location_kind, location = "zones", _last(raw["zone"])
        region = _region_from_zone(raw["zone"])
    else:  # regional disk
        location_kind, location = "regions", _last(raw["region"])
        region = location
    status = raw.get("status", "UNKNOWN")
    if raw.get("users"):
        lifecycle = LifecycleState.ATTACHED
    elif status == "READY":
        lifecycle = LifecycleState.UNATTACHED
    else:
        lifecycle = LifecycleState.OTHER
    size = raw.get("sizeGb")
    return ResourceIdentity(
        provider=Provider.GCP,
        account_id=project,
        resource_id=f"//compute.googleapis.com/projects/{project}/{location_kind}/{location}/disks/{raw['name']}",
        kind=ResourceKind.DISK,
        name=raw["name"],
        region=region,
        resource_type=_last(raw["type"]) if raw.get("type") else None,
        provider_state=status,
        lifecycle=lifecycle,
        created_at=_parse_ts(raw.get("creationTimestamp")),
        size_gb=float(size) if size is not None else None,
        tags=dict(raw.get("labels") or {}),
    )


def gcp_telemetry(
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    created_at: Optional[dt.datetime],
    cpu_utilization_mean_points: Sequence[float],
    cpu_utilization_max_points: Sequence[float],
    received_bytes: Sequence[float],
    sent_bytes: Sequence[float],
) -> Telemetry:
    """Hourly Cloud Monitoring points -> Telemetry. CPU arrives as a 0-1 fraction."""
    has_net = bool(received_bytes or sent_bytes)
    return build_telemetry(
        window_start=window_start,
        window_end=window_end,
        created_at=created_at,
        cpu_average_pct=(
            sum(cpu_utilization_mean_points) / len(cpu_utilization_mean_points) * 100.0
            if cpu_utilization_mean_points
            else None
        ),
        cpu_maximum_pct=max(cpu_utilization_max_points) * 100.0 if cpu_utilization_max_points else None,
        network_total_bytes=(sum(received_bytes) + sum(sent_bytes)) if has_net else None,
        cpu_points=len(cpu_utilization_mean_points),
    )
