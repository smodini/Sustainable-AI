"""
Article 4: Unified Multi-Cloud Resource Scavenger
==================================================
A Python framework for Automated Resource Hygiene and Carbon Attribution.

Implements the "Sensing & Notifying Loop" for cross-cloud zombie resource
detection, E_waste carbon attribution, and graduated escalation notifications.

Supports: GCP, AWS, Azure

Note: This is the high-level architectural implementation accompanying Article 4.
      Article 5 will provide production-grade code with Kubernetes integration,
      real-time orchestration, and Anthos-based workload migration.

Authors: Sai Kalyan Kumar Modini, Sai Kiran Chary Kannyakanti
Date: March 2026
"""

import abc
import datetime
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict


# ===========================================================================
# SECTION 1: Data Models
# ===========================================================================

class CloudProvider(Enum):
    GCP = "gcp"
    AWS = "aws"
    AZURE = "azure"


class ResourceType(Enum):
    VIRTUAL_MACHINE = "vm"
    DISK = "disk"
    SNAPSHOT = "snapshot"
    GPU_INSTANCE = "gpu"


class StalenessVerdict(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ZOMBIE = "zombie"
    EXEMPT = "exempt"       # Tagged as DR/standby — excluded from hygiene


@dataclass
class TelemetryWindow:
    """Rolling telemetry metrics over the observation period."""
    avg_cpu_percent: float
    max_cpu_percent: float
    cpu_below_threshold_ratio: float    # Fraction of time CPU was below 1%
    total_network_bytes_7d: float
    total_disk_io_bytes_7d: float
    avg_gpu_utilization: Optional[float] = None   # For GPU-attached instances
    avg_memory_percent: Optional[float] = None
    observation_days: int = 14


@dataclass
class CloudResource:
    """Unified representation of a cloud resource across any provider."""
    resource_id: str
    resource_type: ResourceType
    provider: CloudProvider
    region: str
    instance_type: str
    owner_email: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    created_at: Optional[datetime.datetime] = None
    telemetry: Optional[TelemetryWindow] = None
    estimated_idle_power_kw: float = 0.0    # P_idle in kilowatts
    verdict: StalenessVerdict = StalenessVerdict.ACTIVE
    e_waste_kg_co2: float = 0.0


# ===========================================================================
# SECTION 2: Zombie Detection Thresholds (Article 4, Section 4.1)
# ===========================================================================

@dataclass
class ZombieThresholds:
    """Configurable thresholds for zombie resource identification."""
    cpu_avg_max_percent: float = 1.0
    cpu_below_threshold_ratio: float = 0.95
    network_max_bytes_7d: float = 5 * 1024 * 1024   # 5 MB
    gpu_avg_max_percent: float = 2.0                 # GPU idle cutoff
    memory_avg_max_percent: float = 5.0              # Memory idle cutoff
    observation_window_days: int = 14
    exempt_tags: List[str] = field(default_factory=lambda: [
        "disaster-recovery", "warm-standby", "exempt-from-hygiene"
    ])


# ===========================================================================
# SECTION 3: Abstract Cloud Resource Adapter
# ===========================================================================

class CloudResourceAdapter(abc.ABC):
    """
    Abstract base class for cloud-specific resource discovery.
    Each provider (GCP, AWS, Azure) implements this interface.
    """

    @abc.abstractmethod
    def authenticate(self) -> None:
        """Establish authenticated session using service account / IAM role."""
        ...

    @abc.abstractmethod
    def discover_via_recommender(self, project_or_account: str) -> List[CloudResource]:
        """
        Primary path: query cloud-native idle resource recommender APIs.
        GCP Recommender / AWS Compute Optimizer / Azure Advisor continuously
        analyse resource usage — consume their output rather than re-polling.
        Returns pre-validated zombie resources with telemetry already populated.
        """
        ...

    @abc.abstractmethod
    def discover_via_polling(self, project_or_account: str) -> List[CloudResource]:
        """
        Fallback path: manual asset inventory scan used when recommender APIs
        are unavailable (insufficient permissions, new account, free tier).
        Requires a subsequent fetch_telemetry() call per resource.
        """
        ...

    @abc.abstractmethod
    def fetch_telemetry(self, resource: CloudResource) -> TelemetryWindow:
        """Retrieve CPU, Network, Disk, GPU metrics for the observation window."""
        ...

    @abc.abstractmethod
    def get_carbon_intensity(self, region: str) -> float:
        """Return grid carbon intensity in gCO2eq/kWh for the given region."""
        ...


# ===========================================================================
# SECTION 3a: GCP Adapter
# ===========================================================================

class GCPResourceAdapter(CloudResourceAdapter):
    """
    GCP implementation using:
      - google-cloud-recommender (Primary: Idle VM Recommender API)
      - google-cloud-asset for Cloud Asset Inventory (Fallback)
      - google-cloud-monitoring for telemetry metrics (Fallback)
      - Cloud Carbon Footprint API / BigQuery export for carbon intensity
    """

    def authenticate(self) -> None:
        from google.cloud import asset_v1
        from google.cloud import monitoring_v3
        self.asset_client = asset_v1.AssetServiceClient()
        self.monitoring_client = monitoring_v3.MetricServiceClient()

    def discover_via_recommender(self, project_id: str) -> List[CloudResource]:
        """
        Query GCP Idle VM Recommender per zone.
        In production, enumerate zones dynamically via the Compute API;
        here we use a configurable scan_zones list for illustration.
        """
        from google.cloud import recommender_v1

        rec_client = recommender_v1.RecommenderClient()
        resources = []
        zones = getattr(self, "scan_zones", [
            "us-central1-a", "us-east1-b", "europe-west1-b"
        ])

        for zone in zones:
            parent = (
                f"projects/{project_id}/locations/{zone}/recommenders/"
                "google.compute.instance.IdleResourceRecommender"
            )
            try:
                for rec in rec_client.list_recommendations(parent=parent):
                    from google.cloud.recommender_v1 import RecommendationStateInfo
                    if rec.state_info.state != RecommendationStateInfo.State.ACTIVE:
                        continue
                    overview = rec.content.overview
                    res = CloudResource(
                        resource_id=overview.get("resourceName", rec.name),
                        resource_type=ResourceType.VIRTUAL_MACHINE,
                        provider=CloudProvider.GCP,
                        region=zone.rsplit("-", 1)[0],
                        instance_type=overview.get("machineType", "unknown"),
                        tags={},
                        estimated_idle_power_kw=0.07,
                        verdict=StalenessVerdict.ZOMBIE,
                    )
                    res.telemetry = TelemetryWindow(
                        avg_cpu_percent=float(overview.get("avgCpuUsage", 0.0)),
                        max_cpu_percent=0.0,
                        cpu_below_threshold_ratio=0.99,
                        total_network_bytes_7d=0.0,
                        total_disk_io_bytes_7d=0.0,
                        observation_days=int(
                            overview.get("observationPeriodInDays", 14)
                        ),
                    )
                    resources.append(res)
            except Exception:
                continue     # Zone may not have recommender data

        return resources

    def discover_via_polling(self, project_id: str) -> List[CloudResource]:
        from google.cloud import asset_v1

        request = asset_v1.ListAssetsRequest(
            parent=f"projects/{project_id}",
            asset_types=[
                "compute.googleapis.com/Instance",
                "compute.googleapis.com/Disk",
            ],
        )
        resources = []
        for asset in self.asset_client.list_assets(request=request):
            res = CloudResource(
                resource_id=asset.name,
                resource_type=self._map_asset_type(asset.asset_type),
                provider=CloudProvider.GCP,
                region=self._extract_zone(asset),
                instance_type=self._extract_machine_type(asset),
                owner_email=self._extract_owner_label(asset),
                tags=dict(asset.resource.data.get("labels", {})),
                estimated_idle_power_kw=self._estimate_idle_power(asset),
            )
            resources.append(res)
        return resources

    def fetch_telemetry(self, resource: CloudResource) -> TelemetryWindow:
        from google.cloud import monitoring_v3
        from google.protobuf.timestamp_pb2 import Timestamp
        import time

        now = time.time()
        window_seconds = 14 * 86400
        interval = monitoring_v3.TimeInterval(
            end_time=Timestamp(seconds=int(now)),
            start_time=Timestamp(seconds=int(now - window_seconds)),
        )

        # Query CPU utilization
        cpu_filter = (
            'metric.type = "compute.googleapis.com/instance/cpu/utilization" '
            f'AND resource.labels.instance_id = "{resource.resource_id}"'
        )
        cpu_request = monitoring_v3.ListTimeSeriesRequest(
            name=f"projects/{self._extract_project(resource)}",
            filter=cpu_filter,
            interval=interval,
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        )
        cpu_series = self.monitoring_client.list_time_series(request=cpu_request)
        cpu_values = [
            point.value.double_value * 100
            for ts in cpu_series for point in ts.points
        ]

        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0.0
        below_thr = (
            sum(1 for v in cpu_values if v < 1.0) / len(cpu_values)
            if cpu_values else 0.0
        )

        return TelemetryWindow(
            avg_cpu_percent=avg_cpu,
            max_cpu_percent=max(cpu_values, default=0.0),
            cpu_below_threshold_ratio=below_thr,
            total_network_bytes_7d=0.0,   # Extend with network metric query
            total_disk_io_bytes_7d=0.0,   # Extend with disk I/O metric query
        )

    def get_carbon_intensity(self, region: str) -> float:
        """
        Reference grid intensities from GCP Carbon Footprint API (gCO2eq/kWh).
        In production: query BigQuery carbon footprint export table.
        """
        gcp_carbon_map = {
            "us-central1": 420, "us-east1": 380, "us-west1": 90,
            "europe-west1": 200, "europe-north1": 130,
            "asia-south1": 700, "asia-northeast1": 500,
        }
        return gcp_carbon_map.get(region, 450)

    # -- Internal helpers --

    def _map_asset_type(self, asset_type: str) -> ResourceType:
        if "Disk" in asset_type:
            return ResourceType.DISK
        return ResourceType.VIRTUAL_MACHINE

    def _extract_zone(self, asset) -> str:
        return asset.resource.data.get("zone", "unknown").rsplit("/", 1)[-1]

    def _extract_machine_type(self, asset) -> str:
        return asset.resource.data.get("machineType", "unknown").rsplit("/", 1)[-1]

    def _extract_owner_label(self, asset) -> Optional[str]:
        return asset.resource.data.get("labels", {}).get("owner")

    def _estimate_idle_power(self, asset) -> float:
        machine = self._extract_machine_type(asset)
        if any(g in machine for g in ("a2", "g2", "a3")):
            return 0.35     # GPU instances idle higher
        if any(s in machine for s in ("n2", "e2", "n1")):
            return 0.07
        return 0.10

    def _extract_project(self, resource: CloudResource) -> str:
        parts = resource.resource_id.split("/")
        return parts[1] if len(parts) > 1 else "unknown"


# ===========================================================================
# SECTION 3b: AWS Adapter
# ===========================================================================

class AWSResourceAdapter(CloudResourceAdapter):
    """
    AWS implementation using:
      - boto3 compute-optimizer (Primary: idle EC2 instance findings)
      - boto3 EC2 for resource discovery (Fallback)
      - boto3 CloudWatch for telemetry (Fallback)
      - EPA eGRID / electricityMap data for carbon intensity
    """

    def authenticate(self) -> None:
        import boto3
        self.ec2_client = boto3.client("ec2")
        self.cloudwatch = boto3.client("cloudwatch")

    def discover_via_recommender(self, account_id: str) -> List[CloudResource]:
        """
        Query AWS Compute Optimizer for idle EC2 instance findings.
        Returns resources pre-tagged with CPU utilization metadata.
        """
        import boto3
        optimizer = boto3.client("compute-optimizer")
        resources = []

        try:
            paginator = optimizer.get_paginator(
                "get_ec2_instance_recommendations"
            )
            for page in paginator.paginate(
                filters=[{
                    "name": "Finding",
                    "values": ["NotOptimized", "Overprovisioned"],
                }]
            ):
                for rec in page.get("instanceRecommendations", []):
                    instance_id = rec["instanceArn"].split("/")[-1]
                    region = rec["instanceArn"].split(":")[3]
                    tags_resp = self.ec2_client.describe_tags(
                        Filters=[{"Name": "resource-id", "Values": [instance_id]}]
                    )
                    tags = {
                        t["Key"]: t["Value"]
                        for t in tags_resp.get("Tags", [])
                    }
                    cpu_vals = [
                        m["value"]
                        for m in rec.get("utilizationMetrics", [])
                        if m["name"] == "CPU" and m["statistic"] == "AVERAGE"
                    ]
                    avg_cpu = cpu_vals[0] if cpu_vals else 0.0
                    instance_type = rec.get("currentInstanceType", "unknown")
                    res = CloudResource(
                        resource_id=instance_id,
                        resource_type=ResourceType.VIRTUAL_MACHINE,
                        provider=CloudProvider.AWS,
                        region=region,
                        instance_type=instance_type,
                        owner_email=tags.get("Owner"),
                        tags=tags,
                        estimated_idle_power_kw=self._estimate_idle_power(
                            instance_type
                        ),
                        verdict=StalenessVerdict.ZOMBIE,
                    )
                    res.telemetry = TelemetryWindow(
                        avg_cpu_percent=avg_cpu,
                        max_cpu_percent=0.0,
                        cpu_below_threshold_ratio=0.99,
                        total_network_bytes_7d=0.0,
                        total_disk_io_bytes_7d=0.0,
                        observation_days=14,
                    )
                    resources.append(res)
        except Exception as e:
            logging.getLogger("scavenger").warning(
                f"AWS Compute Optimizer unavailable: {e}"
            )

        return resources

    def discover_via_polling(self, account_id: str) -> List[CloudResource]:
        import boto3
        ec2 = boto3.resource("ec2")
        resources = []

        # Discover EC2 instances
        for instance in ec2.instances.all():
            tags = {t["Key"]: t["Value"] for t in (instance.tags or [])}
            res = CloudResource(
                resource_id=instance.id,
                resource_type=ResourceType.VIRTUAL_MACHINE,
                provider=CloudProvider.AWS,
                region=instance.placement.get("AvailabilityZone", "unknown")[:-1],
                instance_type=instance.instance_type,
                owner_email=tags.get("Owner"),
                tags=tags,
                created_at=instance.launch_time,
                estimated_idle_power_kw=self._estimate_idle_power(instance.instance_type),
            )
            resources.append(res)

        # Discover unattached EBS volumes (orphaned disks)
        for volume in ec2.volumes.filter(
            Filters=[{"Name": "status", "Values": ["available"]}]
        ):
            tags = {t["Key"]: t["Value"] for t in (volume.tags or [])}
            res = CloudResource(
                resource_id=volume.id,
                resource_type=ResourceType.DISK,
                provider=CloudProvider.AWS,
                region=volume.availability_zone[:-1],
                instance_type=volume.volume_type,
                tags=tags,
                estimated_idle_power_kw=0.005,
            )
            resources.append(res)

        return resources

    def fetch_telemetry(self, resource: CloudResource) -> TelemetryWindow:
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(days=14)

        response = self.cloudwatch.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": resource.resource_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,            # 1-hour granularity
            Statistics=["Average", "Maximum"],
        )

        datapoints = response.get("Datapoints", [])
        avg_values = [dp["Average"] for dp in datapoints]
        avg_cpu = sum(avg_values) / len(avg_values) if avg_values else 0.0
        below_thr = (
            sum(1 for v in avg_values if v < 1.0) / len(avg_values)
            if avg_values else 0.0
        )

        return TelemetryWindow(
            avg_cpu_percent=avg_cpu,
            max_cpu_percent=max(
                (dp["Maximum"] for dp in datapoints), default=0.0
            ),
            cpu_below_threshold_ratio=below_thr,
            total_network_bytes_7d=0.0,   # Extend: NetworkIn + NetworkOut
            total_disk_io_bytes_7d=0.0,   # Extend: DiskReadBytes + DiskWriteBytes
        )

    def get_carbon_intensity(self, region: str) -> float:
        """AWS has no native carbon API; use EPA eGRID / electricityMap data."""
        aws_carbon_map = {
            "us-east-1": 380, "us-west-2": 100,
            "eu-west-1": 300, "eu-north-1": 50,
            "ap-south-1": 700, "ap-northeast-1": 500,
        }
        return aws_carbon_map.get(region, 450)

    def _estimate_idle_power(self, instance_type: str) -> float:
        family = instance_type.split(".")[0] if "." in instance_type else instance_type
        if family.startswith(("p", "g", "dl", "trn", "inf")):
            return 0.35     # GPU / ML accelerator instances
        if family.startswith("t"):
            return 0.005    # Burstable
        if family.startswith(("m", "c", "r")):
            return 0.07
        return 0.10


