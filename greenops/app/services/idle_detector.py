"""Detection verdicts: provider-neutral identity + telemetry -> IdlenessRecord.

Decision order (first match wins):

  1. Exemption tag            -> EXEMPT   (protects the resource at every stage)
  2. DISK                     -> ORPHANED if unattached, ACTIVE if attached
  3. VM not running           -> STOPPED
  4. VM telemetry missing or
     coverage < min_coverage  -> UNKNOWN  (never IDLE on absent data)
  5. CPU max  >= threshold    -> ACTIVE
  6. Network  >= threshold    -> ACTIVE
  7. otherwise                -> IDLE     (CPU AND network both below threshold)

Thresholds are strict (<): a VM sitting exactly on a threshold is ACTIVE.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from app.config import EnergyPolicy, IdlePolicy, energy_policy, idle_policy
from app.models.idleness import (
    Exemption,
    IdleState,
    IdlenessRecord,
    LifecycleState,
    ResourceIdentity,
    ResourceKind,
    Telemetry,
)
from app.services.energy_calculator import compute_energy


def find_exemption(tags: dict[str, str], policy: IdlePolicy = idle_policy) -> Exemption:
    """Case-insensitive match of any configured exemption key with a truthy value."""
    wanted = {k.lower() for k in policy.exemption_tag_keys}
    truthy = {v.lower() for v in policy.exemption_true_values}
    for key, value in tags.items():
        if key.lower() in wanted and str(value).strip().lower() in truthy:
            return Exemption(exempt=True, tag_key=key, tag_value=str(value))
    return Exemption()


def _observed_idle_hours(identity: ResourceIdentity, telemetry: Telemetry) -> float:
    """Hours of the window during which the resource existed (a young VM has fewer)."""
    start = telemetry.window_start
    if identity.created_at is not None and identity.created_at > start:
        start = identity.created_at
    hours = (telemetry.window_end - start).total_seconds() / 3600.0
    return max(hours, 0.0)


def classify(
    identity: ResourceIdentity,
    telemetry: Optional[Telemetry],
    now: dt.datetime,
    policy: IdlePolicy = idle_policy,
    energy: EnergyPolicy = energy_policy,
) -> IdlenessRecord:
    def record(
        state: IdleState,
        reason: str,
        exemption: Exemption = Exemption(),
        with_energy_hours: Optional[float] = None,
    ) -> IdlenessRecord:
        return IdlenessRecord(
            identity=identity,
            state=state,
            reason=reason,
            exemption=exemption,
            telemetry=telemetry,
            energy=(
                compute_energy(identity.kind, with_energy_hours, energy)
                if with_energy_hours is not None
                else None
            ),
            evaluated_at=now,
        )

    # 1. Exemption wins over everything, including missing telemetry.
    exemption = find_exemption(identity.tags, policy)
    if exemption.exempt:
        return record(
            IdleState.EXEMPT,
            f"exempted by tag {exemption.tag_key}={exemption.tag_value}",
            exemption,
        )

    # 2. Storage: attachment is the signal, not utilization.
    if identity.kind is ResourceKind.DISK:
        if identity.lifecycle is LifecycleState.UNATTACHED:
            return record(
                IdleState.ORPHANED,
                f"disk not attached to any compute resource (provider state: {identity.provider_state})",
                with_energy_hours=(
                    _observed_idle_hours(identity, telemetry) if telemetry is not None else 0.0
                ),
            )
        if identity.lifecycle is LifecycleState.ATTACHED:
            return record(IdleState.ACTIVE, "disk is attached")
        return record(
            IdleState.UNKNOWN,
            f"disk in transitional state {identity.provider_state!r}; not judged",
        )

    # 3. VM that is not running draws no idle compute power; transitional states
    #    (pending, stopping, provisioning, ...) are not judged.
    if identity.lifecycle is LifecycleState.STOPPED:
        return record(
            IdleState.STOPPED,
            f"VM not running (provider state: {identity.provider_state})",
        )
    if identity.lifecycle is not LifecycleState.RUNNING:
        return record(
            IdleState.UNKNOWN,
            f"VM in transitional state {identity.provider_state!r}; not judged",
        )

    # 4. Positive evidence only: missing or sparse telemetry is UNKNOWN.
    if (
        telemetry is None
        or telemetry.cpu_maximum is None
        or telemetry.network_mb_per_day is None
    ):
        return record(IdleState.UNKNOWN, "no CPU/network telemetry returned for the window")
    if telemetry.coverage < policy.min_coverage:
        return record(
            IdleState.UNKNOWN,
            f"telemetry coverage {telemetry.coverage:.0%} below required {policy.min_coverage:.0%}",
        )

    # 5-6. Any signal above threshold means the VM is doing work.
    if telemetry.cpu_maximum >= policy.cpu_threshold_pct:
        return record(
            IdleState.ACTIVE,
            f"peak CPU {telemetry.cpu_maximum:.2f}% >= {policy.cpu_threshold_pct:.2f}%",
        )
    if telemetry.network_mb_per_day >= policy.network_threshold_mb_day:
        return record(
            IdleState.ACTIVE,
            f"network {telemetry.network_mb_per_day:.2f} MB/day >= {policy.network_threshold_mb_day:.2f} MB/day",
        )

    # 7. Both signals below threshold over a trusted window.
    return record(
        IdleState.IDLE,
        f"peak CPU {telemetry.cpu_maximum:.2f}% < {policy.cpu_threshold_pct:.2f}% and "
        f"network {telemetry.network_mb_per_day:.2f} MB/day < {policy.network_threshold_mb_day:.2f} MB/day "
        f"over {telemetry.window_days:.1f} days",
        with_energy_hours=_observed_idle_hours(identity, telemetry),
    )


def is_vm_idle(
    cpu_maximum: float,
    network_mb_per_day: float,
    policy: IdlePolicy = idle_policy,
) -> bool:
    """Backward-compatible boolean helper (both signals strictly below threshold)."""
    return cpu_maximum < policy.cpu_threshold_pct and network_mb_per_day < policy.network_threshold_mb_day
