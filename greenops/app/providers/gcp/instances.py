import os
from google.cloud import compute_v1
from app.providers.gcp.client import get_compute_client, get_zones_client


def get_project_id() -> str:
    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise ValueError("GCP_PROJECT_ID environment variable is not set")
    return project


def get_all_zones(project_id: str) -> list[str]:
    client = get_zones_client()
    return [z.name for z in client.list(project=project_id)]


def get_instances(project_id: str, zone: str) -> list[dict]:
    client = get_compute_client()
    instances = []

    for inst in client.list(project=project_id, zone=zone):
        if inst.status != "RUNNING":
            continue

        labels = dict(inst.labels) if inst.labels else {}
        if labels.get("greenops-ignore", "").lower() == "true":
            continue

        machine_type = inst.machine_type.split("/")[-1]
        instances.append({
            "instance_id": str(inst.id),
            "name": inst.name,
            "instance_type": machine_type,
            "zone": zone,
            "region": zone.rsplit("-", 1)[0],
            "labels": labels,
        })

    return instances
