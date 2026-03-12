Implementing the Ewaste Protocol

A Multi-Cloud Python Framework for Automated Resource Hygiene and Carbon Attribution

Authors: Sai Kalyan Kumar Modini

Co-Author: Sai Kiran Chary Kannyakanti

Subject Area: Sustainable Computing / GreenOps

1. Abstract

While previous research established the theoretical Ewaste formula [2], this paper provides a functional technical implementation for a Unified Multi-Cloud Resource Scavenger. We demonstrate a Python-based microservice capable of cross-cloud authentication (GCP, AWS, Azure), stale resource identification via metadata telemetry, and automated carbon-impact notification. This serves as the foundational "sensing" layer for the future orchestration layer of the Carbon-Aware Cloud.

2.The Problem: The "Ghost in the Machine"

In a typical enterprise environment, approximately 28% of cloud spend is wasted on unutilized resources. However, the environmental cost is often overlooked. A "stale" or "zombie" instance doesn't just cost money; it consumes base-load power (Pidle) regardless of utility. To solve this, we must bridge the gap between financial cost-saving (FinOps) and environmental sustainability (GreenOps) through automated enforcement.

3. Technical Architecture: The Sensing & Notifying Loop

Our implementation follows a recommender-first, five-stage pipeline. Each major cloud provider operates a continuously-updated idle resource detection service—GCP Idle VM Recommender, AWS Compute Optimizer, and Azure Advisor. Rather than rebuilding detection logic against raw metrics, our framework consumes these pre-validated signals as its primary input and adds the layers these native tools cannot provide: carbon attribution and graduated lifecycle enforcement.
Primary Detection (Recommender APIs): Query GCP Idle VM Recommender, AWS Compute Optimizer, or Azure Advisor. These services run continuously against provider telemetry and return pre-validated idle resources—no manual metric polling required on our side.
Fallback Detection (Telemetry Polling): For accounts where recommender APIs are unavailable (insufficient IAM permissions, new accounts, free tier), the framework falls back to querying Cloud Asset Inventory (GCP), AWS Config, and Azure Resource Graph, evaluating CPU, Network I/O, and Disk I/O over a rolling 14-day window.
Carbon Attribution: Interfacing with the GCP Cloud Carbon Footprint API (and equivalent estimates for AWS/Azure) to calculate the real-time CO2 impact of the identified waste using the Ewaste formula.
Graduated Lifecycle Enforcement: A four-stage escalation model (Notice → Warning → Stop → Delete) dispatched via Pub/Sub (GCP) or SNS (AWS), with tag-based owner override at every stage.
4. Technical Implementation (The "Scavenger" Framework)

4.1 Cross-Cloud Resource Sensing Logic (Fallback Path Thresholds)

When recommender APIs are unavailable, the fallback polling path applies the following threshold logic to self-identify zombie resources:
CPU Utilization: Average < 1% for 95% of the observation period.
Network Throughput: < 5 MB total cumulative data transfer over 7 days.
Disk State: Attached but unmounted volumes, or orphaned snapshots.
4.2 Python Implementation: The Unified Scavenger Framework

The implementation uses a recommender-first adapter pattern. Each cloud provider implements a shared interface with two discovery methods: discover_via_recommender() as the primary path, and discover_via_polling() as the fallback. The Ewaste calculator and notification engine are shared and run identically regardless of which path detected the idle resource. The core components are:

(i) Data Models and Threshold Configuration:
class CloudResource:
    resource_id: str
    resource_type: ResourceType          # VM, Disk, Snapshot, GPU
    provider: CloudProvider              # GCP, AWS, Azure
    region: str
    instance_type: str
    owner_email: Optional[str]
    tags: Dict[str, str]
    telemetry: Optional[TelemetryWindow]
    estimated_idle_power_kw: float       # P_idle in kW
    e_waste_kg_co2: float                # Calculated E_waste
  
class ZombieThresholds:
    cpu_avg_max_percent: float = 1.0
    cpu_below_threshold_ratio: float = 0.95
    network_max_bytes_7d: float = 5 * 1024 * 1024   # 5 MB
    gpu_avg_max_percent: float = 2.0
    memory_avg_max_percent: float = 5.0
    exempt_tags: List[str] = ["disaster-recovery", "warm-standby", "exempt-from-hygiene"]

(ii) Abstract Cloud Resource Adapter:

Each cloud provider implements this interface, enabling unified orchestration. The two discovery methods represent the primary and fallback detection paths:
class CloudResourceAdapter(ABC):
    def authenticate(self) -> None: ...
    def discover_via_recommender(self, project_or_account: str) -> List[CloudResource]:
    def discover_via_polling(self, project_or_account: str) -> List[CloudResource]:
    def fetch_telemetry(self, resource: CloudResource) -> TelemetryWindow:
    def get_carbon_intensity(self, region: str) -> float:
