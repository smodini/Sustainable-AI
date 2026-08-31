from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from app.db.database import engine, get_db
from app.db import models
from app.db.crud import save_scan, get_findings, get_scan_history
from app.providers.aws.scanner import scan_aws

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="GreenOps Multi-Cloud Energy Waste Platform")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/aws/scan")
def aws_scan(db: Session = Depends(get_db)):
    result = scan_aws()
    save_scan(db, result)
    return result


@app.get("/api/v1/findings")
def findings(idle_only: bool = False, db: Session = Depends(get_db)):
    rows = get_findings(db, idle_only=idle_only)
    return [
        {
            "resource_id": r.resource_id,
            "name": r.name,
            "provider": r.provider,
            "region": r.region,
            "instance_type": r.instance_type,
            "cpu_maximum": r.cpu_maximum,
            "network_mb_day": r.network_mb_day,
            "idle": r.idle,
            "energy_waste_kwh": r.energy_waste_kwh,
            "risk": r.risk,
            "detected_at": r.detected_at,
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
            "total_vms": r.total_vms,
            "idle_vms": r.idle_vms,
            "total_waste_kwh": r.total_waste_kwh,
            "scanned_at": r.scanned_at,
        }
        for r in rows
    ]