# ===========================================================================
# SECTION 3c: Azure Adapter
# ===========================================================================

class AzureResourceAdapter(CloudResourceAdapter):
    """
    Azure implementation using:
      - azure-mgmt-advisor (Primary: Cost Recommendations for idle VMs)
      - azure-identity (DefaultAzureCredential)
      - azure-mgmt-compute for VM and Disk discovery (Fallback)
      - azure-mgmt-monitor for telemetry (Fallback)
      - Azure Emissions Impact Dashboard for carbon data
    """

    def authenticate(self) -> None:
        import os
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.compute import ComputeManagementClient
        from azure.mgmt.monitor import MonitorManagementClient

        self.credential = DefaultAzureCredential()
        self.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
        self.compute_client = ComputeManagementClient(
            self.credential, self.subscription_id
        )
        self.monitor_client = MonitorManagementClient(
            self.credential, self.subscription_id
        )

    def discover_via_recommender(self, subscription_id: str) -> List[CloudResource]:
        """
        Query Azure Advisor Cost recommendations for idle virtual machines.
        """
        from azure.mgmt.advisor import AdvisorManagementClient

        advisor = AdvisorManagementClient(self.credential, subscription_id)
        resources = []

        try:
            for rec in advisor.recommendations.list():
                if rec.category != "Cost":
                    continue
                problem = (
                    rec.short_description.problem
                    if rec.short_description else ""
                ) or ""
                if "virtual machine" not in problem.lower():
                    continue
                resource_id = (
                    rec.resource_metadata.resource_id
                    if rec.resource_metadata else ""
                )
                region = (
                    rec.resource_metadata.region
                    if rec.resource_metadata else "eastus"
                ) or "eastus"
                vm_size = (rec.extended_properties or {}).get("VMSize", "unknown")
                res = CloudResource(
                    resource_id=resource_id,
                    resource_type=ResourceType.VIRTUAL_MACHINE,
                    provider=CloudProvider.AZURE,
                    region=region,
                    instance_type=vm_size,
                    tags={},
                    estimated_idle_power_kw=self._estimate_idle_power(vm_size),
                    verdict=StalenessVerdict.ZOMBIE,
                )
                res.telemetry = TelemetryWindow(
                    avg_cpu_percent=0.0,
                    max_cpu_percent=0.0,
                    cpu_below_threshold_ratio=0.99,
                    total_network_bytes_7d=0.0,
                    total_disk_io_bytes_7d=0.0,
                    observation_days=14,
                )
                resources.append(res)
        except Exception as e:
            logging.getLogger("scavenger").warning(
                f"Azure Advisor unavailable: {e}"
            )

        return resources

    def discover_via_polling(self, subscription_id: str) -> List[CloudResource]:
        resources = []

        # Discover virtual machines
        for vm in self.compute_client.virtual_machines.list_all():
            tags = vm.tags or {}
            res = CloudResource(
                resource_id=vm.id,
                resource_type=ResourceType.VIRTUAL_MACHINE,
                provider=CloudProvider.AZURE,
                region=vm.location,
                instance_type=vm.hardware_profile.vm_size,
                owner_email=tags.get("Owner"),
                tags=tags,
                estimated_idle_power_kw=self._estimate_idle_power(
                    vm.hardware_profile.vm_size
                ),
            )
            resources.append(res)

        # Discover unattached managed disks
        for disk in self.compute_client.disks.list():
            if disk.disk_state == "Unattached":
                res = CloudResource(
                    resource_id=disk.id,
                    resource_type=ResourceType.DISK,
                    provider=CloudProvider.AZURE,
                    region=disk.location,
                    instance_type=disk.sku.name,
                    tags=disk.tags or {},
                    estimated_idle_power_kw=0.005,
                )
                resources.append(res)

        return resources

    def fetch_telemetry(self, resource: CloudResource) -> TelemetryWindow:
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(days=14)
        timespan = f"{start_time.isoformat()}/{end_time.isoformat()}"

        metrics = self.monitor_client.metrics.list(
            resource_uri=resource.resource_id,
            timespan=timespan,
            interval="PT1H",
            metricnames="Percentage CPU",
            aggregation="Average,Maximum",
        )

        cpu_values = []
        for metric in metrics.value:
            for ts in metric.timeseries:
                for data in ts.data:
                    if data.average is not None:
                        cpu_values.append(data.average)

        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0.0
        below_thr = (
            sum(1 for v in cpu_values if v < 1.0) / len(cpu_values)
            if cpu_values else 0.0
        )

        return TelemetryWindow(
            avg_cpu_percent=avg_cpu,
            max_cpu_percent=max(cpu_values, default=0.0),
            cpu_below_threshold_ratio=below_thr,
            total_network_bytes_7d=0.0,
            total_disk_io_bytes_7d=0.0,
        )

    def get_carbon_intensity(self, region: str) -> float:
        """Azure Emissions Impact Dashboard / Sustainability Calculator."""
        azure_carbon_map = {
            "eastus": 380, "westus2": 100,
            "northeurope": 200, "westeurope": 300,
            "southeastasia": 500, "centralindia": 700,
        }
        return azure_carbon_map.get(region, 450)

    def _estimate_idle_power(self, vm_size: str) -> float:
        size = vm_size.lower()
        if any(g in size for g in ("nc", "nd", "nv")):
            return 0.35     # GPU series
        if "b" == size[len("standard_"):len("standard_") + 1] if size.startswith("standard_") else False:
            return 0.005    # Burstable B-series
        return 0.08


