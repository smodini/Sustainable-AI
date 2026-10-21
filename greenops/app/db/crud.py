from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IdleFinding, ScanRun
from app.models.idleness import IdleState, IdlenessRecord, ScanSummary


def _finding_from_record(scan_id: int, r: IdlenessRecord) -> IdleFinding:
    ident, t, e = r.identity, r.telemetry, r.energy
    return IdleFinding(
        scan_id=scan_id,
        schema_version=r.schema_version,
        provider=ident.provider.value,
        account_id=ident.account_id,
        resource_id=ident.resource_id,
        resource_kind=ident.kind.value,
        name=ident.name,
        region=ident.region,
        resource_type=ident.resource_type,
        provider_state=ident.provider_state,
        lifecycle=ident.lifecycle.value,
        size_gb=ident.size_gb,
        idle_state=r.state.value,
        reason=r.reason,
        exempt=r.exemption.exempt,
        exemption_tag=(
            f"{r.exemption.tag_key}={r.exemption.tag_value}" if r.exemption.exempt else None
        ),
        cpu_average=t.cpu_average if t else None,
        cpu_maximum=t.cpu_maximum if t else None,
        network_mb_day=t.network_mb_per_day if t else None,
        telemetry_coverage=t.coverage if t else None,
        p_idle_kw=e.p_idle_kw if e else None,
        pue=e.pue if e else None,
        idle_hours_observed=e.idle_hours_observed if e else None,
        e_waste_kwh_observed=e.e_waste_kwh_observed if e else None,
        e_waste_kwh_monthly=e.e_waste_kwh_monthly if e else None,
        evaluated_at=r.evaluated_at,
    )


def save_scan(db: Session, summary: ScanSummary) -> ScanRun:
    """Persist a scan atomically: the run row and all findings commit together or not at all."""
    scan = ScanRun(
        provider=summary.provider.value,
        total=summary.total,
        active=summary.active,
        stopped=summary.stopped,
        idle=summary.idle,
        orphaned=summary.orphaned,
        exempt=summary.exempt,
        unknown=summary.unknown,
        monthly_waste_kwh=summary.monthly_waste_kwh,
        errors=summary.errors,
        scanned_at=summary.scanned_at,
    )
    try:
        db.add(scan)
        db.flush()
        db.add_all(_finding_from_record(scan.id, r) for r in summary.records)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return scan


def get_findings(
    db: Session,
    states: Optional[list[IdleState]] = None,
    limit: int = 1000,
) -> list[IdleFinding]:
    stmt = select(IdleFinding).order_by(IdleFinding.evaluated_at.desc()).limit(limit)
    if states:
        stmt = stmt.where(IdleFinding.idle_state.in_([s.value for s in states]))
    return list(db.scalars(stmt))


def get_scan_history(db: Session, limit: int = 100) -> list[ScanRun]:
    return list(db.scalars(select(ScanRun).order_by(ScanRun.scanned_at.desc()).limit(limit)))
