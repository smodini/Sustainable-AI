from app.providers.gcp.instances import get_project_id, get_all_zones, get_instances
from app.providers.gcp.metrics import get_cpu_metrics, get_network_metrics
from app.services.idle_detector import is_vm_idle
from app.services.energy_calculator import calculate_energy_waste, MONTHLY_HOURS


def get_risk(idle_days: int) -> str:
    if idle_days < 2:
        return "LOW"
    if idle_days < 7:
        return "MEDIUM"
    if idle_days < 14:
        return "HIGH"
    return "CRITICAL"


def scan_gcp(observation_days: int = 7) -> dict:
    project_id = get_project_id()
    all_instances = []
    idle_resources = []
    total_waste_kwh = 0.0

    for zone in get_all_zones(project_id):
        for inst in get_instances(project_id, zone):
            cpu = get_cpu_metrics(inst["instance_id"], project_id, observation_days)
            net = get_network_metrics(inst["instance_id"], project_id, observation_days)

            idle = is_vm_idle(cpu_maximum=cpu["max"], network_mb_per_day=net)
            idle_hours = MONTHLY_HOURS if idle else 0.0
            energy_waste = calculate_energy_waste(idle_hours) if idle else 0.0
            total_waste_kwh += energy_waste

            resource = {
                "resource_id": inst["instance_id"],
                "name": inst["name"],
                "region": inst["region"],
                "instance_type": inst["instance_type"],
                "cpu_average": cpu["avg"],
                "cpu_maximum": cpu["max"],
                "network_mb_day": net,
                "idle": idle,
                "idle_hours": idle_hours,
                "energy_waste_kwh": energy_waste,
                "risk": get_risk(observation_days) if idle else "NONE",
            }

            all_instances.append(resource)
            if idle:
                idle_resources.append(resource)

    return {
        "provider": "GCP",
        "total_vms": len(all_instances),
        "idle_vms": len(idle_resources),
        "active_vms": len(all_instances) - len(idle_resources),
        "estimated_monthly_waste_kwh": round(total_waste_kwh, 2),
        "resources": all_instances,
    }