# ===========================================================================
# SECTION 4: E_waste Carbon Attribution Calculator
# ===========================================================================

class EwasteCalculator:
    """
    Implements the E_waste formula from Article 2 & 3:

        E_waste = P_idle  x  T_stale  x  CI(region)  x  PUE

    Where:
        P_idle   = Idle power draw of the resource (kW)
        T_stale  = Duration the resource has been stale (hours)
        CI       = Regional grid carbon intensity (gCO2eq/kWh)
        PUE      = Power Usage Effectiveness of the data center

    Returns: Estimated carbon waste in kg CO2e
    """

    DEFAULT_PUE = 1.1   # Hyperscaler average PUE (Google: 1.10, AWS: ~1.135)

    def calculate(
        self,
        resource: CloudResource,
        adapter: CloudResourceAdapter,
        stale_hours: float,
    ) -> float:
        p_idle = resource.estimated_idle_power_kw       # kW
        ci = adapter.get_carbon_intensity(resource.region)  # gCO2eq/kWh
        pue = self.DEFAULT_PUE

        # E_waste in grams CO2eq, then convert to kilograms
        e_waste_g = p_idle * stale_hours * ci * pue
        e_waste_kg = e_waste_g / 1000.0

        resource.e_waste_kg_co2 = e_waste_kg
        return e_waste_kg

    @staticmethod
    def humanize_carbon(kg_co2: float) -> str:
        """Convert kg CO2 to relatable real-world analogies."""
        homes_powered = kg_co2 / 9.5   # ~9.5 kg CO2/month per US home base load
        tree_months = kg_co2 / 1.8     # ~1.8 kg CO2 absorbed per tree per month
        return (
            f"{kg_co2:.1f} kg CO2e/month "
            f"(equivalent to powering {homes_powered:.1f} U.S. homes, "
            f"or requiring {tree_months:.0f} tree-months to offset)"
        )


