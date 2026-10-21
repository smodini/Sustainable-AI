"""Carbon-aware workload orchestration helpers.

This module implements the first executable orchestration layer for GreenOps:
policy-based decisioning for workloads that exceed acceptable carbon impact.

The logic intentionally sits between the detection layer (which produces idle
resource findings and carbon waste estimates) and the execution layer (which may
scale down, migrate, or stop workloads via cloud or Kubernetes APIs).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.config import carbon_policy


class OrchestrationAction(StrEnum):
    """Action to take when a resource's carbon burden exceeds policy thresholds."""

    NO_ACTION = "no_action"
    NOTIFY_OWNER = "notify_owner"
    SCALE_DOWN = "scale_down"
    MIGRATE = "migrate"
    STOP = "stop"


class CarbonOrchestrationPolicy(BaseModel):
    """Declarative thresholds for the orchestration layer."""

    model_config = ConfigDict(frozen=True)

    notify_kg_co2e_monthly: float = Field(default=20.0, gt=0)
    scale_down_kg_co2e_monthly: float = Field(default=50.0, gt=0)
    migrate_kg_co2e_monthly: float = Field(default=100.0, gt=0)
    stop_kg_co2e_monthly: float = Field(default=200.0, gt=0)
    high_carbon_intensity_gco2_kwh: float = Field(default=450.0, gt=0)
    preferred_regions: tuple[str, ...] = ("us-east1", "europe-west1", "us-central1")


class CarbonDecision(BaseModel):
    """One action recommendation for a resource or workload."""

    model_config = ConfigDict(frozen=True)

    resource_name: str = "unknown-resource"
    region: str | None = None
    carbon_intensity_gco2_kwh: float = Field(default=0.0, ge=0)
    estimated_kg_co2e_monthly: float = Field(default=0.0, ge=0)
    action: OrchestrationAction = OrchestrationAction.NO_ACTION
    reason: str = "resource is within configured carbon policy thresholds"
    recommended_region: str | None = None
    exempt: bool = False


class CarbonDecisionInput(BaseModel):
    """Simple request shape for orchestration evaluation."""

    model_config = ConfigDict(frozen=True)

    name: str = "unknown-resource"
    region: str | None = None
    carbon_intensity_gco2_kwh: float = Field(default=0.0, ge=0)
    e_waste_kwh_monthly: float | None = Field(default=None, ge=0)
    energy_waste_kwh_monthly: float | None = Field(default=None, ge=0)
    exempt: bool = False


def _as_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        if value is None:
            return 0.0
        raise ValueError(f"{field_name} must be numeric, got {value!r}") from None
    if number < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return number


