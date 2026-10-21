"""Shared builders for tests (not a conftest, so it also works under a minimal runner)."""
import datetime as dt

from app.models.idleness import (
    LifecycleState,
    Provider,
    ResourceIdentity,
    ResourceKind,
    Telemetry,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
WINDOW_END = dt.datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
WINDOW_START = WINDOW_END - dt.timedelta(days=7)
OLD = dt.datetime(2026, 1, 1, tzinfo=UTC)


def vm(lifecycle=LifecycleState.RUNNING, tags=None, created_at=OLD, state="running", provider=Provider.AWS):
    return ResourceIdentity(
        provider=provider, account_id="123456789012", resource_id="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        kind=ResourceKind.VM, name="web", region="us-east-1", resource_type="t3.medium",
        provider_state=state, lifecycle=lifecycle, created_at=created_at, tags=tags or {},
    )


def disk(lifecycle=LifecycleState.UNATTACHED, tags=None, state="available", provider=Provider.AWS):
    return ResourceIdentity(
        provider=provider, account_id="123456789012", resource_id="arn:aws:ec2:us-east-1:123456789012:volume/vol-1",
        kind=ResourceKind.DISK, name="vol", region="us-east-1", resource_type="gp3",
        provider_state=state, lifecycle=lifecycle, created_at=OLD, size_gb=100.0, tags=tags or {},
    )


def tel(cpu_max=1.0, cpu_avg=0.5, net=1.0, coverage=1.0):
    return Telemetry(
        window_start=WINDOW_START, window_end=WINDOW_END,
        cpu_average=cpu_avg, cpu_maximum=cpu_max, network_mb_per_day=net, coverage=coverage,
    )
