# Orchestration layer: carbon-aware placement

```
WattTime /v3/data ──► hourly history ──► scikit-learn forecast ──► planner ──► Placement
       ▲                                        ▲                                  │
       │                                        └──── per-region error (MAPE) ◄── observe(realized)
       └──────────────────────────── reconcile loop (re-plan with hysteresis) ◄─────┘
```

| Module | Role |
|---|---|
| `app/orchestration/watttime.py` | WattTime v3 client: region lookup, history (lbs/MWh → g/kWh, units verified) |
| `app/orchestration/forecast.py` | Gradient-boosted forecaster; must beat seasonal-naive on held-out hours or the baseline is served |
| `app/orchestration/planner.py` | Best (region, start hour) per workload under deadline and allowed regions; `kWh = P × PUE × T` |
| `app/orchestration/controller.py` | Closed loop: `reconcile` (plan/re-plan, hysteresis), `observe` (realized vs expected, error feedback) |

`app/services/carbon_orchestrator.py` (threshold recommender for wasteful existing resources) is separate.

## API
- `POST /api/v1/orchestration/placements`: list of `FlexibleWorkload` → placements
- `POST /api/v1/orchestration/placements/{name}/observe`: realized hourly intensity → outcome and feedback
- Needs `WATTTIME_USERNAME` / `WATTTIME_PASSWORD`; extra cloud-region coordinates via `GREENOPS_REGION_COORDS`.

## Known limits
- WattTime calls are covered by fake-session tests only; verify one live `history()` call first.
- Forecast accuracy is demonstrated on synthetic data, not real grid data. Check `ForecastReport` per region.
- Lead time is 48 h: workloads cannot be placed beyond that forecast horizon.
- Controller state (plans, error history) is in memory and single-process.
- Executing a placement (moving a job) is a stub (`RecordingExecutor`); the Kubernetes controller is the intended executor.
