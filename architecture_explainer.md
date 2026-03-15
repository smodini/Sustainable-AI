# Article 4 Architecture: Plain-Language Explainer
## Why We Changed the Approach, and How the Two Paths Work

---

## The Core Question

> *"Why not just log into each cloud and scan everything?"*

That's what the first version of the code did — log in, list every VM, pull CPU metrics,
run our own checks. It works fine at small scale. But it has a problem:

**Each major cloud already does exactly that job — continuously, for free — and gives you
the answer if you just ask for it.**

GCP, AWS, and Azure all run idle resource detection internally 24/7. They're watching your
VMs, checking CPU, memory, network — the same signals we would check. They surface the
result through a Recommender or Advisor API. Our old code was re-doing thousands of API
calls to arrive at the same answer.

**The fix: ask the cloud for the result first. Only do the manual work if the API says nothing.**

---

## Visual Flow: Old Approach vs New Approach

### OLD: Poll-Based (every resource, every time)

```
┌─────────────────────────────────────────────────────────────────┐
│  Our Scavenger                                                  │
│                                                                 │
│  1. List ALL VMs in account (100s-1000s of API calls)           │
│  2. For each VM → pull 14 days of CPU metrics                   │
│  3. For each VM → pull 7 days of network metrics                │
│  4. Run our own threshold logic (< 1% CPU for 95% of time)      │
│  5. Classify as ZOMBIE / IDLE / ACTIVE                          │
│  6. Calculate E_waste                                           │
│  7. Send notification                                           │
│                                                                 │
│  Problem: Steps 1-5 already exist inside the cloud. We're       │
│  duplicating them using thousands of API calls at our cost.     │
└─────────────────────────────────────────────────────────────────┘
```

### NEW: Recommender-First (ask the cloud what it already knows)

```
┌─────────────────────────────────────────────────────────────────┐
│  PRIMARY PATH (what the cloud already computed for us)          │
│                                                                 │
│  GCP Idle VM Recommender  ─┐                                    │
│  AWS Compute Optimizer    ─┼─→ "Here are your idle VMs"         │
│  Azure Advisor            ─┘   (pre-validated, continuous)      │
│                                        │                        │
│                                        ▼                        │
│                         Our Scavenger adds what's MISSING:      │
│                         E_waste carbon attribution              │
│                         Graduated lifecycle enforcement         │
│                         Cross-cloud unified reporting           │
│                                        │                        │
│                                        ▼                        │
│                               Notification Sent                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  FALLBACK PATH (only triggered if recommender returns nothing)  │
│  Reason: new account, insufficient IAM permissions, free tier   │
│                                                                 │
│  1. List VMs via Cloud Asset Inventory / AWS Config             │
│  2. Pull 14-day CPU + network telemetry                         │
│  3. Apply ZombieClassifier thresholds                           │
│  4. E_waste carbon attribution                                  │
│  5. Notification sent                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## What Each Cloud's Native Recommender Does

| Cloud | Service | How it works | What it gives us |
|-------|---------|--------------|-----------------|
| **GCP** | Idle VM Recommender | Monitors all instances continuously. Flags VMs where CPU < 0.03 vCPUs for 28 days, with < 5% CPU 99% of the time | Instance name, machine type, avg CPU, observation period in days |
| **AWS** | Compute Optimizer | Runs ML-based analysis against 14 days of CloudWatch data. Classifies instances as `NotOptimized` or `Overprovisioned` | Instance ARN, finding type, current instance type, utilization metrics |
| **Azure** | Advisor (Cost category) | Analyses Monitor metrics and flags VMs with < 5% CPU and < 2% network over 7+ days | VM resource ID, region, VM size, recommendation description |

**Key point:** These services run whether we call them or not. We're not computing anything new —
we're just reading a pre-computed result.

---

## What Our Framework Adds (the value we bring)

The native recommenders tell you *what* is idle. They don't:

1. **Quantify the carbon waste** — they show cost savings, not CO2 impact
2. **Attribute carbon to a specific owner** — no owner tag lookup + notification
3. **Enforce lifecycle** — they show recommendations but don't act on them
4. **Work across all three clouds in a single unified view**
5. **Apply graduated escalation** — native tools have no Notice → Warning → Stop → Delete pipeline

Our framework is the **enforcement and attribution layer** sitting above what the clouds already provide.

---

## The Code Structure (How the Two Paths Are Wired)

### The Interface (what every cloud adapter must implement)

```python
class CloudResourceAdapter(ABC):
    def discover_via_recommender(...)  # PRIMARY: ask the cloud's native tool
    def discover_via_polling(...)      # FALLBACK: manually scan + pull metrics
    def fetch_telemetry(...)           # FALLBACK only: pull raw metric data
    def get_carbon_intensity(...)      # Used by E_waste calculator (both paths)
