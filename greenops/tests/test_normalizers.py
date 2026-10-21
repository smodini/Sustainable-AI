"""One idle condition per provider must land on the same schema vocabulary."""
import datetime as dt

from app.config import idle_policy
from app.models.idleness import IdleState, LifecycleState, Provider, ResourceKind
from app.providers.aws.normalize import normalize_ebs_volume, normalize_ec2_instance
from app.providers.azure.normalize import azure_telemetry, normalize_disk as az_disk, normalize_vm as az_vm
from app.providers.gcp.normalize import gcp_telemetry, normalize_disk as gcp_disk, normalize_instance as gcp_vm
from app.services.idle_detector import classify
from tests.conftest_helpers import NOW, WINDOW_END, WINDOW_START

SUB = "/subscriptions/11111111-2222-3333-4444-555555555555"


def test_unattached_storage_converges_across_providers():
    aws = normalize_ebs_volume(
        {"VolumeId": "vol-0abc", "State": "available", "Attachments": [], "Size": 100,
         "VolumeType": "gp3", "CreateTime": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
         "Tags": [{"Key": "Name", "Value": "old-data"}]},
        "123456789012", "us-east-1")
    azure = az_disk({
        "id": f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/OldData", "name": "OldData",
        "location": "eastus", "sku": {"name": "Premium_LRS"}, "tags": {"owner": "x"},
        "properties": {"diskState": "Unattached", "diskSizeGB": 128, "timeCreated": "2026-01-01T00:00:00+00:00"}})
    gcp = gcp_disk({
        "name": "old-data", "zone": "https://www.googleapis.com/compute/v1/projects/p/zones/us-central1-a",
        "status": "READY", "sizeGb": "200", "type": ".../diskTypes/pd-ssd",
        "creationTimestamp": "2026-01-01T00:00:00.000-07:00"}, "my-project")

    for ident, provider in ((aws, Provider.AWS), (azure, Provider.AZURE), (gcp, Provider.GCP)):
        assert ident.provider is provider
        assert ident.kind is ResourceKind.DISK
        assert ident.lifecycle is LifecycleState.UNATTACHED
        assert classify(ident, None, NOW).state is IdleState.ORPHANED
    assert (aws.provider_state, azure.provider_state, gcp.provider_state) == ("available", "Unattached", "READY")
    assert (aws.size_gb, azure.size_gb, gcp.size_gb) == (100.0, 128.0, 200.0)


def test_attached_storage_is_not_orphaned():
    assert normalize_ebs_volume({"VolumeId": "v", "State": "in-use", "Attachments": [{"InstanceId": "i-1"}]},
                                "1", "us-east-1").lifecycle is LifecycleState.ATTACHED
    for disk in (
        {"id": f"{SUB}/x/d", "name": "d", "location": "eastus", "managedBy": f"{SUB}/vm", "properties": {"diskState": "Attached"}},
        {"id": f"{SUB}/x/d", "name": "d", "location": "eastus", "properties": {"diskState": "Reserved"}},  # deallocated VM
    ):
        assert az_disk(disk).lifecycle is LifecycleState.ATTACHED
    assert gcp_disk({"name": "d", "zone": "z/us-east1-b", "status": "READY", "users": ["projects/p/zones/z/instances/i"]},
                    "p").lifecycle is LifecycleState.ATTACHED


def test_gcp_regional_disk_and_region_derivation():
    d = gcp_disk({"name": "rd", "region": "https://x/regions/europe-west1", "status": "READY"}, "p")
    assert d.region == "europe-west1" and "/regions/europe-west1/disks/rd" in d.resource_id
    assert gcp_vm({"name": "n", "zone": "https://x/zones/us-central1-a", "status": "RUNNING",
                   "machineType": ".../machineTypes/e2-medium"}, "p").region == "us-central1"


def test_vm_power_states_converge():
    aws = normalize_ec2_instance({"InstanceId": "i-1", "State": {"Name": "stopped"}, "InstanceType": "t3.small"}, "1", "us-east-1")
    azure = az_vm({"id": f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1", "name": "vm1",
                   "location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B2s"},
                   "extended": {"instanceView": {"powerState": {"code": "PowerState/deallocated"}}}}})
    gcp = gcp_vm({"name": "vm1", "zone": "z/us-central1-a", "status": "TERMINATED", "machineType": "m/e2-small"}, "p")
    for ident in (aws, azure, gcp):
        assert ident.lifecycle is LifecycleState.STOPPED
        assert classify(ident, None, NOW).state is IdleState.STOPPED


def test_azure_vm_expand_instance_view_form_and_subscription():
    vm = az_vm({"id": f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/VM1", "name": "VM1",
                "location": "westus2", "tags": {"hygiene-status": "exempt-from-hygiene"},
                "properties": {"instanceView": {"statuses": [{"code": "ProvisioningState/succeeded"}, {"code": "PowerState/running"}]}}})
    assert vm.lifecycle is LifecycleState.RUNNING
    assert vm.account_id == "11111111-2222-3333-4444-555555555555"
    assert classify(vm, None, NOW).state is IdleState.EXEMPT  # AWS-style tag key works on Azure tags


def test_gcp_cpu_fraction_is_converted_to_percent():
    t = gcp_telemetry(window_start=WINDOW_START, window_end=WINDOW_END, created_at=None,
                      cpu_utilization_mean_points=[0.02] * 168, cpu_utilization_max_points=[0.04] * 168,
                      received_bytes=[1000.0] * 168, sent_bytes=[1000.0] * 168)
    assert abs(t.cpu_maximum - 4.0) < 1e-9 and abs(t.cpu_average - 2.0) < 1e-9
    assert t.coverage == 1.0
    ident = gcp_vm({"name": "n", "zone": "z/us-central1-a", "status": "RUNNING"}, "p")
    assert classify(ident, t, NOW).state is IdleState.IDLE  # 4% < 5% threshold


def test_same_workload_same_verdict_on_all_three_clouds():
    n = 168
    az = azure_telemetry(window_start=WINDOW_START, window_end=WINDOW_END, created_at=None,
                         cpu_average_points=[1.0] * n, cpu_maximum_points=[3.0] * n,
                         network_in_total_bytes=[500.0] * n, network_out_total_bytes=[500.0] * n)
    gc = gcp_telemetry(window_start=WINDOW_START, window_end=WINDOW_END, created_at=None,
                       cpu_utilization_mean_points=[0.01] * n, cpu_utilization_max_points=[0.03] * n,
                       received_bytes=[500.0] * n, sent_bytes=[500.0] * n)
    assert abs(az.cpu_maximum - gc.cpu_maximum) < 1e-9
    assert abs(az.network_mb_per_day - gc.network_mb_per_day) < 1e-9


def test_missing_azure_network_metrics_yield_none_not_zero():
    t = azure_telemetry(window_start=WINDOW_START, window_end=WINDOW_END, created_at=None,
                        cpu_average_points=[1.0] * 168, cpu_maximum_points=[2.0] * 168,
                        network_in_total_bytes=[], network_out_total_bytes=[])
    assert t.network_mb_per_day is None
