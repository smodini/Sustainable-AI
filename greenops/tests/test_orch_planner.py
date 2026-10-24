import datetime as dt

from app.orchestration.models import FlexibleWorkload, ForecastSource, IntensityPoint
from app.orchestration.planner import NoFeasiblePlacement, plan

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
NOW = T0 - dt.timedelta(minutes=30)
SRC = ForecastSource.MODEL


def series(values, start=T0):
    return [IntensityPoint(time=start + dt.timedelta(hours=i), g_co2_per_kwh=v) for i, v in enumerate(values)]


HOME = series([500] * 6 + [200] * 6 + [500] * 12)


def wl(**kw):
    base = dict(name="train", power_kw=1.0, duration_hours=2, earliest_start=NOW, deadline=T0 + dt.timedelta(hours=24),
                home_region="home", allowed_regions=("home", "other"))
    return FlexibleWorkload(**{**base, **kw})


def test_shifts_to_the_cheapest_window_with_exact_energy_math():
    p = plan(wl(allowed_regions=("home",)), {"home": HOME}, NOW, SRC, pue=1.5)
    assert p.start == T0 + dt.timedelta(hours=6) and p.region == "home"
    assert p.expected_avg_g_per_kwh == 200.0
    assert p.expected_kg_co2e == 0.6                       # 1 kW x 1.5 PUE x 2 h x 200 g / 1000
    assert p.baseline_kg_co2e == 1.5 and p.savings_kg_co2e == 0.9 and p.savings_pct == 60.0


def test_tight_deadline_forces_immediate_run_and_zero_savings():
    p = plan(wl(allowed_regions=("home",), deadline=T0 + dt.timedelta(hours=4)), {"home": HOME}, NOW, SRC, pue=1.5)
    assert p.start == T0 and p.savings_kg_co2e == 0.0


def test_region_shift_when_allowed_and_not_when_restricted():
    fc = {"home": HOME, "other": series([100] * 24)}
    assert plan(wl(), fc, NOW, SRC, pue=1.5).region == "other"
    assert plan(wl(), fc, NOW, SRC, pue=1.5).expected_kg_co2e == 0.3
    assert plan(wl(allowed_regions=("home",)), fc, NOW, SRC, pue=1.5).region == "home"  # data residency


def test_inflexible_workload_runs_now_in_home_region():
    fc = {"home": HOME, "other": series([100] * 24)}
    p = plan(wl(flexible=False), fc, NOW, SRC, pue=1.5)
    assert p.region == "home" and p.start == T0 and p.savings_kg_co2e == 0.0


def test_risk_margin_penalises_ranking_but_not_reported_numbers():
    fc = {"home": HOME, "other": series([100] * 24)}
    p = plan(wl(), fc, NOW, SRC, pue=1.5, risk_margin={"other": 4.0})  # 100*(1+4)=500 > home best 200
    assert p.region == "home"
    q = plan(wl(), fc, NOW, SRC, pue=1.5, risk_margin={"other": 0.5})   # 150 < 200: still wins
    assert q.region == "other" and q.expected_avg_g_per_kwh == 100.0    # un-inflated


def test_ties_prefer_earliest_start_then_home_region():
    flat = {"home": series([300] * 24), "other": series([300] * 24)}
    p = plan(wl(), flat, NOW, SRC, pue=1.5)
    assert p.start == T0 and p.region == "home"


def test_window_must_be_fully_covered_by_the_forecast():
    try:
        plan(wl(duration_hours=4, allowed_regions=("home",)), {"home": series([100] * 3)}, NOW, SRC)
    except NoFeasiblePlacement:
        return
    raise AssertionError("expected NoFeasiblePlacement")


def test_missing_home_forecast_is_infeasible():
    try:
        plan(wl(), {"other": series([100] * 24)}, NOW, SRC)
    except NoFeasiblePlacement as exc:
        assert "home region" in str(exc)
        return
    raise AssertionError("expected NoFeasiblePlacement")


def test_workload_validation():
    for bad in (dict(home_region="elsewhere"), dict(deadline=NOW + dt.timedelta(hours=1)),
                dict(earliest_start=dt.datetime(2026, 10, 21))):
        try:
            wl(**bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")
