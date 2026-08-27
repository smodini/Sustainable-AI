# GreenOps — Multi-Cloud Energy Waste Detection Platform

**Authors:** Sai Kalyan Kumar Modini, Sai Kiran Chary Kannyakanti
**Patent Reference:** Sustainable AI / GreenOps Patent Specification
**Status:** POC — Phase 1 (AWS)

---

## What Is This?

GreenOps is a multi-cloud platform that automatically detects idle and zombie cloud
resources, calculates their energy waste using the patent formula, and provides
graduated remediation with full audit trail.

It bridges **FinOps** (cost) and **GreenOps** (carbon sustainability) in one unified platform.

---

## The Core Formula

```
E_waste = P_idle × PUE × T

P_idle  = 0.10 kW   (idle power draw per VM)
PUE     = 1.50       (data center Power Usage Effectiveness)
T       = 720 hours  (one calendar month)

→ 108 kWh wasted per idle VM per month
```

With carbon attribution:

```
Carbon_waste = E_waste × CI(region)

Example (us-east-1):
108 kWh × 380 gCO₂e/kWh = 41.0 kg CO₂e per idle VM per month
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| REST API | FastAPI + Uvicorn |
| AWS | Boto3 |
| Azure | azure-identity, azure-mgmt-compute, azure-monitor-query |
| GCP | google-cloud-compute, google-cloud-monitoring |
| Database | PostgreSQL + SQLAlchemy |
| Scheduler | APScheduler |
| Dashboard | Streamlit |
| Testing | Pytest |
| Deployment | Docker + docker-compose |

---

## Project Structure

```
greenops/
├── app/
│   ├── main.py                   ← FastAPI entry point
│   ├── config.py                 ← configurable idle thresholds
│   ├── models/vm.py              ← normalized VMResource schema
│   ├── services/
│   │   ├── energy_calculator.py  ← E_waste formula
│   │   ├── idle_detector.py      ← multi-signal idle detection
│   │   └── scanner.py            ← unified multi-cloud scanner
│   ├── providers/
│   │   ├── aws/                  ← EC2 + CloudWatch
│   │   ├── azure/                ← Azure VMs + Monitor
│   │   └── gcp/                  ← Compute Engine + Monitoring
│   └── db/                       ← PostgreSQL ORM + CRUD
├── tests/
├── dashboard/app.py              ← Streamlit dashboard
├── .env
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Quick Start

### 1. Clone and set up environment

```bash
git clone git@github.com:smodini/Sustainable-AI.git
cd Sustainable-AI
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your AWS/Azure/GCP credentials
```

### 3. Run the API

```bash
uvicorn app.main:app --reload
```

Open: http://localhost:8000/docs

### 4. Run tests

```bash
pytest
```

### 5. Run the dashboard

```bash
streamlit run dashboard/app.py
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/v1/aws/scan` | Scan AWS for idle VMs |
| GET | `/api/v1/azure/scan` | Scan Azure for idle VMs |
| GET | `/api/v1/gcp/scan` | Scan GCP for idle VMs |
| GET | `/api/v1/scan` | Unified scan — all clouds |
| GET | `/api/v1/findings` | Query stored findings |
| POST | `/api/v1/remediate` | Submit remediation action |

---

## Sample Scan Output

```json
{
  "provider": "AWS",
  "total_vms": 23,
  "idle_vms": 4,
  "active_vms": 19,
  "estimated_monthly_waste_kwh": 432,
  "resources": [
    {
      "resource_id": "i-0abc123",
      "name": "dev-api-01",
      "region": "us-east-1",
      "cpu_maximum": 1.3,
      "network_mb_day": 1.8,
      "idle": true,
      "risk": "HIGH",
      "energy_waste_kwh": 108
    }
  ]
}
```

---

## Idle Detection Thresholds (configurable)

| Signal | Default Threshold |
|---|---|
| CPU maximum | < 5% over observation window |
| Network | < 5 MB/day |
| Observation window | 7 days |

Override in `.env`:
```
CPU_THRESHOLD=5.0
NETWORK_THRESHOLD_MB=5.0
OBSERVATION_DAYS=7
```

---

## Risk Levels

| Idle Duration | Risk | Action |
|---|---|---|
| < 2 days | LOW | Monitor |
| 2–6 days | MEDIUM | Notify owner |
| 7–13 days | HIGH | Stop recommendation |
| ≥ 14 days | CRITICAL | Snapshot + delete recommendation |

---

## Safety Controls

- `REMEDIATION_ENABLED=false` in `.env` → dry-run mode, no destructive actions
- Snapshot always taken before stop or delete
- Tag `greenops-ignore=true` on any resource to exempt it permanently
- Full approval workflow before any action executes

---

## Development Milestones

See [BUILD_STEPS.md](./BUILD_STEPS.md) for the detailed step-by-step build log.

| Milestone | Status |
|---|---|
| M1 FastAPI + /health | ⬜ |
| M2 Energy formula | ⬜ |
| M3 Idle policy engine | ⬜ |
| M4 AWS EC2 inventory | ⬜ |
| M5 AWS CloudWatch metrics | ⬜ |
| M6 AWS idle scanner | ⬜ |
| M7 Energy integration | ⬜ |
| M8 PostgreSQL | ⬜ |
| M9 Streamlit dashboard | ⬜ |
| M10 Azure provider | ⬜ |
| M11 GCP provider | ⬜ |
| M12 Unified scanner | ⬜ |
| M13 Storage hygiene | ⬜ |
| M14 Recommendations | ⬜ |
| M15 Remediation engine | ⬜ |
| M16 Carbon attribution | ⬜ |
| M17 Carbon-aware orchestration | ⬜ |

---

## Related Documents

- [DESIGN_AND_ARCHITECTURE.md](./DESIGN_AND_ARCHITECTURE.md) — full system design
- [BUILD_STEPS.md](./BUILD_STEPS.md) — step-by-step build log
- [article_4.md](./article_4.md) — research article (Article 4)
- [architecture_explainer.md](./architecture_explainer.md) — plain-language architecture explainer
