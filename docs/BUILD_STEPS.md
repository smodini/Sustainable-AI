# GreenOps — Build Steps
**Step-by-step log of what we are building, why, and in what order**

---

## Ground Rules

- Build one milestone at a time. Do not move forward until the current milestone passes.
- Every milestone has a clear exit criterion — a test, an API response, or a visible output.
- AWS is built first and fully working before Azure or GCP are touched.
- The energy formula and idle detector are cloud-agnostic from day one.
- No destructive AWS actions (stop/terminate) until M15 with `REMEDIATION_ENABLED=true`.

---

## Phase 1 — Foundation (M1–M3)

### M1 — FastAPI + /health

**What:** Bare FastAPI app running locally.

**Why:** Confirms Python environment, dependencies, and server are all working before
any cloud code is written.

**Files:**
```
greenops/
├── app/
│   ├── __init__.py
│   └── main.py
├── .env
├── .gitignore
└── requirements.txt
```

**Install:**
```bash
pip install fastapi uvicorn boto3 pydantic python-dotenv
```

**Code — app/main.py:**
```python
from fastapi import FastAPI

app = FastAPI(title="GreenOps Multi-Cloud Energy Waste Platform")

@app.get("/health")
def health():
    return {"status": "healthy"}
```

**Run:**
```bash
uvicorn app.main:app --reload
```

**Exit criterion:**
```
GET http://localhost:8000/health
→ {"status": "healthy"}
```

---

### M2 — Energy Waste Formula

**What:** Implement `E_waste = P_idle × PUE × T` as a standalone function.

**Why:** This is the core of the patent. It must work correctly and independently
before any cloud scanning is added. Every provider will call this same function.

**Files:**
```
app/services/
├── __init__.py
└── energy_calculator.py
```

**Constants:**
```
P_idle = 0.10 kW
PUE    = 1.50
T      = 720 hours (one month)

0.10 × 1.50 × 720 = 108.0 kWh
```

**Exit criterion:**
```python
calculate_energy_waste(720)  == 108.0   # full month
calculate_energy_waste(100)  == 15.0    # actual idle hours
calculate_energy_waste(0)    == 0.0     # zero hours
```

---

### M3 — Idle Policy Engine

**What:** Multi-signal idle detection as a standalone function with configurable thresholds.

**Why:** Separating idle detection from cloud APIs means the same logic works for
AWS, Azure, and GCP without duplication. Thresholds are configurable without
changing source code.

**Files:**
```
app/services/idle_detector.py
app/config.py
```

**Default thresholds:**
```
CPU maximum      < 5.0%
Network/day      < 5.0 MB
Observation      7 days
```

**Exit criterion:**
```python
is_vm_idle(cpu_maximum=2.1, network_mb_per_day=1.5)  == True
is_vm_idle(cpu_maximum=8.0, network_mb_per_day=1.5)  == False
is_vm_idle(cpu_maximum=2.1, network_mb_per_day=9.0)  == False
```

---

### M3 Tests — Pytest

**What:** Automated tests for M2 and M3.

**Files:**
```
tests/
├── test_energy.py
└── test_idle_detector.py
```

**Exit criterion:**
```
pytest
→ 6 passed
```

---

## Phase 2 — AWS (M4–M7)

### M4 — AWS EC2 Inventory

**What:** Connect to AWS via boto3 and list all EC2 instances across all regions.

**Why:** You need the full inventory before you can pull metrics. Pagination is
required — a single AWS account can have hundreds of instances.

**Files:**
```
app/providers/aws/
├── __init__.py
├── client.py       ← boto3 EC2 + CloudWatch clients
└── instances.py    ← paginated EC2 inventory
```

**AWS permissions required (read-only):**
```
ec2:DescribeInstances
ec2:DescribeRegions
sts:GetCallerIdentity
```

**Setup:**
```bash
aws configure
# Enter: Access Key, Secret Key, default region, output format
```

**Exit criterion:**
```python
# Returns list of dicts with at minimum:
[
  {
    "instance_id": "i-0abc123",
    "instance_type": "t3.medium",
    "state": "running",
    "region": "us-east-1"
  }
]
```

---

### M5 — AWS CloudWatch Metrics

**What:** For each running EC2 instance, retrieve 7-day CPU and Network metrics.

**Why:** These are the two signals used by the idle detector. Without real metrics,
idle detection is guesswork.

**Files:**
```
app/providers/aws/metrics.py
```

**Metrics retrieved:**
```
CPUUtilization   → average + maximum over 7 days
NetworkIn        → total bytes over 7 days → convert to MB/day
NetworkOut       → total bytes over 7 days → convert to MB/day
```

**Additional AWS permission:**
```
cloudwatch:GetMetricStatistics
```

**Exit criterion:**
```
VM: dev-api-01
7-day average CPU: 1.2%
7-day maximum CPU: 3.7%
Network in+out:    2.1 MB/day
```

---

### M6 — AWS Idle Scanner

**What:** Combine EC2 inventory + CloudWatch metrics + idle detector into one scan.

