import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[int] = mapped_column(Integer, default=0)
    stopped: Mapped[int] = mapped_column(Integer, default=0)
    idle: Mapped[int] = mapped_column(Integer, default=0)
    orphaned: Mapped[int] = mapped_column(Integer, default=0)
    exempt: Mapped[int] = mapped_column(Integer, default=0)
    unknown: Mapped[int] = mapped_column(Integer, default=0)
    monthly_waste_kwh: Mapped[float] = mapped_column(Float, default=0.0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    scanned_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    findings: Mapped[list["IdleFinding"]] = relationship(back_populates="scan")


class IdleFinding(Base):
    """One persisted IdlenessRecord (see app/models/idleness.py)."""

    __tablename__ = "idle_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String, nullable=False)

    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str | None] = mapped_column(String)
    provider_state: Mapped[str] = mapped_column(String)
    lifecycle: Mapped[str] = mapped_column(String)
    size_gb: Mapped[float | None] = mapped_column(Float)

    idle_state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String)
    exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    exemption_tag: Mapped[str | None] = mapped_column(String)

    cpu_average: Mapped[float | None] = mapped_column(Float)
    cpu_maximum: Mapped[float | None] = mapped_column(Float)
    network_mb_day: Mapped[float | None] = mapped_column(Float)
    telemetry_coverage: Mapped[float | None] = mapped_column(Float)

    p_idle_kw: Mapped[float | None] = mapped_column(Float)
    pue: Mapped[float | None] = mapped_column(Float)
    idle_hours_observed: Mapped[float | None] = mapped_column(Float)
    e_waste_kwh_observed: Mapped[float | None] = mapped_column(Float)
    e_waste_kwh_monthly: Mapped[float | None] = mapped_column(Float)

    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)

    scan: Mapped[ScanRun] = relationship(back_populates="findings")
