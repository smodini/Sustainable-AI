from __future__ import annotations

import datetime as dt

from app.config import CarbonPolicy
from app.models.idleness import IdleState
from app.services.carbon_orchestrator import OrchestrationAction, plan_orchestration


def test_no_action_for_low_carbon_burden():
    policy = CarbonPolicy(notify_kg_co2e_monthly=10, scale_down_kg_co2e_monthly=25, migrate_kg_co2e_monthly=50, stop_kg_co2e_monthly=100)
    decision = plan_orchestration(
        [{
            "name": "dev-api-01",
            "region": "us-east-1",
            "carbon_intensity_gco2_kwh": 200,
            "e_waste_kwh_monthly": 10,
        }],
        policy=policy,
    )[0]
    assert decision.action is OrchestrationAction.NO_ACTION


def test_notify_owner_for_moderate_carbon_burden():
    policy = CarbonPolicy(notify_kg_co2e_monthly=10, scale_down_kg_co2e_monthly=25, migrate_kg_co2e_monthly=50, stop_kg_co2e_monthly=100)
    decision = plan_orchestration(
        [{
            "name": "analytics-01",
            "region": "us-east-1",
            "carbon_intensity_gco2_kwh": 500,
            "e_waste_kwh_monthly": 30,
        }],
        policy=policy,
    )[0]
    assert decision.action is OrchestrationAction.NOTIFY_OWNER


def test_migrate_for_high_carbon_burden():
    policy = CarbonPolicy(notify_kg_co2e_monthly=10, scale_down_kg_co2e_monthly=25, migrate_kg_co2e_monthly=50, stop_kg_co2e_monthly=100)
    decision = plan_orchestration(
        [{
            "name": "etl-01",
            "region": "us-central1",
            "carbon_intensity_gco2_kwh": 700,
            "e_waste_kwh_monthly": 90,
        }],
        policy=policy,
    )[0]
    assert decision.action is OrchestrationAction.MIGRATE
    assert decision.recommended_region == "us-east1"


def test_exempt_resources_skip_orchestration():
    policy = CarbonPolicy(notify_kg_co2e_monthly=10, scale_down_kg_co2e_monthly=25, migrate_kg_co2e_monthly=50, stop_kg_co2e_monthly=100)
    decision = plan_orchestration(
        [{
            "name": "dr-01",
            "region": "us-west-2",
            "carbon_intensity_gco2_kwh": 800,
            "e_waste_kwh_monthly": 200,
            "exempt": True,
        }],
        policy=policy,
    )[0]
    assert decision.action is OrchestrationAction.NO_ACTION
    assert decision.exempt is True


def test_stop_for_very_high_burden():
    policy = CarbonPolicy(notify_kg_co2e_monthly=10, scale_down_kg_co2e_monthly=25, migrate_kg_co2e_monthly=50, stop_kg_co2e_monthly=100)
    decision = plan_orchestration(
        [{
            "name": "batch-01",
            "region": "us-east-1",
            "carbon_intensity_gco2_kwh": 900,
            "e_waste_kwh_monthly": 200,
        }],
        policy=policy,
    )[0]
    assert decision.action is OrchestrationAction.STOP
