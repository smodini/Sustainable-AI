"""Azure ARM shapes + Azure Monitor metrics -> Idleness Schema (pure functions).

Inputs are ARM JSON (camelCase), as returned by the REST API and Azure Resource Graph.

Azure idle storage condition: managed disk ``diskState == "Unattached"`` with no
``managedBy`` (the counterpart of an AWS EBS volume in state ``available``).
``Reserved`` means attached to a deallocated VM and counts as attached.

Azure Monitor metrics used (VM): ``Percentage CPU`` (Average, Maximum; percent) and
``Network In Total`` / ``Network Out Total`` (Total; bytes).
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

AZURE_VM_METRICS = ("Percentage CPU", "Network In Total", "Network Out Total")

_POWER_LIFECYCLE = {
    "PowerState/running": LifecycleState.RUNNING,
    "PowerState/stopped": LifecycleState.STOPPED,
    "PowerState/deallocated": LifecycleState.STOPPED,
}

_ATTACHED_DISK_STATES = {"Attached", "Reserved"}


def subscription_from_id(arm_id: str) -> str:
    parts = arm_id.strip("/").split("/")
    return parts[1] if len(parts) > 1 and parts[0].lower() == "subscriptions" else ""


_parse_ts = parse_ts


def _power_state(vm: dict[str, Any]) -> str:
    props = vm.get("properties", {})
    # Resource Graph: properties.extended.instanceView.powerState.code
    code = props.get("extended", {}).get("instanceView", {}).get("powerState", {}).get("code")
    if code:
        return code
    # REST ?$expand=instanceView: properties.instanceView.statuses[]
    for status in props.get("instanceView", {}).get("statuses", []):
        if str(status.get("code", "")).startswith("PowerState/"):
            return status["code"]
    return "PowerState/unknown"


def normalize_vm(vm: dict[str, Any]) -> ResourceIdentity:
    props = vm.get("properties", {})
    power = _power_state(vm)
    return ResourceIdentity(
        provider=Provider.AZURE,
        account_id=subscription_from_id(vm["id"]),
        resource_id=vm["id"].lower(),
        kind=ResourceKind.VM,
        name=vm["name"],
        region=vm["location"],
        resource_type=props.get("hardwareProfile", {}).get("vmSize"),
        provider_state=power,
        lifecycle=_POWER_LIFECYCLE.get(power, LifecycleState.OTHER),
        created_at=_parse_ts(props.get("timeCreated")),
        tags=dict(vm.get("tags") or {}),
    )


def normalize_disk(disk: dict[str, Any]) -> ResourceIdentity:
    props = disk.get("properties", {})
    state = props.get("diskState", "Unknown")
    managed_by = disk.get("managedBy") or props.get("managedBy")
    if managed_by or state in _ATTACHED_DISK_STATES:
        lifecycle = LifecycleState.ATTACHED
    elif state == "Unattached":
        lifecycle = LifecycleState.UNATTACHED
    else:
        lifecycle = LifecycleState.OTHER
    size = props.get("diskSizeGB")
    return ResourceIdentity(
        provider=Provider.AZURE,
        account_id=subscription_from_id(disk["id"]),
        resource_id=disk["id"].lower(),
        kind=ResourceKind.DISK,
        name=disk["name"],
        region=disk["location"],
        resource_type=(disk.get("sku") or {}).get("name"),
        provider_state=state,
        lifecycle=lifecycle,
        created_at=_parse_ts(props.get("timeCreated")),
        size_gb=float(size) if size is not None else None,
        tags=dict(disk.get("tags") or {}),
    )


def azure_telemetry(
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    created_at: Optional[dt.datetime],
    cpu_average_points: Sequence[float],
    cpu_maximum_points: Sequence[float],
    network_in_total_bytes: Sequence[float],
    network_out_total_bytes: Sequence[float],
) -> Telemetry:
    """Hourly Azure Monitor datapoints (empty sequence == no data) -> Telemetry."""
    has_net = bool(network_in_total_bytes or network_out_total_bytes)
    return build_telemetry(
        window_start=window_start,
        window_end=window_end,
        created_at=created_at,
        cpu_average_pct=(sum(cpu_average_points) / len(cpu_average_points)) if cpu_average_points else None,
        cpu_maximum_pct=max(cpu_maximum_points) if cpu_maximum_points else None,
        network_total_bytes=(sum(network_in_total_bytes) + sum(network_out_total_bytes)) if has_net else None,
        cpu_points=len(cpu_average_points),
    )
