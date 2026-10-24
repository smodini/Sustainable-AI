"""Azure scan: ARM + Azure Monitor -> list[IdlenessRecord] -> ScanSummary.

Same contract as the AWS and GCP scanners: exempt/stopped/attached resources are
reported, telemetry is fetched only for running non-exempt VMs, a failing subscription is
recorded rather than fatal, and a VM whose metrics could not be read is UNKNOWN, never IDLE.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, Optional

from app.config import EnergyPolicy, IdlePolicy, energy_policy, idle_policy
from app.models.idleness import IdlenessRecord, LifecycleState, Provider, ScanSummary
from app.providers.azure import client as azure_client
from app.providers.azure.instances import iter_unattached_disks, iter_vms
from app.providers.azure.metrics import fetch_azure_telemetry
from app.providers.azure.normalize import normalize_disk, normalize_vm
from app.providers.common import observation_window, utc_now
from app.providers.rest import RestClient
from app.services.idle_detector import classify, find_exemption

log = logging.getLogger(__name__)


def scan_subscription(
    subscription: str,
    rest: RestClient,
    policy: IdlePolicy,
    energy: EnergyPolicy,
    now: dt.datetime,
    errors: list[str],
) -> list[IdlenessRecord]:
    start, end = observation_window(policy.observation_days, now)

    vms = [normalize_vm(v) for v in iter_vms(rest, subscription)]
    disks = [normalize_disk(d) for d in iter_unattached_disks(rest, subscription)]

    needs_telemetry = [
        (v.resource_id, v.created_at)
        for v in vms
        if v.lifecycle is LifecycleState.RUNNING and not find_exemption(v.tags, policy).exempt
    ]
    telemetry, failures = fetch_azure_telemetry(rest, needs_telemetry, start, end) if needs_telemetry else ({}, {})
    errors.extend(f"{subscription}: metrics {vm_id}: {msg}" for vm_id, msg in sorted(failures.items()))

    records = [classify(v, telemetry.get(v.resource_id), now, policy, energy) for v in vms]
    records += [classify(d, None, now, policy, energy) for d in disks]
    return records


def scan_azure(
    policy: IdlePolicy = idle_policy,
    energy: EnergyPolicy = energy_policy,
    subscriptions: Optional[list[str]] = None,
    now: Optional[dt.datetime] = None,
    rest_factory: Callable[[], RestClient] = azure_client.get_rest_client,
) -> ScanSummary:
    now = now or utc_now()
    subscriptions = subscriptions or azure_client.configured_subscriptions()
    if not subscriptions:
        raise ValueError("no Azure subscriptions configured: pass subscriptions or set GREENOPS_AZURE_SUBSCRIPTIONS")
    rest = rest_factory()

    records: list[IdlenessRecord] = []
    errors: list[str] = []
    for subscription in subscriptions:
        try:
            records.extend(scan_subscription(subscription, rest, policy, energy, now, errors))
        except Exception as exc:
            log.exception("Azure scan failed for subscription %s; continuing", subscription)
            errors.append(f"{subscription}: {type(exc).__name__}: {exc}")
    return ScanSummary.from_records(Provider.AZURE, now, records, errors)
