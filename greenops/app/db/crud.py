import datetime
from sqlalchemy.orm import Session
from app.db.models import ScanRun, IdleFinding


def save_scan(db: Session, scan_result: dict) -> ScanRun:
    scan = ScanRun(
        provider=scan_result["provider"],
        total_vms=scan_result["total_vms"],
        idle_vms=scan_result["idle_vms"],
        total_waste_kwh=scan_result["estimated_monthly_waste_kwh"],
        scanned_at=datetime.datetime.utcnow(),
    )
    db.add(scan)
    db.flush()

    for resource in scan_result["resources"]:
        finding = IdleFinding(
            scan_id=scan.id,
            provider=scan_result["provider"],
            resource_id=resource["resource_id"],
            name=resource["name"],
            region=resource["region"],
            instance_type=resource["instance_type"],
            cpu_average=resource["cpu_average"],
            cpu_maximum=resource["cpu_maximum"],
            network_mb_day=resource["network_mb_day"],
            idle=resource["idle"],
            idle_hours=resource["idle_hours"],
            energy_waste_kwh=resource["energy_waste_kwh"],
            risk=resource["risk"],
        )
        db.add(finding)

    db.commit()
    db.refresh(scan)
    return scan


def get_findings(db: Session, idle_only: bool = False):
    query = db.query(IdleFinding)
    if idle_only:
        query = query.filter(IdleFinding.idle == True)
    return query.order_by(IdleFinding.detected_at.desc()).all()


def get_scan_history(db: Session):
    return db.query(ScanRun).order_by(ScanRun.scanned_at.desc()).all()