def _resource_name_from_record(record: Mapping[str, Any]) -> str:
    for key in ("name", "resource_name", "resourceId", "resource_id"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return "unknown-resource"


def _region_from_record(record: Mapping[str, Any]) -> str | None:
    value = record.get("region") or record.get("location")
    return str(value) if value not in (None, "") else None


def _monthly_energy_kwh(record: Mapping[str, Any]) -> float:
    for key in ("e_waste_kwh_monthly", "energy_waste_kwh_monthly", "monthly_waste_kwh"):
        value = record.get(key)
        if value is not None:
            return _as_float(value, key)
    return 0.0


def _intensity_from_record(record: Mapping[str, Any]) -> float:
    for key in (
        "carbon_intensity_gco2_kwh",
        "carbon_intensity",
        "co2e_per_kwh",
        "gco2_per_kwh",
    ):
        value = record.get(key)
        if value is not None:
            return _as_float(value, key)
    return 0.0


def _choose_region(region: str | None, preferred_regions: Iterable[str]) -> str | None:
    preferred = tuple(r for r in preferred_regions if r and r != region)
    if preferred:
        return preferred[0]
    return None


def evaluate_carbon_action(
    resource_name: str,
    carbon_intensity_gco2_kwh: float,
    monthly_energy_waste_kwh: float,
    *,
    region: str | None = None,
    exempt: bool = False,
    policy: CarbonOrchestrationPolicy = CarbonOrchestrationPolicy(),
) -> CarbonDecision:
    """Return the action recommended for one workload or resource."""
    carbon_intensity = _as_float(carbon_intensity_gco2_kwh, "carbon_intensity_gco2_kwh")
    monthly_waste = _as_float(monthly_energy_waste_kwh, "monthly_energy_waste_kwh")
    estimated_kg = (monthly_waste * carbon_intensity) / 1000.0

    if exempt:
        return CarbonDecision(
            resource_name=resource_name,
            region=region,
            carbon_intensity_gco2_kwh=carbon_intensity,
            estimated_kg_co2e_monthly=estimated_kg,
            action=OrchestrationAction.NO_ACTION,
            reason="resource is exempt from carbon orchestration policies",
            recommended_region=None,
            exempt=True,
        )

    if estimated_kg >= policy.stop_kg_co2e_monthly:
        return CarbonDecision(
            resource_name=resource_name,
            region=region,
            carbon_intensity_gco2_kwh=carbon_intensity,
            estimated_kg_co2e_monthly=estimated_kg,
            action=OrchestrationAction.STOP,
            reason=(
                f"estimated carbon burden {estimated_kg:.2f} kg CO2e/month exceeds stop threshold "
                f"{policy.stop_kg_co2e_monthly:.2f} kg"
            ),
            recommended_region=_choose_region(region, policy.preferred_regions),
            exempt=False,
        )

    if estimated_kg >= policy.migrate_kg_co2e_monthly:
        return CarbonDecision(
            resource_name=resource_name,
            region=region,
            carbon_intensity_gco2_kwh=carbon_intensity,
            estimated_kg_co2e_monthly=estimated_kg,
            action=OrchestrationAction.MIGRATE,
            reason=(
                f"estimated carbon burden {estimated_kg:.2f} kg CO2e/month exceeds migrate threshold "
                f"{policy.migrate_kg_co2e_monthly:.2f} kg"
            ),
            recommended_region=_choose_region(region, policy.preferred_regions),
            exempt=False,
        )

    if estimated_kg >= policy.scale_down_kg_co2e_monthly or carbon_intensity >= policy.high_carbon_intensity_gco2_kwh:
        return CarbonDecision(
            resource_name=resource_name,
            region=region,
            carbon_intensity_gco2_kwh=carbon_intensity,
            estimated_kg_co2e_monthly=estimated_kg,
            action=OrchestrationAction.SCALE_DOWN,
            reason=(
                f"estimated carbon burden {estimated_kg:.2f} kg CO2e/month or intensity "
                f"{carbon_intensity:.1f} gCO2e/kWh requires reduction"
            ),
            recommended_region=_choose_region(region, policy.preferred_regions),
            exempt=False,
        )

    if estimated_kg >= policy.notify_kg_co2e_monthly:
        return CarbonDecision(
            resource_name=resource_name,
            region=region,
            carbon_intensity_gco2_kwh=carbon_intensity,
            estimated_kg_co2e_monthly=estimated_kg,
            action=OrchestrationAction.NOTIFY_OWNER,
            reason=(
                f"estimated carbon burden {estimated_kg:.2f} kg CO2e/month exceeds owner notification threshold "
                f"{policy.notify_kg_co2e_monthly:.2f} kg"
            ),
            recommended_region=None,
            exempt=False,
        )

    return CarbonDecision(
        resource_name=resource_name,
        region=region,
        carbon_intensity_gco2_kwh=carbon_intensity,
        estimated_kg_co2e_monthly=estimated_kg,
        action=OrchestrationAction.NO_ACTION,
        reason="resource remains below all carbon orchestration thresholds",
        recommended_region=None,
        exempt=False,
    )


def plan_orchestration(
    resources: Iterable[Mapping[str, Any] | CarbonDecisionInput],
    policy: CarbonOrchestrationPolicy = CarbonOrchestrationPolicy(),
) -> list[CarbonDecision]:
    """Evaluate a collection of resources and return the actions a control plane should take."""
    decisions: list[CarbonDecision] = []
    for resource in resources:
        if isinstance(resource, CarbonDecisionInput):
            record = resource.model_dump()
        elif isinstance(resource, Mapping):
            record = dict(resource)
        else:
            raise TypeError(f"Unsupported resource payload: {type(resource)!r}")

        name = _resource_name_from_record(record)
        region = _region_from_record(record)
        carbon_intensity = _intensity_from_record(record)
        monthly_kwh = _monthly_energy_kwh(record)
        exempt = bool(record.get("exempt") or record.get("is_exempt") or record.get("exemption"))
        decisions.append(
            evaluate_carbon_action(
                name,
                carbon_intensity,
                monthly_kwh,
                region=region,
                exempt=exempt,
                policy=policy,
            )
        )
    return decisions


default_orchestration_policy = CarbonOrchestrationPolicy()


# Compatibility: the application config also exposes a global carbon policy.
# Keep this value in sync with the service defaults.
carbon_orchestration_policy = CarbonOrchestrationPolicy(
    notify_kg_co2e_monthly=carbon_policy.notify_kg_co2e_monthly,
    scale_down_kg_co2e_monthly=carbon_policy.scale_down_kg_co2e_monthly,
    migrate_kg_co2e_monthly=carbon_policy.migrate_kg_co2e_monthly,
    stop_kg_co2e_monthly=carbon_policy.stop_kg_co2e_monthly,
    high_carbon_intensity_gco2_kwh=carbon_policy.high_carbon_intensity_gco2_kwh,
    preferred_regions=carbon_policy.preferred_regions,
)


__all__ = [
    "CarbonDecision",
    "CarbonDecisionInput",
    "CarbonOrchestrationPolicy",
    "OrchestrationAction",
    "carbon_orchestration_policy",
    "evaluate_carbon_action",
    "plan_orchestration",
]