# ===========================================================================
# SECTION 5: Zombie Classification Engine
# ===========================================================================

class ZombieClassifier:
    """
    Multi-signal classification: CPU + Network + GPU + Tag exemptions.
    Composite scoring prevents false positives from single-metric anomalies.
    """

    def __init__(self, thresholds: Optional[ZombieThresholds] = None):
        self.thresholds = thresholds or ZombieThresholds()

    def classify(self, resource: CloudResource) -> StalenessVerdict:
        # Check for tag-based exemption (DR, standby, etc.)
        for tag_value in resource.tags.values():
            if tag_value.lower() in self.thresholds.exempt_tags:
                resource.verdict = StalenessVerdict.EXEMPT
                return StalenessVerdict.EXEMPT

        telemetry = resource.telemetry
        if telemetry is None:
            return StalenessVerdict.ACTIVE   # Cannot classify without data

        # Orphaned disks / snapshots are always zombies
        if resource.resource_type in (ResourceType.DISK, ResourceType.SNAPSHOT):
            resource.verdict = StalenessVerdict.ZOMBIE
            return StalenessVerdict.ZOMBIE

        # Signal 1: CPU
        cpu_zombie = (
            telemetry.avg_cpu_percent < self.thresholds.cpu_avg_max_percent
            and telemetry.cpu_below_threshold_ratio >= self.thresholds.cpu_below_threshold_ratio
        )

        # Signal 2: Network
        net_zombie = (
            telemetry.total_network_bytes_7d < self.thresholds.network_max_bytes_7d
        )

        # Signal 3: GPU (if applicable)
        gpu_zombie = True
        if telemetry.avg_gpu_utilization is not None:
            gpu_zombie = (
                telemetry.avg_gpu_utilization < self.thresholds.gpu_avg_max_percent
            )

        # Signal 4: Memory (if applicable) — guards against cache/DB workloads
        mem_zombie = True
        if telemetry.avg_memory_percent is not None:
            mem_zombie = (
                telemetry.avg_memory_percent < self.thresholds.memory_avg_max_percent
            )

        # Composite verdict
        if cpu_zombie and net_zombie and gpu_zombie and mem_zombie:
            resource.verdict = StalenessVerdict.ZOMBIE
        elif cpu_zombie or net_zombie:
            resource.verdict = StalenessVerdict.IDLE
        else:
            resource.verdict = StalenessVerdict.ACTIVE

        return resource.verdict


