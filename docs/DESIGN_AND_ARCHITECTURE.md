# GreenOps — Design & Architecture
**Multi-Cloud Energy Waste Detection and Carbon Attribution Platform**

Authors: Sai Kalyan Kumar Modini, Sai Kiran Chary Kannyakanti
Date: 2026
Patent Reference: Sustainable AI / GreenOps Patent Specification

---

## 1. Problem Statement

In a typical enterprise cloud environment, approximately **28% of cloud spend** is wasted on
unutilized or idle resources. Beyond cost, every idle VM consumes base-load power (P_idle)
regardless of whether it is doing useful work. This platform bridges the gap between
**FinOps** (cost savings) and **GreenOps** (carbon sustainability) through automated
detection, attribution, and remediation.

---

## 2. Core Formula (Patent Baseline)

```
E_waste = P_idle × PUE × T

Where:
  P_idle  = 0.10 kW       (idle power draw per VM)
  PUE     = 1.50           (Power Usage Effectiveness, data center overhead)
  T       = 720 hours      (one calendar month)

Patent Baseline:
  0.10 × 1.50 × 720 = 108 kWh per idle VM per month
```

Extended with carbon attribution:

```
Carbon_waste = E_waste × CI(region)

Where:
  CI(region) = grid carbon intensity in gCO₂e/kWh
               (e.g., us-east-1 ≈ 380 gCO₂e/kWh)

Example:
  108 kWh × 380 gCO₂e/kWh = 41,040 gCO₂e = 41.0 kg CO₂e/month per idle VM
```

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLOUD PROVIDERS                              │
│                                                                      │
│      AWS                   Azure                    GCP              │
│  EC2 + CloudWatch    VMs + Azure Monitor    Compute + Monitoring     │
│       │                      │                       │               │
└───────┼──────────────────────┼───────────────────────┼───────────────┘
        │                      │                       │
        ▼                      ▼                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          SCANNER LAYER                               │
│                                                                      │
│  app/providers/aws/    app/providers/azure/    app/providers/gcp/   │
│  ├── client.py         ├── client.py           ├── client.py        │
│  ├── instances.py      ├── instances.py        ├── instances.py     │
│  ├── metrics.py        ├── metrics.py          ├── metrics.py       │
│  └── scanner.py        └── scanner.py          └── scanner.py       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       NORMALIZATION LAYER                            │
│                                                                      │
│   app/models/vm.py  →  VMResource (single unified schema)           │
│                                                                      │
│   InstanceId   (AWS)   →  resource_id                               │
│   resourceId   (Azure) →  resource_id                               │
│   instance.id  (GCP)   →  resource_id                               │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        DETECTION LAYER                               │
│                                                                      │
│   app/services/idle_detector.py                                     │
│                                                                      │
│   Signal 1 — CPU max < 5% over observation window                   │
│   Signal 2 — Network < 5 MB/day                                     │
│   Signal 3 — Tag exemptions  (greenops-ignore=true)                 │
│   Signal 4 — Orphaned storage (unattached disks)                    │
│                                                                      │
│   Verdict:  ACTIVE | IDLE | ZOMBIE | EXEMPT                         │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    ENERGY WASTE CALCULATOR                           │
│                                                                      │
│   app/services/energy_calculator.py                                 │
│                                                                      │
│   E_waste = P_idle × PUE × T                                        │
│   Carbon   = E_waste × CI(region)                                   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       PERSISTENCE LAYER                              │
│                                                                      │
│   PostgreSQL + SQLAlchemy                                           │
│                                                                      │
│   ├── cloud_accounts       registered cloud accounts                │
│   ├── resources            normalized VM/disk inventory             │
│   ├── resource_metrics     CPU, network per scan                    │
│   ├── scan_runs            scan history + timestamps                │
│   ├── idle_findings        idle verdicts + energy waste             │
│   └── remediation_actions  approvals, actions, results              │
└──────────┬────────────────────────────────────────────┬─────────────┘
           │                                            │
           ▼                                            ▼
┌──────────────────────┐                  ┌────────────────────────────┐
│      FastAPI         │                  │        Streamlit           │
│    REST Backend      │                  │        Dashboard           │
│                      │                  │                            │
│  GET  /health        │                  │  Total Resources           │
│  GET  /api/v1/aws/   │                  │  Idle VMs                  │
│  GET  /api/v1/scan   │                  │  Energy Waste kWh          │
│  POST /remediate     │                  │  Carbon kg CO₂e            │
└──────────┬───────────┘                  │  Per-VM drill-down         │
           │                              └────────────────────────────┘
           ▼