**Files:**
```
app/providers/aws/scanner.py
```

**Flow:**
```
get EC2 instances (all regions)
        ↓
for each running instance:
    get CPU metrics (CloudWatch)
    get Network metrics (CloudWatch)
        ↓
    is_vm_idle(cpu_maximum, network_mb_per_day)
        ↓
    normalize → VMResource
```

**Exit criterion:**
```
AWS account scanned
Running VMs: 19
Idle VMs identified: 4
  - dev-api-01  (CPU: 1.3%, Network: 1.8 MB/day)
  - test-db-02  (CPU: 0.7%, Network: 0.3 MB/day)
  ...
```

---

### M7 — Energy Integration

**What:** For each idle VM, call `calculate_energy_waste()` and attach the result
to the VMResource. Add `GET /api/v1/aws/scan` endpoint.

**Files:**
```
app/providers/aws/scanner.py   ← add energy_waste_kwh
app/main.py                    ← add /api/v1/aws/scan route
```

**Exit criterion:**
```json
GET /api/v1/aws/scan
{
  "provider": "AWS",
  "total_vms": 23,
  "idle_vms": 4,
  "estimated_monthly_waste_kwh": 432,
  "resources": [...]
}
```

Stop here. Validate results manually against the AWS console before continuing.

---

## Phase 3 — Persistence (M8)

### M8 — PostgreSQL + Scan History

**What:** Store every scan result in PostgreSQL so findings accumulate over time.

**Why:** A single scan is a snapshot. Historical data is evidence — it shows a VM
has been idle for 3 consecutive weeks, which is far stronger than one observation.

**Install:**
```bash
pip install sqlalchemy psycopg2-binary alembic
```

**Files:**
```
app/db/
├── __init__.py
├── database.py    ← engine + session
├── models.py      ← ORM tables
└── crud.py        ← read/write operations
```

**Key tables:**
```
resources          — VM inventory (one row per resource)
scan_runs          — one row per scan execution
idle_findings      — one row per idle VM per scan
```

**Exit criterion:**
```
Run scan twice (24 hours apart)
Query idle_findings
→ same VM appears in both scans with detected_at timestamps
```

---

## Phase 4 — Dashboard (M9)

### M9 — Streamlit Dashboard

**What:** Visual dashboard showing scan results from the database.

**Install:**
```bash
pip install streamlit pandas
```

**Files:**
```
dashboard/app.py
```

**Dashboard shows:**
```
GREENOPS
─────────────────────────────────
Total Resources     382
Idle VMs             29
Energy Waste    3,132 kWh/month
─────────────────────────────────
Provider breakdown: AWS / Azure / GCP
─────────────────────────────────
Table: Cloud | VM | Region | CPU | Idle Days | Waste | Risk
─────────────────────────────────
Filters: Provider / Region / Risk level
```

**Run:**
```bash
streamlit run dashboard/app.py
```

**Exit criterion:** Dashboard loads, shows real data from PostgreSQL, filters work.

---

## Phase 5 — Azure (M10)

### M10 — Azure Provider

**What:** Add Azure VM inventory + Azure Monitor metrics, normalize to VMResource.

**Install:**
```bash
pip install azure-identity azure-mgmt-compute azure-monitor-query azure-mgmt-resource
```

**Files:**
```
app/providers/azure/
├── __init__.py
├── client.py
├── instances.py
├── metrics.py
└── scanner.py
```

**Key rule:** Azure scanner calls the same `is_vm_idle()` and `calculate_energy_waste()`
functions as AWS. No separate energy logic.

**Exit criterion:**
```
GET /api/v1/azure/scan
→ same response shape as /api/v1/aws/scan
```

---

## Phase 6 — GCP (M11)

### M11 — GCP Provider

**What:** Add GCP Compute Engine inventory + Cloud Monitoring metrics, normalize to VMResource.

**Install:**
```bash
pip install google-cloud-compute google-cloud-monitoring google-cloud-asset
```

**Files:**
```
app/providers/gcp/
├── __init__.py
├── client.py
├── instances.py
├── metrics.py
└── scanner.py
```

**Exit criterion:**
```
GET /api/v1/gcp/scan
→ same response shape as /api/v1/aws/scan
```

---

## Phase 7 — Unified Scanner (M12)

### M12 — All Clouds in One Response

**What:** `GET /api/v1/scan` runs AWS + Azure + GCP concurrently and returns
a unified summary.

**Files:**
```
app/services/scanner.py
app/main.py   ← add /api/v1/scan route
```

**Exit criterion:**
```json
GET /api/v1/scan
{
  "total_vms": 220,
  "idle_vms": 18,
  "energy_waste_kwh": 1944,
  "providers": {
    "aws": 864,
    "azure": 648,
    "gcp": 432
  }
}
```

---

## Phase 8 — Storage Hygiene (M13)

### M13 — Orphaned Disk Detection

**What:** Detect unattached storage volumes across all three clouds.

