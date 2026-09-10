import boto3
from app.providers.aws.client import get_ec2_client


def get_all_regions() -> list[str]:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    response = ec2.describe_regions(Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])
    return [r["RegionName"] for r in response["Regions"]]


def get_instances(region: str) -> list[dict]:
    ec2 = get_ec2_client(region)
    instances = []
    paginator = ec2.get_paginator("describe_instances")

    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                instances.append({
                    "instance_id": inst["InstanceId"],
                    "name": tags.get("Name", inst["InstanceId"]),
                    "instance_type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "region": region,
                    "tags": tags,
                })

    return instances
