from app.providers.azure.client import get_compute_client


def get_instances() -> list[dict]:
    client = get_compute_client()
    instances = []

    for vm in client.virtual_machines.list_all():
        if vm.tags and vm.tags.get("greenops-ignore", "").lower() == "true":
            continue

        # Extract resource group from VM id
        # id format: /subscriptions/{sub}/resourceGroups/{rg}/providers/...
        parts = vm.id.split("/")
        resource_group = parts[4]
        location = vm.location

        instance_view = client.virtual_machines.instance_view(resource_group, vm.name)
        statuses = [s.code for s in (instance_view.statuses or [])]
        if "PowerState/running" not in statuses:
            continue

        vm_size = vm.hardware_profile.vm_size if vm.hardware_profile else "unknown"

        instances.append({
            "instance_id": vm.id,
            "name": vm.name,
            "instance_type": vm_size,
            "region": location,
            "resource_group": resource_group,
            "tags": vm.tags or {},
        })

    return instances
