"""GCP scan: Compute + Cloud Monitoring -> list[IdlenessRecord] -> ScanSummary.

Mirrors the AWS scanner: exempt, stopped and attached resources are reported rather than
dropped, telemetry is fetched only for running non-exempt VMs, and one failing project
is recorded on the summary instead of aborting the scan. A failed *telemetry* fetch
leaves the project's VMs UNKNOWN (never IDLE) and is also recorded.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, Optional

from app.config import EnergyPolicy, IdlePolicy, energy_policy, idle_policy
from app.models.idleness import IdlenessRecord, LifecycleState, Provider, ScanSummary
from app.providers.common import observation_window, utc_now
from app.providers.gcp import client as gcp_client
from app.providers.gcp.instances import iter_instances, iter_unattached_disks
from app.providers.gcp.metrics import InstanceKey, fetch_gcp_telemetry
from app.providers.gcp.normalize import normalize_disk, normalize_instance
from app.providers.rest import RestClient
from app.services.idle_detector import classify, find_exemption

log = logging.getLogger(__name__)


def instance_key(resource_id: str) -> InstanceKey:
    """(zone, name) from //compute.googleapis.com/projects/P/zones/Z/instances/N."""
    parts = resource_id.split("/")
    return parts[parts.index("zones") + 1], parts[parts.index("instances") + 1]


def scan_project(
    project: str,
    rest: RestClient,
    policy: IdlePolicy,
    energy: EnergyPolicy,
    now: dt.datetime,
    errors: list[str],
) -> list[IdlenessRecord]:
    start, end = observation_window(policy.observation_days, now)

    vms = [normalize_instance(i, project) for i in iter_instances(rest, project, errors)]
    disks = [normalize_disk(d, project) for d in iter_unattached_disks(rest, project, errors)]

    needs_telemetry = [
        (instance_key(v.resource_id), v.created_at)
        for v in vms
        if v.lifecycle is LifecycleState.RUNNING and not find_exemption(v.tags, policy).exempt
    ]
    telemetry = {}
    if needs_telemetry:
        try:
            telemetry = fetch_gcp_telemetry(rest, project, needs_telemetry, start, end)
        except Exception as exc:
            log.exception("GCP telemetry failed for project %s; VMs left UNKNOWN", project)
            errors.append(f"{project}: telemetry: {type(exc).__name__}: {exc}")

    records = [classify(v, telemetry.get(instance_key(v.resource_id)), now, policy, energy) for v in vms]
    records += [classify(d, None, now, policy, energy) for d in disks]
    return records


def scan_gcp(
    policy: IdlePolicy = idle_policy,
    energy: EnergyPolicy = energy_policy,
    projects: Optional[list[str]] = None,
    now: Optional[dt.datetime] = None,
    rest_factory: Callable[[], RestClient] = gcp_client.get_rest_client,
) -> ScanSummary:
    now = now or utc_now()
    projects = projects or gcp_client.configured_projects()
    if not projects:
        raise ValueError("no GCP projects configured: pass projects or set GREENOPS_GCP_PROJECTS")
    rest = rest_factory()

    records: list[IdlenessRecord] = []
    errors: list[str] = []
    for project in projects:
        try:
            records.extend(scan_project(project, rest, policy, energy, now, errors))
        except Exception as exc:
            log.exception("GCP scan failed for project %s; continuing", project)
            errors.append(f"{project}: {type(exc).__name__}: {exc}")
    return ScanSummary.from_records(Provider.GCP, now, records, errors)
