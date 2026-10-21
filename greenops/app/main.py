from typing import Optional

from fastapi import Depends, FastAPI, Query
from sqlalchemy.orm import Session

from app.db import models
from app.db.crud import get_findings, get_scan_history, save_scan
from app.db.database import engine, get_db
from app.models.idleness import IdleState
from app.providers.aws.scanner import scan_aws

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


@app.get("/api/v1/findings")
def findings(
    state: Optional[list[IdleState]] = Query(default=None),
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
