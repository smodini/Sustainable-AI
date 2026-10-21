"""AWS scan: CloudWatch + EC2 -> list[IdlenessRecord] -> ScanSummary.

Exempt, stopped and unattached/attached resources are all reported (previously exempt
resources were silently dropped from the inventory). Telemetry is only fetched for
running, non-exempt VMs.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable, Optional

from app.config import EnergyPolicy, IdlePolicy, energy_policy, idle_policy
from app.models.idleness import (
    IdlenessRecord,
    LifecycleState,
    Provider,
    ScanSummary,
)
from app.providers.aws import client as aws_client
from app.providers.aws.instances import get_all_regions, iter_instances, iter_unattached_volumes
from app.providers.aws.metrics import fetch_ec2_telemetry
from app.providers.aws.normalize import (
    instance_id_from_resource_id,
    normalize_ebs_volume,
    normalize_ec2_instance,
)
from app.providers.common import observation_window, utc_now
from app.services.idle_detector import classify, find_exemption

log = logging.getLogger(__name__)


def scan_region(
    region: str,
    account_id: str,
    ec2: Any,
    cw: Any,
    policy: IdlePolicy,
    energy: EnergyPolicy,
    now: dt.datetime,
) -> list[IdlenessRecord]:
    start, end = observation_window(policy.observation_days, now)

    vm_identities = [normalize_ec2_instance(i, account_id, region) for i in iter_instances(ec2)]
    disk_identities = [
        normalize_ebs_volume(v, account_id, region) for v in iter_unattached_volumes(ec2)
    ]

    # Only running, non-exempt VMs need telemetry.
    needs_telemetry = [
        (instance_id_from_resource_id(v.resource_id), v.created_at)
        for v in vm_identities
        if v.lifecycle is LifecycleState.RUNNING and not find_exemption(v.tags, policy).exempt
    ]
    telemetry = fetch_ec2_telemetry(cw, needs_telemetry, start, end) if needs_telemetry else {}

    records: list[IdlenessRecord] = []
    for ident in vm_identities:
        t = telemetry.get(instance_id_from_resource_id(ident.resource_id))
        records.append(classify(ident, t, now, policy, energy))
    for ident in disk_identities:
        records.append(classify(ident, None, now, policy, energy))
    return records


def scan_aws(
    policy: IdlePolicy = idle_policy,
    energy: EnergyPolicy = energy_policy,
    regions: Optional[list[str]] = None,
    account_id: Optional[str] = None,
    now: Optional[dt.datetime] = None,
    ec2_factory: Callable[[str], Any] = aws_client.get_ec2_client,
    cw_factory: Callable[[str], Any] = aws_client.get_cloudwatch_client,
) -> ScanSummary:
    now = now or utc_now()
    account_id = account_id or aws_client.get_account_id()
    regions = regions or get_all_regions()

    records: list[IdlenessRecord] = []
    errors: list[str] = []
    for region in regions:
        try:
            records.extend(
                scan_region(region, account_id, ec2_factory(region), cw_factory(region), policy, energy, now)
            )
        except Exception as exc:
            # One failing region (SCP block, opt-in not enabled, throttling) must not
            # abort the whole scan, but it must not be silent either: it is logged and
            # recorded on the summary so consumers know the totals are incomplete.
            log.exception("AWS scan failed for region %s; continuing", region)
            errors.append(f"{region}: {type(exc).__name__}: {exc}")
    return ScanSummary.from_records(Provider.AWS, now, records, errors)