┌──────────────────────┐
│  Remediation Engine  │
│                      │
│  IGNORE              │
│  STOP                │
│  SNAPSHOT            │
│  SNAPSHOT + DELETE   │
│                      │
│  Approval workflow   │
│  Dry-run mode        │
│  Audit log           │
└──────────────────────┘
           ▲
           │
┌──────────────────────┐
│     APScheduler      │
│  Recurring scans     │
│  Every 24 hours      │
└──────────────────────┘
```

---

## 4. Project Folder Structure

```
greenops/
│
├── app/
│   ├── __init__.py
│   ├── main.py                         ← FastAPI entry point
│   ├── config.py                       ← IdlePolicy, env config
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── vm.py                       ← VMResource (normalized schema)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── energy_calculator.py        ← E_waste = P_idle × PUE × T
│   │   ├── idle_detector.py            ← multi-signal idle detection
│   │   ├── scanner.py                  ← unified multi-cloud scanner
│   │   └── remediation/
│   │       ├── aws.py
│   │       ├── azure.py
│   │       ├── gcp.py
│   │       └── manager.py
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── aws/
│   │   │   ├── __init__.py
│   │   │   ├── client.py               ← boto3 EC2 + CloudWatch clients
│   │   │   ├── instances.py            ← EC2 inventory with pagination
│   │   │   ├── metrics.py              ← CloudWatch CPU + Network
│   │   │   └── scanner.py              ← AWS scan → VMResource list
│   │   ├── azure/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── instances.py
│   │   │   ├── metrics.py
│   │   │   └── scanner.py
│   │   └── gcp/
│   │       ├── __init__.py
│   │       ├── client.py
│   │       ├── instances.py
│   │       ├── metrics.py
│   │       └── scanner.py
│   │
│   └── db/
│       ├── __init__.py
│       ├── database.py                 ← SQLAlchemy engine + session
│       ├── models.py                   ← ORM table definitions
│       └── crud.py                     ← DB read/write operations
│
├── tests/
│   ├── test_energy.py
│   ├── test_idle_detector.py
│   └── test_aws_scanner.py
│
├── dashboard/
│   └── app.py                          ← Streamlit dashboard
│
├── .env                                ← secrets (never commit)
├── .gitignore
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── README.md
├── DESIGN_AND_ARCHITECTURE.md
└── BUILD_STEPS.md
```

---

## 5. Data Model — VMResource (Normalized Schema)

Every cloud provider's raw output is converted into this single schema before any
detection or calculation runs. The energy calculator and idle detector never see
provider-specific field names.

| Field | Type | Description |
|---|---|---|
| provider | str | "AWS" / "Azure" / "GCP" |
| account_id | str? | AWS account / Azure subscription / GCP project |
| resource_id | str | normalized unique ID |
| name | str | human-readable name |
| region | str | e.g. "us-east-1" |
| instance_type | str? | e.g. "t3.medium", "Standard_B2s" |
| state | str | "running" / "stopped" / "deallocated" |
| cpu_average | float | % over observation window |
| cpu_maximum | float | % peak over observation window |
| network_in_mb | float | MB received over observation window |
| network_out_mb | float | MB sent over observation window |
| observation_days | int | default 7 |
| idle | bool | verdict from idle_detector |
| idle_hours | float | estimated hours idle |
| energy_waste_kwh | float | E_waste = P_idle × PUE × idle_hours |
| risk | str | "LOW" / "MEDIUM" / "HIGH" / "CRITICAL" |

---

## 6. Idle Detection Logic

```
Input: cpu_maximum, network_mb_per_day, tags, resource_type

Step 1 — Tag exemption
  tag "greenops-ignore" = "true"  →  EXEMPT (skip everything)

Step 2 — Orphaned storage
  resource_type = DISK and not attached  →  ZOMBIE

Step 3 — Multi-signal composite (VMs)
  cpu_idle = cpu_maximum < 5.0%
  net_idle = network_mb_per_day < 5.0 MB

  cpu_idle AND net_idle  →  ZOMBIE
  cpu_idle OR  net_idle  →  IDLE
  neither                →  ACTIVE
```

Thresholds are configurable via `IdlePolicy` in `app/config.py`.
No source code changes needed to adjust sensitivity.

---

## 7. Risk Classification

| Idle Duration | Risk | Recommended Action |
|---|---|---|
| < 2 days | LOW | Monitor |
| 2–6 days | MEDIUM | Notify owner |
| 7–13 days | HIGH | Warning + stop recommendation |
| ≥ 14 days | CRITICAL | Snapshot + delete recommendation |

---

## 8. Remediation Workflow

```
Idle VM detected
      │
      ▼
