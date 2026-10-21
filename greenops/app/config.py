"""Single source of truth for detection and energy policy.

Previously the thresholds were duplicated here and in ``idle_detector.py`` (and this
policy object was never read). Everything now flows from these two frozen models.
Override at runtime with GREENOPS_* environment variables via ``load_policies()``.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from app.models.idleness import ResourceKind


class EnergyPolicy(BaseModel):
    """Parameters of E_waste = P_idle x PUE x T.

    Defaults reproduce the patent baseline: 0.10 kW x 1.50 x 720 h = 108 kWh / VM / month.
    A kind with no entry in ``p_idle_kw_by_kind`` has no defined idle power draw, so its
    energy is left unset rather than reported as a fabricated number.
    """

    model_config = ConfigDict(frozen=True)

    p_idle_kw_by_kind: dict[ResourceKind, float] = Field(
        default_factory=lambda: {ResourceKind.VM: 0.10}
    )
    pue: float = Field(default=1.50, ge=1.0)
    monthly_hours: float = Field(default=720.0, gt=0)


class IdlePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    cpu_threshold_pct: float = Field(default=5.0, gt=0, le=100)
    network_threshold_mb_day: float = Field(default=5.0, gt=0)
    # Article: 14-day rolling window. Hourly datapoints (period 3600) are retained far
    # longer than 14 days on all three providers, so the cap is a policy limit, not an API one.
    observation_days: int = Field(default=14, ge=1, le=14)
    # Minimum fraction of expected datapoints before a verdict is trusted. Below this the
    # resource is UNKNOWN, never IDLE.
    min_coverage: float = Field(default=0.80, gt=0, le=1)
    # User-defined exemption tags as (key, value) pairs: a resource carrying any pair is
    # EXEMPT at every escalation stage. Matching is case-insensitive and ignores
    # surrounding whitespace. Default is the article's override tag.
    exemption_tags: tuple[tuple[str, str], ...] = (("hygiene-status", "exempt-from-hygiene"),)


class EscalationPolicy(BaseModel):
    """14-day graduated escalation (article, section vi). Consumed by the enforcement layer.

    Days are counted from the first IDLE/ORPHANED verdict. An exemption tag cancels the
    sequence at any stage.
    """

    model_config = ConfigDict(frozen=True)

    notice_day: int = Field(default=0, ge=0)  # informational alert to owner
    warning_day: int = Field(default=3, ge=0)  # warning: resource will be stopped
    stop_snapshot_day: int = Field(default=7, ge=0)  # resource stopped, snapshot preserved
    delete_day: int = Field(default=14, ge=0)  # resource and snapshot deleted
    snapshot_retention_days: int = Field(default=7, ge=0)


def load_policies(env: dict[str, str] | None = None) -> tuple[IdlePolicy, EnergyPolicy]:
    env = dict(os.environ) if env is None else env

    idle_kwargs: dict[str, object] = {}
    if "GREENOPS_CPU_THRESHOLD_PCT" in env:
        idle_kwargs["cpu_threshold_pct"] = float(env["GREENOPS_CPU_THRESHOLD_PCT"])
    if "GREENOPS_NETWORK_THRESHOLD_MB_DAY" in env:
        idle_kwargs["network_threshold_mb_day"] = float(env["GREENOPS_NETWORK_THRESHOLD_MB_DAY"])
    if "GREENOPS_OBSERVATION_DAYS" in env:
        idle_kwargs["observation_days"] = int(env["GREENOPS_OBSERVATION_DAYS"])
    if "GREENOPS_MIN_COVERAGE" in env:
        idle_kwargs["min_coverage"] = float(env["GREENOPS_MIN_COVERAGE"])
    if "GREENOPS_EXEMPTION_TAGS" in env:  # "key=value,key2=value2"
        pairs = []
        for item in env["GREENOPS_EXEMPTION_TAGS"].split(","):
            key, sep, value = item.partition("=")
            if item.strip() and (not sep or not key.strip() or not value.strip()):
                raise ValueError(f"GREENOPS_EXEMPTION_TAGS entry {item!r} must be key=value")
            if sep:
                pairs.append((key.strip(), value.strip()))
        idle_kwargs["exemption_tags"] = tuple(pairs)

    energy_kwargs: dict[str, object] = {}
    if "GREENOPS_PUE" in env:
        energy_kwargs["pue"] = float(env["GREENOPS_PUE"])
    if "GREENOPS_P_IDLE_KW_VM" in env:
        energy_kwargs["p_idle_kw_by_kind"] = {ResourceKind.VM: float(env["GREENOPS_P_IDLE_KW_VM"])}

    return IdlePolicy(**idle_kwargs), EnergyPolicy(**energy_kwargs)


idle_policy, energy_policy = load_policies()
