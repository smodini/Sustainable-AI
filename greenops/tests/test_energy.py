from decimal import Decimal

import pytest

from app.config import EnergyPolicy
from app.models.idleness import ResourceKind
from app.services.energy_calculator import (
    BASELINE_E_WASTE_KWH,
    calculate_energy_waste,
    compute_energy,
    e_waste_kwh,
)


def test_patent_baseline_is_exactly_108():
    # 0.10 kW x 1.50 PUE x 720 h
    assert e_waste_kwh("0.10", "1.50", 720) == Decimal("108.00")
    assert e_waste_kwh(0.10, 1.50, 720) == BASELINE_E_WASTE_KWH


def test_float_wrapper_matches_baseline_without_float_noise():
    assert calculate_energy_waste(720) == 108.0
    assert calculate_energy_waste() == 108.0


def test_100_hours_and_zero_hours():
    assert calculate_energy_waste(100) == 15.0
    assert calculate_energy_waste(0) == 0.0


def test_linear_in_each_term():
    assert e_waste_kwh(0.20, 1.50, 720) == Decimal("216.00")
    assert e_waste_kwh(0.10, 2.00, 720) == Decimal("144.00")
    assert e_waste_kwh(0.10, 1.50, 360) == Decimal("54.00")


def test_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        e_waste_kwh(-0.1, 1.5, 720)
    with pytest.raises(ValueError):
        e_waste_kwh(0.1, 0.99, 720)  # PUE < 1 is physically impossible
    with pytest.raises(ValueError):
        e_waste_kwh(0.1, 1.5, -1)
    with pytest.raises(ValueError):
        e_waste_kwh(float("nan"), 1.5, 720)
    with pytest.raises(ValueError):
        e_waste_kwh("abc", 1.5, 720)


def test_compute_energy_vm_reports_observed_and_monthly_baseline():
    e = compute_energy(ResourceKind.VM, idle_hours_observed=168)  # 7 days
    assert e is not None
    assert e.e_waste_kwh_monthly == 108.0  # patent baseline
    assert e.e_waste_kwh_observed == 25.2  # 0.10 x 1.50 x 168
    assert (e.p_idle_kw, e.pue) == (0.10, 1.50)


def test_compute_energy_undefined_for_kinds_without_p_idle():
    assert compute_energy(ResourceKind.DISK, 168) is None


def test_policy_override_changes_result():
    policy = EnergyPolicy(pue=1.2)
    assert compute_energy(ResourceKind.VM, 720, policy).e_waste_kwh_monthly == 86.4
