import datetime
from sqlalchemy import Column, String, Float, Boolean, Integer, DateTime, ForeignKey
from app.db.database import Base


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False)
    total_vms = Column(Integer, default=0)
    idle_vms = Column(Integer, default=0)
    total_waste_kwh = Column(Float, default=0.0)
    scanned_at = Column(DateTime, default=datetime.datetime.utcnow)


class IdleFinding(Base):
    __tablename__ = "idle_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("scan_runs.id"), nullable=False)
    provider = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    name = Column(String)
    region = Column(String)
    instance_type = Column(String)
    cpu_average = Column(Float, default=0.0)
    cpu_maximum = Column(Float, default=0.0)
    network_mb_day = Column(Float, default=0.0)
    idle = Column(Boolean, default=False)
    idle_hours = Column(Float, default=0.0)
    energy_waste_kwh = Column(Float, default=0.0)
    risk = Column(String, default="NONE")
    detected_at = Column(DateTime, default=datetime.datetime.utcnow)
