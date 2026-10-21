"""Idleness Schema: the single, provider-neutral record produced by the Detection Layer.

Every provider module (AWS CloudWatch, GCP Cloud Monitoring, Azure Monitor) converts its
native inventory and telemetry into ``IdlenessRecord`` before any detection, energy
calculation, persistence or enforcement happens. Nothing downstream of the provider
modules ever sees a provider-specific field name or state string.

Provider-native idle conditions map onto one vocabulary:

    AWS  EC2 instance, state=running, low CPU + network   -> VM,   IDLE
    AWS  EBS volume,   State=available (unattached)       -> DISK, ORPHANED
    Azure VM, PowerState/running, low CPU + network       -> VM,   IDLE
    Azure managed disk, diskState=Unattached              -> DISK, ORPHANED
    GCP  Compute instance, status=RUNNING, low CPU + net  -> VM,   IDLE
    GCP  persistent disk with no ``users``                -> DISK, ORPHANED

Bump ``SCHEMA_VERSION`` on any breaking change; the enforcement layer (Go controller)
pins to it.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class Provider(StrEnum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"


class ResourceKind(StrEnum):
    VM = "vm"
    DISK = "disk"


class IdleState(StrEnum):
    """Detection verdict.

    UNKNOWN is deliberate and load-bearing: missing or sparse telemetry is *not* idle.
    A resource is only IDLE/ORPHANED on positive evidence, because the enforcement
    layer can snapshot and eventually delete what this layer flags.
    """

    ACTIVE = "active"
    STOPPED = "stopped"  # VM not running: no idle compute draw (its disks are judged separately)
    IDLE = "idle"  # VM: CPU and network both below policy thresholds
    ORPHANED = "orphaned"  # DISK: not attached to any compute resource
    EXEMPT = "exempt"  # carries a user-defined exemption tag
    UNKNOWN = "unknown"  # insufficient telemetry to decide


class LifecycleState(StrEnum):
    """Provider power/attachment states collapsed to one vocabulary."""

    RUNNING = "running"
    STOPPED = "stopped"  # includes Azure 'deallocated' and GCP 'TERMINATED'
    ATTACHED = "attached"
    UNATTACHED = "unattached"
    OTHER = "other"  # pending, stopping, provisioning, deleting, ...


class Telemetry(BaseModel):
    """Normalized utilization signals over the observation window.

    CPU is always percent (0-100); GCP reports a 0-1 fraction and is converted in the
    GCP normalizer. Network is always MB/day (1 MB = 1024*1024 bytes), in + out combined.
    ``None`` means "no data", never "zero".
    """

    model_config = ConfigDict(frozen=True)

    window_start: dt.datetime
    window_end: dt.datetime
    cpu_average: Optional[float] = Field(default=None, ge=0, le=100)
    cpu_maximum: Optional[float] = Field(default=None, ge=0, le=100)
    network_mb_per_day: Optional[float] = Field(default=None, ge=0)
    # Fraction of expected datapoints actually received (0-1), measured against the
    # part of the window in which the resource existed.
    coverage: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _check_window(self) -> "Telemetry":
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("telemetry window timestamps must be timezone-aware (UTC)")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self

    @property
    def window_days(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 86400.0


class Exemption(BaseModel):
    model_config = ConfigDict(frozen=True)

    exempt: bool = False
    tag_key: Optional[str] = None
    tag_value: Optional[str] = None


class EnergyWaste(BaseModel):
    """E_waste = P_idle x PUE x T, reported for the observed window and a monthly baseline."""

    model_config = ConfigDict(frozen=True)

    p_idle_kw: float = Field(ge=0)
    pue: float = Field(ge=1.0)
    idle_hours_observed: float = Field(ge=0)
    e_waste_kwh_observed: float = Field(ge=0)  # T = idle_hours_observed
    e_waste_kwh_monthly: float = Field(ge=0)  # T = 720 h (patent baseline: 108 kWh/VM)


class ResourceIdentity(BaseModel):
    """What a provider normalizer produces, before telemetry and verdict are attached."""

    model_config = ConfigDict(frozen=True)

    provider: Provider
    account_id: str  # AWS account / Azure subscription / GCP project
    resource_id: str  # provider-native stable identifier (ARN / ARM id / self-link)
    kind: ResourceKind
    name: str
    region: str
    resource_type: Optional[str] = None  # instance type, VM size, disk type
    provider_state: str  # raw native state string, kept for audit
    lifecycle: LifecycleState
    created_at: Optional[dt.datetime] = None
    size_gb: Optional[float] = Field(default=None, ge=0)  # disks
    tags: dict[str, str] = Field(default_factory=dict)  # AWS tags / Azure tags / GCP labels


class IdlenessRecord(BaseModel):
    """One row of the Idleness Schema."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    identity: ResourceIdentity
    state: IdleState
    reason: str  # human-readable justification for the verdict
    exemption: Exemption = Field(default_factory=Exemption)
    telemetry: Optional[Telemetry] = None
    energy: Optional[EnergyWaste] = None  # set only when state is IDLE/ORPHANED and P_idle is defined
    evaluated_at: dt.datetime

    # Convenience pass-throughs so consumers need not reach into ``identity``.
    @property
    def provider(self) -> Provider:
        return self.identity.provider

    @property
    def resource_id(self) -> str:
        return self.identity.resource_id

    @property
    def is_wasteful(self) -> bool:
        return self.state in (IdleState.IDLE, IdleState.ORPHANED)


class ScanSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: Provider
    scanned_at: dt.datetime
    total: int
    active: int
    stopped: int
    idle: int
    orphaned: int
    exempt: int
    unknown: int
    monthly_waste_kwh: float
    # Non-empty means the scan is incomplete (e.g. a region failed); totals undercount.
    errors: list[str] = Field(default_factory=list)
    records: list[IdlenessRecord]

    @classmethod
    def from_records(
        cls,
        provider: Provider,
        scanned_at: dt.datetime,
        records: list[IdlenessRecord],
        errors: Optional[list[str]] = None,
    ) -> "ScanSummary":
        def count(state: IdleState) -> int:
            return sum(1 for r in records if r.state is state)

        monthly = sum(r.energy.e_waste_kwh_monthly for r in records if r.energy is not None)
        return cls(
            provider=provider,
            scanned_at=scanned_at,
            total=len(records),
            active=count(IdleState.ACTIVE),
            stopped=count(IdleState.STOPPED),
            idle=count(IdleState.IDLE),
            orphaned=count(IdleState.ORPHANED),
            exempt=count(IdleState.EXEMPT),
            unknown=count(IdleState.UNKNOWN),
            monthly_waste_kwh=round(monthly, 2),
            errors=list(errors or []),
            records=records,
        )
