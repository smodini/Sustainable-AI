# GreenOps — How to Run

---

## Prerequisites

- Python 3.9+
- AWS CLI configured
- Azure CLI configured
- GCP credentials configured
- PostgreSQL running (for DB persistence)

---

## Step 1 — Install Dependencies

```bash
cd /Users/vijjuvimal/kalyan/Sustainable-AI/greenops
python3 -m pip install -r requirements.txt
```

---

## Step 2 — Configure Credentials

Edit `.env` in the `greenops/` folder. All values are already filled in:

```
AWS_ACCESS_KEY_ID=<your key>
AWS_SECRET_ACCESS_KEY=<your secret>
AWS_DEFAULT_REGION=us-east-1

AZURE_SUBSCRIPTION_ID=eacbfa05-1552-44c3-9327-f79ccd80046c
AZURE_TENANT_ID=5dd9c1fd-1433-43cf-abe0-601f82c665c2
AZURE_CLIENT_ID=<your client id>
AZURE_CLIENT_SECRET=<your client secret>

GCP_PROJECT_ID=patent-poc-project
```

---

## Step 3 — Start Cloud VMs (Test Instances)

```bash
# Start AWS EC2 instance
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/start_ec2.sh

# Start Azure VM
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/start_azure.sh

# Start GCP VM (requires billing enabled on patent-poc-project)
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/start_gcp.sh
```

---

## Step 4 — Start the API Server

```bash
cd /Users/vijjuvimal/kalyan/Sustainable-AI/greenops
python3 -m uvicorn app.main:app --reload --port 8001
```

Server runs at: http://localhost:8001

---

## Step 5 — Run Scans

Open a new terminal tab and run:

```bash
# Health check
curl http://localhost:8001/health

# Scan AWS only
curl http://localhost:8001/api/v1/aws/scan

# Scan Azure only
curl http://localhost:8001/api/v1/azure/scan

# Scan GCP only
curl http://localhost:8001/api/v1/gcp/scan

# Scan all clouds at once (unified)
curl http://localhost:8001/api/v1/scan

# View all findings stored in DB
curl http://localhost:8001/api/v1/findings

# View idle findings only
curl "http://localhost:8001/api/v1/findings?idle_only=true"

# View scan history
curl http://localhost:8001/api/v1/scans
```

---

## Step 6 — Launch the Dashboard

```bash
cd /Users/vijjuvimal/kalyan/Sustainable-AI/greenops
python3 -m streamlit run dashboard/app.py
```

Dashboard runs at: http://localhost:8501

---

## Stop Everything

### Stop the API server
Press `CTRL+C` in the terminal running uvicorn.

### Stop the dashboard
Press `CTRL+C` in the terminal running streamlit.

### Stop cloud VMs (avoid charges)

```bash
# Stop AWS EC2 instance
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/stop_ec2.sh

# Stop Azure VM
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/stop_azure.sh

# Stop GCP VM
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/stop_gcp.sh
```

### Verify everything is stopped

```bash
# Check AWS
aws ec2 describe-instances \
  --region us-east-1 \
  --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[*].Instances[*].[InstanceId,State.Name]' \
  --output table

# Check Azure
az vm list --resource-group greenops-rg \
  --show-details \
  --query "[].{Name:name, State:powerState}" \
  --output table

# Check GCP
gcloud compute instances list --project patent-poc-project
```

---

## API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/v1/aws/scan` | Scan AWS for idle VMs |
| GET | `/api/v1/azure/scan` | Scan Azure for idle VMs |
| GET | `/api/v1/gcp/scan` | Scan GCP for idle VMs |
| GET | `/api/v1/scan` | Unified scan — all 3 clouds |
| GET | `/api/v1/findings` | All findings from DB |
| GET | `/api/v1/findings?idle_only=true` | Idle findings only |
| GET | `/api/v1/scans` | Scan history |

---

## Troubleshooting

**Port already in use:**
```bash
lsof -ti :8001 | xargs kill -9
```

**GCP 403 billing error:**
Enable billing at https://console.developers.google.com/billing/enable?project=patent-poc-project

**Azure auth error:**
```bash
az login --service-principal \
  --username <AZURE_CLIENT_ID> \
  --password <AZURE_CLIENT_SECRET> \
  --tenant <AZURE_TENANT_ID>
```

**AWS returning 0 VMs:**
Make sure EC2 instance is started:
```bash
bash /Users/vijjuvimal/kalyan/Sustainable-AI/scripts/start_ec2.sh
```
