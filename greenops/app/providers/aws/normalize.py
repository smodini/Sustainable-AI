"""AWS-native EC2/EBS shapes -> Idleness Schema ResourceIdentity (pure functions)."""

from __future__ import annotations

from typing import Any

from app.models.idleness import LifecycleState, Provider, ResourceIdentity, ResourceKind

_EC2_LIFECYCLE = {
    "running": LifecycleState.RUNNING,
    "stopped": LifecycleState.STOPPED,
}

_EBS_LIFECYCLE = {
    "available": LifecycleState.UNATTACHED,  # the AWS idle-storage condition
    "in-use": LifecycleState.ATTACHED,
}


def aws_tags(raw_tags: list[dict[str, str]] | None) -> dict[str, str]:
    return {t["Key"]: t.get("Value", "") for t in (raw_tags or [])}


def normalize_ec2_instance(raw: dict[str, Any], account_id: str, region: str) -> ResourceIdentity:
    tags = aws_tags(raw.get("Tags"))
    state = raw["State"]["Name"]
    return ResourceIdentity(
        provider=Provider.AWS,
        account_id=account_id,
        resource_id=f"arn:aws:ec2:{region}:{account_id}:instance/{raw['InstanceId']}",
        kind=ResourceKind.VM,
        name=tags.get("Name", raw["InstanceId"]),
        region=region,
        resource_type=raw.get("InstanceType"),
        provider_state=state,
        lifecycle=_EC2_LIFECYCLE.get(state, LifecycleState.OTHER),
        created_at=raw.get("LaunchTime"),
        tags=tags,
    )


def normalize_ebs_volume(raw: dict[str, Any], account_id: str, region: str) -> ResourceIdentity:
    tags = aws_tags(raw.get("Tags"))
    state = raw["State"]
    attached = bool(raw.get("Attachments"))
    lifecycle = (
        LifecycleState.ATTACHED
        if attached
        else _EBS_LIFECYCLE.get(state, LifecycleState.OTHER)
    )
    return ResourceIdentity(
        provider=Provider.AWS,
        account_id=account_id,
        resource_id=f"arn:aws:ec2:{region}:{account_id}:volume/{raw['VolumeId']}",
        kind=ResourceKind.DISK,
        name=tags.get("Name", raw["VolumeId"]),
        region=region,
        resource_type=raw.get("VolumeType"),
        provider_state=state,
        lifecycle=lifecycle,
        created_at=raw.get("CreateTime"),
        size_gb=float(raw["Size"]) if "Size" in raw else None,
        tags=tags,
    )


def instance_id_from_resource_id(resource_id: str) -> str:
    return resource_id.rsplit("/", 1)[-1]