**Why:** The patent explicitly includes orphaned storage normalization. Unattached
disks consume cost and energy with zero utility.

**Detection logic per cloud:**
```
AWS   — EBS volumes with state = "available"
Azure — Managed Disks with managed_by = null
GCP   — Persistent Disks with users = []
```

**Normalized verdict:** `ORPHANED_STORAGE`

**Exit criterion:** Orphaned disks appear in scan results and dashboard alongside idle VMs.

---

## Phase 9 — Recommendations (M14)

### M14 — Remediation Recommendations

**What:** For each idle/zombie resource, generate a recommended action.
Do not execute anything yet.

**Recommendation options:**
```
IGNORE           — mark as acknowledged
STOP             — stop the VM
SNAPSHOT         — take snapshot only
SNAPSHOT+DELETE  — snapshot then delete
```

**Exit criterion:** Each idle VM in the API response includes a `recommended_action` field.

---

## Phase 10 — Remediation Engine (M15)

### M15 — Approved Cleanup

**What:** Implement the full approval workflow and execute approved actions.

**Files:**
```
app/services/remediation/
├── aws.py
├── azure.py
├── gcp.py
└── manager.py
```

**Additional AWS permissions (only when REMEDIATION_ENABLED=true):**
```
ec2:StopInstances
ec2:CreateSnapshot
ec2:TerminateInstances
```

**Safety controls:**
```
REMEDIATION_ENABLED=false   → dry-run only (default)
REMEDIATION_ENABLED=true    → live execution
```

**Workflow:**
```
Idle detected → Recommendation → Owner notified → Approval → Execute → Log
```

**Exit criterion:**
```
Dry-run: action logged, nothing executed
Live:    VM stopped, snapshot created, audit row written to remediation_actions
```

---

## Phase 11 — Carbon Attribution (M16)

### M16 — CO₂e Calculation

**What:** Extend energy findings with carbon emissions using regional grid intensity.

**Formula:**
```
Carbon_waste = E_waste × CI(region)

Example:
108 kWh × 380 gCO₂e/kWh = 41,040 gCO₂e = 41.0 kg CO₂e/month
```

**Carbon intensity sources:**
```
AWS   — EPA eGRID data per region
Azure — Azure Emissions Impact Dashboard
GCP   — GCP Carbon Footprint API / BigQuery export
```

**Exit criterion:**
```
Each idle_finding includes carbon_kg
Dashboard shows "Estimated Carbon Waste: X kg CO₂e/month"
```

---

## Phase 12 — Carbon-Aware Orchestration (M17)

### M17 — Green-Region Placement

**What:** For workloads that must stay running, recommend migration to a lower-carbon
region rather than stopping them.

**Why:** Some workloads are legitimately active but placed in a high-carbon region
by default. Moving them is greener than stopping them.

**Logic:**
```
Current region carbon intensity  →  compare against alternatives
Workload latency sensitivity     →  LOW allows cross-region migration
Policy engine                    →  approve/reject migration

If carbon saving > threshold AND latency = LOW:
  → Recommend migration to lower-carbon region
```

**Example output:**
```
Resource:   batch-job-07
Region:     us-east-1  (410 gCO₂/kWh)
Suggestion: Migrate to us-west-2 (170 gCO₂/kWh)
Saving:     57% carbon reduction
```

**Exit criterion:** Carbon-aware placement recommendations appear in API and dashboard.

---

## Scheduler Setup (runs alongside all phases from M8 onward)

```python
# APScheduler — runs scan every 24 hours
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(scan_all_clouds, "interval", hours=24)
scheduler.start()
```

---

## Environment Variables (.env)

```
# AWS
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=us-east-1

# Azure
AZURE_SUBSCRIPTION_ID=
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=

# GCP
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
GCP_PROJECT_ID=

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/greenops

# Idle thresholds
CPU_THRESHOLD=5.0
NETWORK_THRESHOLD_MB=5.0
OBSERVATION_DAYS=7

# Remediation
REMEDIATION_ENABLED=false
```

---

## Current Status

| Milestone | Status |
|---|---|
| M1 FastAPI + /health | ⬜ Not started |
| M2 Energy formula | ⬜ Not started |
| M3 Idle policy engine | ⬜ Not started |
| M4 AWS EC2 inventory | ⬜ Not started |
| M5 AWS CloudWatch metrics | ⬜ Not started |
| M6 AWS idle scanner | ⬜ Not started |
| M7 Energy integration | ⬜ Not started |
| M8 PostgreSQL | ⬜ Not started |
| M9 Streamlit dashboard | ⬜ Not started |
| M10 Azure provider | ⬜ Not started |
| M11 GCP provider | ⬜ Not started |
| M12 Unified scanner | ⬜ Not started |
| M13 Storage hygiene | ⬜ Not started |
| M14 Recommendations | ⬜ Not started |
| M15 Remediation engine | ⬜ Not started |
| M16 Carbon attribution | ⬜ Not started |
| M17 Carbon-aware orchestration | ⬜ Not started |