# ===========================================================================
# SECTION 6: Graduated Notification Engine ("Social FinOps")
# ===========================================================================

class NotificationEngine:
    """
    Graduated escalation model (replaces aggressive auto-deletion):

        Day 0  -> NOTICE:   Informational alert to resource owner
        Day 3  -> WARNING:  Resource will be stopped soon
        Day 7  -> ACTION:   Resource stopped; snapshot preserved 7 days
        Day 14 -> FINAL:    Resource + snapshot will be deleted
    """

    ESCALATION_LEVELS = {
        0:  ("NOTICE",  "Resource identified as potentially stale"),
        3:  ("WARNING", "Resource will be STOPPED in 4 days if no action taken"),
        7:  ("ACTION",  "Resource STOPPED. Snapshot preserved for 7 days"),
        14: ("FINAL",   "Resource and snapshot will be DELETED in 48 hours"),
    }

    def build_payload(self, resource: CloudResource, days_stale: int) -> dict:
        level, message = self._get_escalation_level(days_stale)

        payload = {
            "notification_type": "RESOURCE_HYGIENE_ALERT",
            "severity": level,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "resource": {
                "id": resource.resource_id,
                "type": resource.resource_type.value,
                "provider": resource.provider.value,
                "region": resource.region,
                "instance_type": resource.instance_type,
                "owner": resource.owner_email or "untagged-owner@company.com",
            },
            "telemetry_summary": {
                "avg_cpu_percent": (
                    round(resource.telemetry.avg_cpu_percent, 2)
                    if resource.telemetry else None
                ),
                "total_network_7d_bytes": (
                    resource.telemetry.total_network_bytes_7d
                    if resource.telemetry else None
                ),
                "observation_days": (
                    resource.telemetry.observation_days
                    if resource.telemetry else None
                ),
            },
            "carbon_impact": {
                "e_waste_kg_co2_per_month": round(resource.e_waste_kg_co2, 2),
                "human_readable": EwasteCalculator.humanize_carbon(
                    resource.e_waste_kg_co2
                ),
            },
            "action": {
                "level": level,
                "message": message,
                "days_until_next_escalation": self._days_to_next(days_stale),
                "override_instructions": (
                    "To exempt this resource, apply the tag "
                    "'hygiene-status: exempt-from-hygiene' or respond "
                    "to this ticket within the escalation window."
                ),
            },
        }
        return payload

    def _get_escalation_level(self, days_stale: int) -> tuple:
        applicable = [
            (d, level, msg)
            for d, (level, msg) in self.ESCALATION_LEVELS.items()
            if days_stale >= d
        ]
        _, level, msg = max(applicable, key=lambda x: x[0])
        return level, msg

    def _days_to_next(self, days_stale: int) -> Optional[int]:
        for threshold in sorted(self.ESCALATION_LEVELS.keys()):
            if threshold > days_stale:
                return threshold - days_stale
        return None


