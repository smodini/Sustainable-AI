"""scikit-learn forecaster for hourly grid carbon intensity.

Direct multi-step design with a fixed lead time L (default 48 h): for a target hour t the
features use only information available L hours earlier, so every hour in the next L
hours is predicted in one shot with no error-compounding recursion:

    hour-of-day (sin, cos), day-of-week (sin, cos),
    y(t-L), y(t-168)  [same hour last week],  mean(y over the 24 h ending at t-L)

A gradient-boosted regressor is trained on the history. Honesty guard: on the most recent
``holdout_hours`` it must beat the seasonal-naive baseline (y(t-168)), otherwise the
baseline is what gets served and the report says so. The model never silently wins.
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from sklearn.ensemble import GradientBoostingRegressor

from app.orchestration.models import ForecastSource, IntensityPoint, floor_hour

WEEK = 168


class InsufficientHistory(ValueError):
    pass


class ForecastReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: ForecastSource
    model_mae: float  # g/kWh on the held-out tail
    naive_mae: float
    n_train: int
    lead_hours: int
    history_hours: int
    filled_hours: int  # hours interpolated across gaps in the input


def to_hourly(
    points: Sequence[IntensityPoint], max_missing_fraction: float = 0.1
) -> tuple[dt.datetime, np.ndarray, int]:
    """Mean per clock hour, gaps linearly interpolated.

    Returns (first_hour, values, filled_hours). WattTime emits ~5-minute points, so this is
    also the resampling step. Rejects input with more than ``max_missing_fraction`` of the
    span missing rather than forecasting from interpolated fiction.
    """
    if not points:
        raise InsufficientHistory("no intensity points")
    buckets: dict[dt.datetime, list[float]] = {}
    for p in points:
        buckets.setdefault(floor_hour(p.time), []).append(p.g_co2_per_kwh)
    first, last = min(buckets), max(buckets)
    n = int((last - first).total_seconds() // 3600) + 1
    y = np.full(n, np.nan)
    for hour, vals in buckets.items():
        y[int((hour - first).total_seconds() // 3600)] = float(np.mean(vals))
    missing = np.isnan(y)
    filled = int(missing.sum())
    if filled / n > max_missing_fraction:
        raise InsufficientHistory(f"{filled}/{n} hours missing (> {max_missing_fraction:.0%})")
    if filled:
        idx = np.arange(n)
        y[missing] = np.interp(idx[missing], idx[~missing], y[~missing])
    return first, y, filled


def _cyc(values: np.ndarray, period: float) -> tuple[np.ndarray, np.ndarray]:
    angle = 2 * np.pi * values / period
    return np.sin(angle), np.cos(angle)


class CarbonForecaster:
    def __init__(
        self,
        lead_hours: int = 48,
        holdout_hours: int = 72,
        random_state: int = 0,
        max_missing_fraction: float = 0.1,
    ):
        if not 1 <= lead_hours <= WEEK:
            raise ValueError("lead_hours must be in [1, 168]")
        self.lead = lead_hours
        self.holdout = holdout_hours
        self._seed = random_state
        self._max_missing = max_missing_fraction
        self._first: dt.datetime | None = None
        self._y: np.ndarray | None = None
        self._model: GradientBoostingRegressor | None = None
        self.report: ForecastReport | None = None

    # ---- features -------------------------------------------------------------------
    @property
    def _first_target(self) -> int:
        return max(WEEK, self.lead + 23)

    def _features(self, y: np.ndarray, first: dt.datetime, idx: np.ndarray) -> np.ndarray:
        hours = np.array([(first + dt.timedelta(hours=int(i))) for i in idx])
        hod = np.array([t.hour for t in hours], dtype=float)
        dow = np.array([t.weekday() for t in hours], dtype=float)
        hs, hc = _cyc(hod, 24)
        ds, dc = _cyc(dow, 7)
        lag_lead = y[idx - self.lead]
        lag_week = y[idx - WEEK]
        roll = np.array([y[i - self.lead - 23 : i - self.lead + 1].mean() for i in idx])
        return np.column_stack([hs, hc, ds, dc, lag_lead, lag_week, roll])

    def _new_model(self) -> GradientBoostingRegressor:
        return GradientBoostingRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=self._seed
        )

    # ---- fit / predict --------------------------------------------------------------
    def fit(self, history: Sequence[IntensityPoint]) -> "CarbonForecaster":
        first, y, filled = to_hourly(history, self._max_missing)
        n = len(y)
        need = self._first_target + self.holdout + 48
        if n < need:
            raise InsufficientHistory(f"need >= {need} hourly points of history, got {n}")
        idx_all = np.arange(self._first_target, n)
        idx_tr, idx_va = idx_all[idx_all < n - self.holdout], idx_all[idx_all >= n - self.holdout]

        x_tr, x_va = self._features(y, first, idx_tr), self._features(y, first, idx_va)
        trial = self._new_model().fit(x_tr, y[idx_tr])
        model_mae = float(np.mean(np.abs(trial.predict(x_va) - y[idx_va])))
        naive_mae = float(np.mean(np.abs(y[idx_va - WEEK] - y[idx_va])))
        use_model = model_mae < naive_mae

        self._model = (
            self._new_model().fit(self._features(y, first, idx_all), y[idx_all]) if use_model else None
        )
        self._first, self._y = first, y
        self.report = ForecastReport(
            source=ForecastSource.MODEL if use_model else ForecastSource.SEASONAL_NAIVE,
            model_mae=round(model_mae, 3),
            naive_mae=round(naive_mae, 3),
            n_train=len(idx_all),
            lead_hours=self.lead,
            history_hours=n,
            filled_hours=filled,
        )
        return self

    def predict(self, horizon_hours: int | None = None) -> list[IntensityPoint]:
        """Hourly forecast for the ``horizon_hours`` after the last observed hour."""
        if self._y is None or self._first is None or self.report is None:
            raise RuntimeError("fit() first")
        horizon = self.lead if horizon_hours is None else horizon_hours
        if not 1 <= horizon <= self.lead:
            raise ValueError(f"horizon_hours must be in [1, {self.lead}] (the model's lead time)")
        n = len(self._y)
        idx = np.arange(n, n + horizon)
        if self._model is not None:
            # Features for idx need y[idx-lead] and y[idx-168]: both <= n-1 since horizon <= lead <= 168.
            pred = self._model.predict(self._features(self._y, self._first, idx))
        else:
            pred = self._y[idx - WEEK]
        pred = np.clip(pred, 0.0, None)
        return [
            IntensityPoint(time=self._first + dt.timedelta(hours=int(i)), g_co2_per_kwh=float(v))
            for i, v in zip(idx, pred)
        ]
