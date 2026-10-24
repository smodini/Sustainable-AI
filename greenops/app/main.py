from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import models
from app.db.crud import get_findings, get_scan_history, save_scan
from app.db.database import engine, get_db
from app.models.idleness import IdleState
from app.providers.aws.scanner import scan_aws
from app.providers.azure.scanner import scan_azure
from app.providers.gcp.scanner import scan_gcp
from app.services.carbon_orchestrator import CarbonDecisionInput, plan_orchestration

# POC convenience; replace with Alembic migrations before production.
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="GreenOps Multi-Cloud Energy Waste Platform")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/aws/scan")
def aws_scan(db: Session = Depends(get_db)):
    """Run an AWS scan, persist it, and return the full Idleness Schema payload."""
    summary = scan_aws()
    save_scan(db, summary)
    return summary.model_dump(mode="json")


def _run_scan(scan, db: Session):
    """Run a provider scan, persist it, return the Idleness Schema payload.

    A missing project/subscription configuration is a client-visible 400, not a 500.
    """
    try:
        summary = scan()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_scan(db, summary)
    return summary.model_dump(mode="json")


@app.get("/api/v1/gcp/scan")
def gcp_scan(db: Session = Depends(get_db)):
    """Scan the projects in GREENOPS_GCP_PROJECTS (Compute + Cloud Monitoring)."""
    return _run_scan(scan_gcp, db)


@app.get("/api/v1/azure/scan")
def azure_scan(db: Session = Depends(get_db)):
    """Scan the subscriptions in GREENOPS_AZURE_SUBSCRIPTIONS (ARM + Azure Monitor)."""
    return _run_scan(scan_azure, db)


@app.get("/api/v1/findings")
def findings(
    state: list[IdleState] | None = Query(default=None),
    idle_only: bool = False,
    db: Session = Depends(get_db),
):
    """Stored findings. ``idle_only`` is shorthand for state=idle&state=orphaned."""
    states = state or ([IdleState.IDLE, IdleState.ORPHANED] if idle_only else None)
    rows = get_findings(db, states=states)
    return [
        {
            "provider": r.provider,
            "account_id": r.account_id,
            "resource_id": r.resource_id,
            "resource_kind": r.resource_kind,
            "name": r.name,
            "region": r.region,
            "resource_type": r.resource_type,
            "idle_state": r.idle_state,
            "reason": r.reason,
            "exempt": r.exempt,
            "cpu_maximum": r.cpu_maximum,
            "network_mb_day": r.network_mb_day,
            "telemetry_coverage": r.telemetry_coverage,
            "e_waste_kwh_observed": r.e_waste_kwh_observed,
            "e_waste_kwh_monthly": r.e_waste_kwh_monthly,
            "evaluated_at": r.evaluated_at,
        }
        for r in rows
    ]


@app.get("/api/v1/scans")
def scan_history(db: Session = Depends(get_db)):
    rows = get_scan_history(db)
    return [
        {
            "id": r.id,
            "provider": r.provider,
            "total": r.total,
            "idle": r.idle,
            "orphaned": r.orphaned,
            "exempt": r.exempt,
            "unknown": r.unknown,
            "monthly_waste_kwh": r.monthly_waste_kwh,
            "errors": r.errors,
            "scanned_at": r.scanned_at,
        }
        for r in rows
    ]


@app.post("/api/v1/orchestration/plan")
def orchestration_plan(payload: list[dict[str, Any]] | dict[str, Any]):
    """Return orchestration decisions for a list of wasteful resources.

    Example payload:
    [{
        "name": "api-prod-01",
        "region": "us-east-1",
        "carbon_intensity_gco2_kwh": 420,
        "e_waste_kwh_monthly": 108,
        "exempt": false
    }]
    """
    resources = payload if isinstance(payload, list) else [payload]
    decisions = plan_orchestration(resources)
    return [decision.model_dump(mode="json") for decision in decisions]


@app.post("/api/v1/orchestration/plan/from-findings")
def orchestration_plan_from_findings(payload: list[dict[str, Any]] | dict[str, Any]):
    """Convenience endpoint that accepts GreenOps findings records."""
    resources = payload if isinstance(payload, list) else [payload]
    normalized = []
    for record in resources:
        normalized.append(
            CarbonDecisionInput(
                name=record.get("name") or record.get("resource_id") or "unknown-resource",
                region=record.get("region"),
                carbon_intensity_gco2_kwh=record.get("carbon_intensity_gco2_kwh", 0.0),
                e_waste_kwh_monthly=record.get("e_waste_kwh_monthly") or record.get("monthly_waste_kwh"),
                exempt=bool(record.get("exempt") or record.get("is_exempt")),
            )
        )
    decisions = plan_orchestration(normalized)
    return [decision.model_dump(mode="json") for decision in decisions]