GCP: google-cloud-recommender (primary) and google-cloud-asset + google-cloud-monitoring (fallback).
AWS: boto3 compute-optimizer (primary) and boto3 EC2 + CloudWatch (fallback).
Azure: azure-mgmt-advisor (primary) and azure-mgmt-compute + azure-mgmt-monitor (fallback).
(iii) GCP Primary Detection: Idle VM Recommender (Representative Example):

Instead of querying all VMs and pulling metrics, the primary path consumes GCP's pre-computed idle recommendations directly:
class GCPResourceAdapter(CloudResourceAdapter):
    def discover_via_recommender(self, project_id):
        from google.cloud import recommender_v1
        rec_client = recommender_v1.RecommenderClient()
        resources = []
        for zone in self.scan_zones:   # configurable; enumerate dynamically in production
            parent = (
                f"projects/{project_id}/locations/{zone}/recommenders/"
                "google.compute.instance.IdleResourceRecommender"
            )
            for rec in rec_client.list_recommendations(parent=parent):
                if rec.state_info.state != ACTIVE:
                    continue
                overview = rec.content.overview
                res = CloudResource(
                    resource_id=overview["resourceName"],
                    region=zone.rsplit("-", 1)[0],
                    instance_type=overview["machineType"],
                    verdict=StalenessVerdict.ZOMBIE,   # pre-validated by GCP
                )
                res.telemetry = TelemetryWindow(
                    avg_cpu_percent=overview["avgCpuUsage"],
                    observation_days=overview["observationPeriodInDays"],
                )
                resources.append(res)
        return resources
  
    def discover_via_polling(self, project_id):   # fallback only
        # Cloud Asset Inventory scan (used when recommender is unavailable)
 
AWS uses boto3 compute-optimizer with get_ec2_instance_recommendations(), and Azure uses azure-mgmt-advisor with recommendations.list(). All three follow the same pattern: query the native recommender, map the output to the shared CloudResource model, and return pre-tagged ZOMBIE verdicts.

(iv) E_waste Carbon Attribution Calculator:

The calculator implements the core Ewaste carbon attribution model introduced in our previous research regarding Sustainable AI Foundations [1, 3]. By applying this formula to real-time provider telemetry, we move from theoretical estimation to verified environmental impact quantification.

Ewaste=Pidle×T×CI(region)×PUE

Where:
Pidle = Idle power draw of the resource (kW)
T = Duration the resource has been stale (hours)
CI region = Regional grid carbon intensity (gCO₂eq/kWh)
PUE = Power Usage Effectiveness of the data center (hyperscaler avg: 1.10)
class EwasteCalculator:
    DEFAULT_PUE = 1.1    # Hyperscaler average
  
    def calculate(self, resource, adapter, stale_hours):
        p_idle = resource.estimated_idle_power_kw       # kW
        ci = adapter.get_carbon_intensity(resource.region)  # gCO2eq/kWh
        pue = self.DEFAULT_PUE
        e_waste_kg = (p_idle * stale_hours * ci * pue) / 1000.0
        resource.e_waste_kg_co2 = e_waste_kg
        return e_waste_kg

Carbon intensity values are sourced from the GCP Carbon Footprint API (via BigQuery export), EPA eGRID data for AWS regions, and the Azure Emissions Impact Dashboard.

(v) Multi-Signal Zombie Classifier:

Rather than relying on a single metric, the classifier uses composite scoring across CPU, Network, GPU, and Memory signals to reduce false positives:
class ZombieClassifier:
    def classify(self, resource):
        # Check tag-based exemptions (DR, standby)
        if any(v in exempt_tags for v in resource.tags.values()):
            return StalenessVerdict.EXEMPT
  
        # Orphaned disks/snapshots are always zombies
        if resource.resource_type in (DISK, SNAPSHOT):
            return StalenessVerdict.ZOMBIE
  
        # Composite: CPU + Network + GPU + Memory
        cpu_zombie = (avg_cpu < 1% for 95% of window)
        net_zombie = (network < 5MB over 7 days)
        gpu_zombie = (avg_gpu < 2% if applicable)
        mem_zombie = (avg_memory < 5% if applicable)
  
        if cpu_zombie and net_zombie and gpu_zombie and mem_zombie:
            return StalenessVerdict.ZOMBIE
        elif cpu_zombie or net_zombie:
            return StalenessVerdict.IDLE
        return StalenessVerdict.ACTIVE
Note: The classifier is active only in the fallback polling path. Resources returned by the recommender APIs carry a pre-validated ZOMBIE verdict and skip classification.

