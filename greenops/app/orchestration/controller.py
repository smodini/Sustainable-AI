"""Closed-loop placement controller.

    observe grid -> forecast -> plan -> (act) -> measure realized carbon -> feed error back

``reconcile`` is idempotent and safe to call on a timer: it refreshes forecasts, re-plans
every not-yet-started workload, and only *moves* an existing plan when that is worth it
(hysteresis), so a noisy forecast does not make jobs thrash between windows. ``observe``
closes the loop: realized vs. expected carbon updates a per-region forecast-error tracker
(MAPE) which then inflates that region's risk margin in future ranking.

The controller decides; an ``Executor`` acts. The default executor only records, the
Kubernetes controller (Go) is the intended real one.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict, deque
from typing import Callable, Optional, Protocol, Sequence

from app.config import energy_policy
from app.orchestration.forecast import CarbonForecaster, InsufficientHistory
from app.orchestration.models import (
    FlexibleWorkload,
    ForecastSource,
    IntensityPoint,
    Outcome,
    Placement,
    PlacementStatus,
    floor_hour,
)
from app.orchestration.planner import NoFeasiblePlacement, emissions_kg, plan

log = logging.getLogger(__name__)


class IntensityProvider(Protocol):
    def history(self, region: str, start: dt.datetime, end: dt.datetime) -> Sequence[IntensityPoint]: ...


class Executor(Protocol):
    def apply(self, placement: Placement) -> None: ...


class RecordingExecutor:
    """Default executor: remembers what it was asked to do (no side effects)."""

    def __init__(self) -> None:
        self.applied: list[Placement] = []

    def apply(self, placement: Placement) -> None:
        self.applied.append(placement)


class PlacementController:
    def __init__(
        self,
        provider: IntensityProvider,
        *,
        executor: Optional[Executor] = None,
        pue: float = energy_policy.pue,
        history_days: int = 21,
        lead_hours: int = 48,
        min_improvement_pct: float = 5.0,
        max_risk_margin: float = 0.5,
        mape_window: int = 20,
        forecaster_factory: Optional[Callable[[], CarbonForecaster]] = None,
    ):
        self.provider, self.executor, self.pue = provider, executor or RecordingExecutor(), pue
        self.history_days, self.lead = history_days, lead_hours
        self.min_improvement_pct, self.max_risk_margin = min_improvement_pct, max_risk_margin
        self._factory = forecaster_factory or (lambda: CarbonForecaster(lead_hours=lead_hours))
        self.placements: dict[str, Placement] = {}
        self._mape: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=mape_window))

    # ---- feedback -----------------------------------------------------------------------
    def risk_margin(self, region: str) -> float:
        errs = self._mape[region]
        return min(sum(errs) / len(errs) / 100.0, self.max_risk_margin) if errs else 0.0

    # ---- forecast -----------------------------------------------------------------------
    def _forecast(self, region: str, now: dt.datetime) -> tuple[list[IntensityPoint], ForecastSource]:
        end = floor_hour(now)
        history = self.provider.history(region, end - dt.timedelta(days=self.history_days), end)
        fc = self._factory().fit(history)
        assert fc.report is not None
        return fc.predict(self.lead), fc.report.source

    # ---- decide ---------------------------------------------------------------------------
    def reconcile(self, workloads: Sequence[FlexibleWorkload], now: dt.datetime) -> list[Placement]:
        """Plan (or re-plan) every workload that has not started. Returns current placements."""
        cache: dict[str, tuple[list[IntensityPoint], ForecastSource]] = {}
        out: list[Placement] = []
        for w in workloads:
            current = self.placements.get(w.name)
            if current is not None and current.status is not PlacementStatus.PLANNED:
                out.append(current)  # started/finished plans are frozen
                continue
            if current is not None and current.start <= now:
                current = self.placements[w.name] = current.model_copy(update={"status": PlacementStatus.RUNNING})
                out.append(current)
                continue
            regions = w.allowed_regions if w.flexible else (w.home_region,)
            try:
                forecasts: dict[str, list[IntensityPoint]] = {}
                sources: list[ForecastSource] = []
                for r in regions:
                    if r not in cache:
                        try:
                            cache[r] = self._forecast(r, now)
                        except InsufficientHistory as exc:
                            log.warning("no usable history for %s: %s", r, exc)
                            continue
                    forecasts[r], src = cache[r]
                    sources.append(src)
                if not forecasts:
                    raise NoFeasiblePlacement(f"{w.name}: no region has usable intensity history")
                source = ForecastSource.MODEL if ForecastSource.MODEL in sources else ForecastSource.SEASONAL_NAIVE
                margins = {r: self.risk_margin(r) for r in forecasts}
                candidate = plan(w, forecasts, now, source, pue=self.pue, risk_margin=margins)
            except NoFeasiblePlacement as exc:
                log.warning("%s", exc)
                if current is not None:
                    out.append(current)  # keep what we had
                continue

            if current is not None and not self._worth_moving(current, candidate, w, now):
                out.append(current)
                continue
            self.placements[w.name] = candidate
            self.executor.apply(candidate)
            out.append(candidate)
        return out

    def _worth_moving(self, current: Placement, candidate: Placement, w: FlexibleWorkload, now: dt.datetime) -> bool:
        """Hysteresis: replace a still-feasible plan only for a material improvement."""
        if current.start < max(now, w.earliest_start):  # window already (partly) in the past
            return True
        if current.end > w.deadline:
            return True
        improvement = (
            100.0 * (current.expected_kg_co2e - candidate.expected_kg_co2e) / current.expected_kg_co2e
            if current.expected_kg_co2e > 0
            else 0.0
        )
        return improvement >= self.min_improvement_pct

    # ---- measure --------------------------------------------------------------------------
    def observe(self, workload: str, actual: Sequence[IntensityPoint], power_kw: float) -> Outcome:
        """Feed back the realized intensity over the job's window (covering its full duration)."""
        placement = self.placements.get(workload)
        if placement is None:
            raise KeyError(f"unknown workload {workload!r}")
        hours = int((placement.end - placement.start).total_seconds() // 3600)
        window = [p for p in actual if placement.start <= p.time < placement.end]
        if len(window) < hours:
            raise ValueError(f"need {hours} hourly points covering the run, got {len(window)}")
        realized_avg = sum(p.g_co2_per_kwh for p in window) / len(window)
        realized = emissions_kg(power_kw, self.pue, hours, realized_avg)
        expected = placement.expected_kg_co2e
        err = 100.0 * (realized - expected) / expected if expected > 0 else 0.0
        self._mape[placement.region].append(abs(err))
        errs = self._mape[placement.region]
        self.placements[workload] = placement.model_copy(update={"status": PlacementStatus.COMPLETED})
        return Outcome(
            workload=workload,
            region=placement.region,
            expected_kg_co2e=expected,
            realized_kg_co2e=round(realized, 4),
            error_pct=round(err, 2),
            region_mape_pct=round(sum(errs) / len(errs), 2),
        )
