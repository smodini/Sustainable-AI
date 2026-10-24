import datetime as dt

from app.orchestration.controller import PlacementController
from app.orchestration.models import FlexibleWorkload, ForecastSource, PlacementStatus
from tests.synthetic_grid import UTC, SyntheticProvider, hourly, observed, truth

NOW = dt.datetime(2026, 10, 20, 20, 30, tzinfo=UTC)  # evening: the solar dip is ahead


def job(**kw):
    base = dict(name="train-1", power_kw=2.0, duration_hours=3, earliest_start=NOW, deadline=NOW + dt.timedelta(hours=30),
                home_region="steady-east", allowed_regions=("steady-east", "solar-west"))
    return FlexibleWorkload(**{**base, **kw})


def controller(**kw):
    return PlacementController(kw.pop("provider", SyntheticProvider()), pue=1.5, **kw)


def test_closed_loop_shifts_training_to_the_low_carbon_window_and_region():
    c = controller()
    [p] = c.reconcile([job()], NOW)
    assert p.region == "solar-west" and p.start.hour in (11, 12, 13)
    assert p.start >= NOW and p.end <= job().deadline
    assert p.savings_pct > 20 and p.forecast_source in (ForecastSource.MODEL, ForecastSource.SEASONAL_NAIVE)
    assert c.executor.applied == [p]


def test_reconcile_is_idempotent_no_thrash():
    c = controller()
    first = c.reconcile([job()], NOW)[0]
    again = c.reconcile([job()], NOW + dt.timedelta(minutes=10))[0]
    assert again == first and len(c.executor.applied) == 1


def test_started_placements_are_frozen():
    c = controller()
    p = c.reconcile([job()], NOW)[0]
    running = c.reconcile([job()], p.start + dt.timedelta(minutes=5))[0]
    assert running.status is PlacementStatus.RUNNING and running.start == p.start
    assert len(c.executor.applied) == 1


def test_observe_measures_realized_carbon_and_feeds_error_back():
    c = controller()
    p = c.reconcile([job()], NOW)[0]
    hours = int((p.end - p.start).total_seconds() // 3600)
    actual = hourly(p.region, p.start, hours, observed)
    out = c.observe("train-1", actual, power_kw=2.0)
    assert out.realized_kg_co2e > 0 and abs(out.error_pct) < 30 and out.region_mape_pct is not None
    assert c.placements["train-1"].status is PlacementStatus.COMPLETED
    small_margin = c.risk_margin(p.region)

    # a second job whose realized intensity is double the forecast: error is large, margin grows
    c2 = controller()
    p2 = c2.reconcile([job()], NOW)[0]
    bad = hourly(p2.region, p2.start, hours, lambda r, t: 2 * observed(r, t))
    out2 = c2.observe("train-1", bad, power_kw=2.0)
    assert out2.error_pct > 50 and c2.risk_margin(p2.region) > small_margin
    assert c2.risk_margin(p2.region) <= c2.max_risk_margin


def test_observe_requires_full_window_and_known_workload():
    c = controller()
    p = c.reconcile([job()], NOW)[0]
    for call in (lambda: c.observe("nope", [], 1.0), lambda: c.observe("train-1", [], 1.0)):
        try:
            call()
        except (KeyError, ValueError):
            continue
        raise AssertionError("expected error")


def test_region_without_usable_history_is_skipped_not_fatal():
    c = controller(provider=SyntheticProvider(broken={"solar-west"}))
    [p] = c.reconcile([job()], NOW)
    assert p.region == "steady-east"


def test_no_usable_history_anywhere_yields_no_placement_not_a_crash():
    c = controller(provider=SyntheticProvider(broken={"solar-west", "steady-east"}))
    assert c.reconcile([job()], NOW) == [] and c.placements == {}


def test_inflexible_job_is_not_shifted():
    c = controller()
    [p] = c.reconcile([job(flexible=False)], NOW)
    assert p.region == "steady-east" and p.savings_kg_co2e == 0.0


def test_forecasts_are_fetched_once_per_region_per_reconcile():
    prov = SyntheticProvider()
    c = controller(provider=prov)
    c.reconcile([job(name="a"), job(name="b")], NOW)
    assert sorted(r for r, _, _ in prov.calls) == ["solar-west", "steady-east"]