Recommendation created  (STOP / SNAPSHOT / DELETE)
      │
      ▼
Owner notified  (email / Slack / webhook)
      │
      ▼
Approval required  (stored: who approved, when)
      │
      ▼
Action executed  (dry-run first, then live)
      │
      ▼
Result logged  (audit trail in remediation_actions table)
```

Safety controls:
- `REMEDIATION_ENABLED=false` in `.env` → dry-run only, zero destructive actions
- Snapshot always taken before stop or delete
- Tag `greenops-ignore=true` exempts any resource at any stage

---

## 9. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Language | Python 3.12 | Core runtime |
| REST API | FastAPI + Uvicorn | Backend endpoints |
| AWS | Boto3 | EC2 inventory + CloudWatch metrics |
| Azure | azure-identity, azure-mgmt-compute, azure-monitor-query | VM inventory + Monitor metrics |
| GCP | google-cloud-compute, google-cloud-monitoring | Compute inventory + Cloud Monitoring |
| Database | PostgreSQL | Scan history, findings, audit log |
| ORM | SQLAlchemy + Alembic | DB models + migrations |
| Scheduler | APScheduler | Recurring 24-hour scans |
| Dashboard | Streamlit + Pandas | Visual reporting |
| Testing | Pytest | Unit + integration tests |
| Deployment | Docker + docker-compose | Containerized runtime |

---

## 10. API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health check |
| GET | `/api/v1/aws/scan` | Scan AWS, return idle findings |
| GET | `/api/v1/azure/scan` | Scan Azure, return idle findings |
| GET | `/api/v1/gcp/scan` | Scan GCP, return idle findings |
| GET | `/api/v1/scan` | Unified scan across all clouds |
| GET | `/api/v1/findings` | Query stored findings from DB |
| POST | `/api/v1/remediate` | Submit remediation action |
| GET | `/api/v1/remediate/{id}` | Check remediation status |

---

## 11. Database Schema (Key Tables)

```sql
resources (
  id, provider, provider_resource_id, name,
  region, instance_type, state, created_at, last_seen_at
)

idle_findings (
  id, resource_id, scan_id,
  cpu_average, cpu_maximum, network_mb_day,
  idle, idle_hours, energy_waste_kwh,
  carbon_kg, risk, detected_at
)

remediation_actions (
  id, resource_id, action_type,
  recommended_by, approved_by, approved_at,
  executed_at, result, dry_run
)
```

---

## 12. Development Milestones

| Milestone | What Gets Built | Exit Criteria |
|---|---|---|
| M1 | FastAPI + `/health` | Returns `{"status": "healthy"}` |
| M2 | Energy formula | `calculate_energy_waste(720) == 108.0` |
| M3 | Idle policy engine | `is_vm_idle(1.2, 1.5) == True` |
| M4 | AWS EC2 inventory | List instances from real account |
| M5 | AWS CloudWatch metrics | CPU + Network per instance |
| M6 | AWS idle scanner | Idle VMs identified |
| M7 | Energy integration | Idle VMs × 108 kWh reported |
| M8 | PostgreSQL | Scan results persisted |
| M9 | Streamlit dashboard | Visual report of findings |
| M10 | Azure provider | Azure VMs detected + normalized |
| M11 | GCP provider | GCP VMs detected + normalized |
| M12 | Unified scanner | AWS + Azure + GCP in one response |
| M13 | Storage hygiene | Orphaned disks detected |
| M14 | Recommendations | Stop/snapshot suggestions |
| M15 | Remediation engine | Approved cleanup with audit log |
| M16 | Carbon attribution | CO₂e per idle VM per region |
| M17 | Carbon-aware orchestration | Green-region placement recommendations |

---

## 13. Carbon-Aware Orchestration (M17 — Final Phase)

After idle resources are detected and attributed, the orchestrator evaluates whether
a workload should be migrated to a lower-carbon region rather than stopped.

```
Current Region:    us-east-1   →  410 gCO₂/kWh
Alternative:       us-west-2   →  170 gCO₂/kWh
Workload type:     batch-processing
Latency:           LOW

GreenOps Action:
  Migrate to us-west-2
  Carbon saving: ~57% reduction
```

This module is intentionally last. It requires a fully working multi-cloud hygiene
engine, stable DB history, and a reliable remediation workflow before it is meaningful.
