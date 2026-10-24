"""Data shapes for carbon-aware placement. All timestamps are timezone-aware UTC."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# WattTime co2_moer is reported in lbs CO2 / MWh. 1 lb = 453.59237 g, 1 MWh = 1000 kWh.
G_PER_KWH_PER_LB_PER_MWH = 0.45359237


def lbs_per_mwh_to_g_per_kwh(value: float) -> float:
    return value * G_PER_KWH_PER_LB_PER_MWH


def floor_hour(t: dt.datetime) -> dt.datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def ceil_hour(t: dt.datetime) -> dt.datetime:
    f = floor_hour(t)
    return f if f == t else f + dt.timedelta(hours=1)


def _require_aware(t: dt.datetime, name: str) -> dt.datetime:
    if t.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (UTC)")
    return t.astimezone(dt.timezone.utc)


class IntensityPoint(BaseModel):
    """Marginal grid carbon intensity at one instant, in gCO2e per kWh."""

    model_config = ConfigDict(frozen=True)

    time: dt.datetime
    g_co2_per_kwh: float = Field(ge=0)

    @field_validator("time")
    @classmethod
    def _utc(cls, v: dt.datetime) -> dt.datetime:
        return _require_aware(v, "time")


class FlexibleWorkload(BaseModel):
    """A deferrable, relocatable job (e.g. model training) and its constraints.

    Energy follows the same shape as the detection layer's formula: the job draws
    ``power_kw`` of IT load for ``duration_hours`` and the facility adds PUE overhead,
    i.e. E = P x PUE x T (here P is active, not idle, power).
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    power_kw: float = Field(gt=0)
    duration_hours: int = Field(ge=1)
    earliest_start: dt.datetime
    deadline: dt.datetime  # the job must have FINISHED by this time
    home_region: str
    allowed_regions: tuple[str, ...] = Field(min_length=1)  # data-residency / capacity limits
    flexible: bool = True  # False: run immediately in home_region, never shifted

    @field_validator("earliest_start", "deadline")
    @classmethod
    def _utc(cls, v: dt.datetime) -> dt.datetime:
        return _require_aware(v, "timestamp")

    @model_validator(mode="after")
    def _check(self) -> "FlexibleWorkload":
        if self.home_region not in self.allowed_regions:
            raise ValueError("home_region must be one of allowed_regions")
        if self.deadline - self.earliest_start < dt.timedelta(hours=self.duration_hours):
            raise ValueError("deadline leaves no room for duration_hours after earliest_start")
        return self


class ForecastSource(StrEnum):
    MODEL = "model"  # scikit-learn model beat the baseline on held-out data
    SEASONAL_NAIVE = "seasonal_naive"  # same hour last week (model did not beat it)


class PlacementStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"


class Placement(BaseModel):
    """Where and when to run a workload, with the expected carbon benefit."""

    model_config = ConfigDict(frozen=True)

    workload: str
    region: str
    start: dt.datetime
    end: dt.datetime
    expected_avg_g_per_kwh: float
    expected_kg_co2e: float
    baseline_region: str
    baseline_start: dt.datetime
    baseline_kg_co2e: float  # run immediately in the home region
    savings_kg_co2e: float
    savings_pct: float
    forecast_source: ForecastSource
    decided_at: dt.datetime
    status: PlacementStatus = PlacementStatus.PLANNED
    reason: str = ""


class Outcome(BaseModel):
    """Result of the measure step of the loop: what actually happened vs. what was expected."""

    model_config = ConfigDict(frozen=True)

    workload: str
    region: str
    expected_kg_co2e: float
    realized_kg_co2e: float
    error_pct: float  # signed: (realized - expected) / expected * 100
    region_mape_pct: Optional[float] = None  # running forecast error for the region after this observation