(vi) Graduated Escalation Notification Engine:
Instead of immediate auto-deletion, the framework implements a four-stage graduated escalation model aligned with enterprise change-management practices:
Day
Level
Action
0
NOTICE
Informational alert to resource owner
3
WARNING
Resource will be stopped in 4 days
7
ACTION
Resource stopped; snapshot preserved for 7 days
14
FINAL
Resource and snapshot deleted in 48 hours

Resource owners can exempt resources at any stage by applying the tag hygiene-status: exempt-from-hygiene.

Sample notification payload:
{
    "severity": "WARNING",
    "resource": {
        "id": "vm-prod-analytics-04",
        "provider": "gcp",
        "region": "us-central1",
        "owner": "team-analytics@company.com"
    },
    "carbon_impact": {
        "e_waste_kg_co2_per_month": 14.2,
        "human_readable": "14.2 kg CO2e/month (equivalent to powering 1.5 U.S. homes)"
    },
    "action": {
        "level": "WARNING",
        "message": "Resource will be STOPPED in 4 days if no action taken",
        "override_instructions": "Apply tag 'hygiene-status: exempt-from-hygiene'"
    }
}

(vii) The Orchestrator:

The MultiCloudScavenger ties together all components. The scan() method implements the recommender-first logic with automatic fallback:

class MultiCloudScavenger:
    def scan(self, targets: Dict[CloudProvider, str]) -> List[dict]:
        for provider, account_id in targets.items():
            # Primary: consume cloud-native recommender output
            resources = adapter.discover_via_recommender(account_id)
  
            # Fallback: manual polling if recommender returns nothing
            if not resources:
                polled = adapter.discover_via_polling(account_id)
                for r in polled:
                    r.telemetry = adapter.fetch_telemetry(r)  # only in fallback path
                    if classifier.classify(r) in (ZOMBIE, IDLE):
                        resources.append(r)
  
            # Shared stages — run identically for both paths
            for resource in resources:
                calculator.calculate(resource, adapter, stale_hours)  # E_waste
                notifications.append(notifier.build_payload(resource))  # Notify
  
        return notifications
In production, this scan is triggered on a scheduled cadence via Cloud Scheduler (GCP), EventBridge (AWS), or Azure Timer Trigger. The complete runnable implementation is provided as a companion code artifact (scavenger.py)

5.Automated Notification & The "Social FinOps" Model

Identification is ineffective without enforcement. Our framework sends a structured JSON payload to the resource owner to drive immediate accountability. The graduated escalation model ensures that resources are not deleted without warning—owners receive multiple touchpoints with a clear override mechanism before any irreversible action is taken.

Example alert (Day 3 — WARNING level):

SUBJECT: [WARNING] Idle Resource — Carbon Limit Exceeded
Resource ID:		vm-prod-analytics-04
Status: 		Stale (0.2% Avg CPU over 14 days)
Carbon Waste:	14.2 kg CO2e / month (Equivalent to powering 1.5 U.S. homes)
Action: 		This resource will be STOPPED in 4 days.
Override:		Apply tag 'hygiene-status: exempt-from-hygiene' to cancel.

6. Conclusion & Future Work: The Kubernetes Pivot

This article proves that automated "sensing" of waste is technically viable across disparate cloud providers using a recommender-first approach that leverages each cloud's native idle detection infrastructure. The E_waste formula provides quantified carbon attribution, and the graduated escalation model provides the enforcement layer these native tools lack.

Our next phase of research will detail the Orchestration Layer, specifically using Kubernetes Custom Controllers to not just stop or delete resources, but migrate them. If a resource is required to stay active, the orchestrator will automatically move that workload to a lower-carbon region (e.g., from a coal-heavy grid to a wind-heavy grid) using Google Anthos. This transforms the scavenger's output notifications into actionable migration signals, closing the loop on the Carbon-Aware Cloud architecture.







7. References
Modini, S. K. K. (2026). Architecting Carbon-Aware Cloud Infrastructure: A Technical Implementation Guide using GCP. SSRN Electronic Journal. https://ssrn.com/abstract=6180079
Modini, S. K. K. (2026). Sustainable AI: A Practitioner Framework for Energy-Efficient Artificial Intelligence. SSRN Electronic Journal. https://ssrn.com/abstract=6180081
Modini, S. K. K. (2026). Sustainable AI: A Practitioner Framework for Energy-Efficient Artificial Intelligence SSRN Electronic Journal. https://ssrn.com/abstract=6099406
Google Cloud. (2025). Carbon Footprint: Understand the environmental impact of your Google Cloud usage. Google Cloud Documentation.
Flexera. (2025). State of the Cloud Report. (Cited for the 28% cloud waste metric).
U.S. Department of Energy. (2024). Frontiers in AI for Science, Security, and Technology (FASST).