# ===========================================================================
# SECTION 7: Main Orchestrator — The Scavenger
# ===========================================================================

class MultiCloudScavenger:
    """
    Top-level orchestrator implementing the Recommender-First architecture.

    Primary path  — Cloud-native recommenders supply pre-validated idle signals.
                    No manual metric polling; no redundant classification work.
    Fallback path — Manual telemetry polling + ZombieClassifier for accounts
                    where recommender APIs are not yet available.
    Shared stages — E_waste attribution and graduated notification run
                    identically regardless of which detection path was used.
    """

    def __init__(self):
        self.adapters: Dict[CloudProvider, CloudResourceAdapter] = {}
        self.classifier = ZombieClassifier()
        self.calculator = EwasteCalculator()
        self.notifier = NotificationEngine()
        self.logger = logging.getLogger("scavenger")

    def register_cloud(
        self, provider: CloudProvider, adapter: CloudResourceAdapter
    ):
        adapter.authenticate()
        self.adapters[provider] = adapter

    def scan(self, targets: Dict[CloudProvider, str]) -> List[dict]:
        """
        Execute the Recommender-First Sensing & Notifying Loop.

        Primary path:  Cloud-native recommenders → E_waste attribution → Notify
        Fallback path: Manual telemetry polling → Classify → E_waste → Notify

        Args:
            targets: {CloudProvider: project_id / account_id / subscription_id}

        Returns:
            List of notification payloads for zombie/idle resources.
        """
        all_notifications = []

        for provider, account_id in targets.items():
            adapter = self.adapters.get(provider)
            if not adapter:
                self.logger.warning(f"No adapter registered for {provider.value}")
                continue

            self.logger.info(f"Scanning {provider.value} / {account_id} ...")

            # ── Primary path: cloud-native recommender APIs ───────────────────
            resources = adapter.discover_via_recommender(account_id)
            self.logger.info(
                f"  Recommender path: {len(resources)} idle resources found"
            )

            # ── Fallback path: manual telemetry polling ───────────────────────
            if not resources:
                self.logger.info(
                    "  Recommender returned 0 — falling back to telemetry polling"
                )
                polled = adapter.discover_via_polling(account_id)
                for resource in polled:
                    if resource.resource_type == ResourceType.VIRTUAL_MACHINE:
                        resource.telemetry = adapter.fetch_telemetry(resource)
                    verdict = self.classifier.classify(resource)
                    if verdict in (StalenessVerdict.ZOMBIE, StalenessVerdict.IDLE):
                        resources.append(resource)
                self.logger.info(
                    f"  Polling path: {len(resources)} idle/zombie resources found"
                )

            # ── E_waste attribution + notification (shared for both paths) ────
            for resource in resources:
                stale_hours = (
                    resource.telemetry.observation_days * 24
                    if resource.telemetry else 14 * 24
                )
                self.calculator.calculate(resource, adapter, stale_hours)

                days_stale = (
                    resource.telemetry.observation_days
                    if resource.telemetry else 14
                )
                payload = self.notifier.build_payload(resource, days_stale)
                all_notifications.append(payload)

                self.logger.info(
                    f"  [{resource.verdict.value.upper()}] {resource.resource_id} | "
                    f"E_waste: {resource.e_waste_kg_co2:.2f} kg CO2e/month"
                )

        return all_notifications


# ===========================================================================
# SECTION 8: Entry Point (Illustrative)
# ===========================================================================

def main():
    """
    Illustrative entry point.
    In production: triggered by Cloud Scheduler (GCP), EventBridge (AWS),
    or Azure Timer Trigger on a daily/weekly cadence.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    scavenger = MultiCloudScavenger()

    # Register cloud adapters
    scavenger.register_cloud(CloudProvider.GCP, GCPResourceAdapter())
    scavenger.register_cloud(CloudProvider.AWS, AWSResourceAdapter())
    scavenger.register_cloud(CloudProvider.AZURE, AzureResourceAdapter())

    # Define scan targets
    targets = {
        CloudProvider.GCP:   "my-gcp-project-id",
        CloudProvider.AWS:   "123456789012",
        CloudProvider.AZURE: "subscription-uuid",
    }

    # Execute
    notifications = scavenger.scan(targets)

    # Report
    print(f"\n{'=' * 60}")
    print(f"SCAVENGER REPORT: {len(notifications)} zombie resources detected")
    print(f"{'=' * 60}")
    for notification in notifications:
        print(json.dumps(notification, indent=2))


if __name__ == "__main__":
    main()