```

### The Orchestrator Logic

```python
# Step 1 — Try the recommender first
resources = adapter.discover_via_recommender(account_id)

# Step 2 — If it returned nothing, fall back to manual polling
if not resources:
    polled = adapter.discover_via_polling(account_id)
    for r in polled:
        r.telemetry = adapter.fetch_telemetry(r)     # only needed in fallback
        if classifier.classify(r) in (ZOMBIE, IDLE):
            resources.append(r)

# Step 3 — E_waste + Notification: SAME for both paths
for resource in resources:
    calculator.calculate(resource, adapter, stale_hours)
    notifications.append(notifier.build_payload(resource))
```

**The E_waste calculator and notification engine don't know or care which path found the resource.**
That's the clean part — the detection source is abstracted away.

---

## Why the Fallback Path Still Exists (and Must)

The fallback is not a backup for when the primary fails — it's a deliberate feature:

| Scenario | Why recommender returns nothing | What happens |
|----------|--------------------------------|--------------|
| New GCP project (< 14 days old) | Not enough observation data yet | Fallback kicks in |
| Recommender role not granted | Missing `roles/recommender.viewer` IAM permission | Fallback kicks in |
| AWS Free Tier account | Compute Optimizer requires at least 14 days of paid usage | Fallback kicks in |
| Azure Advisor disabled | Can be disabled by subscription policy | Fallback kicks in |

Without the fallback, the tool silently scans zero resources in these cases and reports success.
That's a silent failure — worse than a visible error.

---

## Article 4 vs Article 5: Clear Scope Separation

```
Article 3    →  Theoretical framework: E_waste formula, multi-cloud hygiene concept
Article 4    →  Detection + attribution + graduation notification
                (This article: recommender-first sensing layer)
Article 5    →  Kubernetes orchestration + Anthos workload migration
                (Act on detections: not delete, but MOVE to a greener region)
```

Article 5's Kubernetes layer will consume the notifications generated by Article 4's
scavenger and translate them into automated workload migrations — it doesn't need to
change the detection approach at all. The scope boundary is clean.

---

## Summary in One Sentence

> The cloud already knows which VMs are idle. Article 4's code asks for that answer first,
> adds the carbon cost and owner accountability layer on top, and only falls back to doing
> the detection itself when the native API has no data.

To justify the autonomous deprovisioning of assets, the framework utilizes a proprietary Electronic Waste & Idle Energy Formula ($E_{waste}$). This formula allows the controller to calculate the precise environmental cost of "Zombie" resources before triggering a termination command.The Formula:$$E_{waste} = \sum_{i=1}^{n} (P_{idle, i} \times T_{zombie, i} \times CI_{region})$$Where:$n$: The total number of identified orphaned resources (VMs, Disks, IPs).$P_{idle, i}$: The baseline power consumption (in kW) of resource $i$ while in an idle/unattached state.$T_{zombie, i}$: The duration (in hours) the resource has remained unutilized past the threshold.$CI_{region}$: The real-time Carbon Intensity (gCO2/kWh) of the specific cloud region where the resource resides.
