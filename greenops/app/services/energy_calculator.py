"""Energy Waste core:  E_waste = P_idle x PUE x T

    P_idle  idle power draw (kW)
    PUE     Power Usage Effectiveness (>= 1.0)
    T       idle duration (hours)

Patent baseline: 0.10 kW x 1.50 x 720 h = 108 kWh per idle VM per month.

Arithmetic is done in ``Decimal`` so the baseline is exactly 108.00 rather than the
binary-float 108.00000000000001 that ``0.1 * 1.5 * 720`` yields; results are quantized
to 0.01 kWh (ROUND_HALF_UP) only at the boundary.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.config import EnergyPolicy, energy_policy
from app.models.idleness import EnergyWaste, ResourceKind

_CENT = Decimal("0.01")

# Patent baseline constants (kept as named values so tests and docs can cite them).
BASELINE_P_IDLE_KW = Decimal("0.10")
BASELINE_PUE = Decimal("1.50")
BASELINE_MONTHLY_HOURS = Decimal("720")
BASELINE_E_WASTE_KWH = Decimal("108.00")

# Backward-compatible module constants (floats) for existing imports.
IDLE_POWER_KW = float(BASELINE_P_IDLE_KW)
PUE = float(BASELINE_PUE)
MONTHLY_HOURS = float(BASELINE_MONTHLY_HOURS)


def _dec(value: float | int | str | Decimal, name: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except Exception as exc:  # decimal.InvalidOperation
        raise ValueError(f"{name} must be numeric, got {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"{name} must be finite, got {value!r}")
    return d


def e_waste_kwh(p_idle_kw: float | Decimal, pue: float | Decimal, hours: float | Decimal) -> Decimal:
    """E_waste = P_idle x PUE x T, in kWh, exact to 0.01.

    Raises ValueError for negative power or duration, or PUE below 1.0 (a data centre
    cannot draw less than its IT load).
    """
    p = _dec(p_idle_kw, "p_idle_kw")
    u = _dec(pue, "pue")
    t = _dec(hours, "hours")
    if p < 0:
        raise ValueError("p_idle_kw must be >= 0")
    if u < 1:
        raise ValueError("pue must be >= 1.0")
    if t < 0:
        raise ValueError("hours must be >= 0")
    return (p * u * t).quantize(_CENT, rounding=ROUND_HALF_UP)


def calculate_energy_waste(
    idle_hours: float = MONTHLY_HOURS,
    p_idle_kw: float = IDLE_POWER_KW,
    pue: float = PUE,
) -> float:
    """Backward-compatible float wrapper around :func:`e_waste_kwh`."""
    return float(e_waste_kwh(p_idle_kw, pue, idle_hours))


def compute_energy(
    kind: ResourceKind,
    idle_hours_observed: float,
    policy: EnergyPolicy = energy_policy,
) -> EnergyWaste | None:
    """Energy record for one idle resource, or None if the kind has no defined P_idle."""
    p_idle = policy.p_idle_kw_by_kind.get(kind)
    if p_idle is None:
        return None
    return EnergyWaste(
        p_idle_kw=p_idle,
        pue=policy.pue,
        idle_hours_observed=idle_hours_observed,
        e_waste_kwh_observed=float(e_waste_kwh(p_idle, policy.pue, idle_hours_observed)),
        e_waste_kwh_monthly=float(e_waste_kwh(p_idle, policy.pue, policy.monthly_hours)),
    )
