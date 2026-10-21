"""AWS inventory: EC2 instances and EBS volumes, returned as raw boto3 dicts.

Functions take an already-built client so they can be exercised with a stub. Mapping to
the Idleness Schema lives in ``normalize.py``.
"""

from __future__ import annotations

from typing import Any, Iterator

from app.providers.aws.client import get_ec2_client


def get_all_regions(ec2: Any | None = None) -> list[str]:
    ec2 = ec2 or get_ec2_client("us-east-1")
    resp = ec2.describe_regions(
        Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
    )
    return sorted(r["RegionName"] for r in resp["Regions"])


def iter_instances(ec2: Any) -> Iterator[dict[str, Any]]:
    """Yield raw EC2 instances (terminated/shutting-down excluded by the API filter)."""
    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(
        Filters=[
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            }
        ]
    )
    for page in pages:
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                yield inst


def iter_unattached_volumes(ec2: Any) -> Iterator[dict[str, Any]]:
    """Yield EBS volumes in the 'available' state (not attached to any instance)."""
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        yield from page["Volumes"]
