import datetime as dt

from app.orchestration.forecast import CarbonForecaster, InsufficientHistory, to_hourly
from app.orchestration.models import ForecastSource, IntensityPoint
from tests.synthetic_grid import UTC, hourly, observed, truth

END = dt.datetime(2026, 10, 20, 12, 0, tzinfo=UTC)  # exclusive: last observed hour is 11:00
HIST = 21 * 24


def history(region="solar-west", hours=HIST):
    return hourly(region, END - dt.timedelta(hours=hours), hours)


def test_forecast_shape_and_start():
    fc = CarbonForecaster(lead_hours=48).fit(history())
    pts = fc.predict(48)
    assert len(pts) == 48 and pts[0].time == END and pts[-1].time == END + dt.timedelta(hours=47)
    assert all(p.g_co2_per_kwh >= 0 for p in pts)


def test_model_only_served_if_it_beats_seasonal_naive_on_holdout():
    r = CarbonForecaster().fit(history()).report
    if r.source is ForecastSource.MODEL:
        assert r.model_mae < r.naive_mae
    else:
        assert r.model_mae >= r.naive_mae
    assert r.history_hours == HIST and r.lead_hours == 48 and r.n_train > 0


def test_forecast_finds_the_solar_dip_and_tracks_truth():
    pts = CarbonForecaster().fit(history()).predict(48)
    day2 = pts[24:]  # second forecast day
    assert min(day2, key=lambda p: p.g_co2_per_kwh).time.hour in range(11, 16)
    mae = sum(abs(p.g_co2_per_kwh - truth("solar-west", p.time)) for p in pts) / len(pts)
    assert mae < 25.0, f"forecast MAE vs noise-free truth too high: {mae:.1f}"


def test_flat_region_has_flat_forecast():
    pts = CarbonForecaster().fit(history("steady-east")).predict(48)
    spread = max(p.g_co2_per_kwh for p in pts) - min(p.g_co2_per_kwh for p in pts)
    assert spread < 80


def test_horizon_beyond_lead_is_rejected():
    fc = CarbonForecaster(lead_hours=24).fit(history())
    try:
        fc.predict(25)
    except ValueError as exc:
        assert "lead time" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_too_little_history_is_rejected():
    try:
        CarbonForecaster().fit(history(hours=72))
    except InsufficientHistory:
        return
    raise AssertionError("expected InsufficientHistory")


def test_small_gaps_are_interpolated_large_gaps_rejected():
    pts = history()
    sparse = [p for i, p in enumerate(pts) if i % 20 != 5]  # 5 % missing
    rep = CarbonForecaster().fit(sparse).report
    assert rep.filled_hours > 0
    holey = [p for i, p in enumerate(pts) if i % 3 != 0]  # 33 % missing
    try:
        CarbonForecaster().fit(holey)
    except InsufficientHistory as exc:
        assert "missing" in str(exc)
        return
    raise AssertionError("expected InsufficientHistory")


def test_five_minute_points_are_averaged_per_hour():
    t0 = END - dt.timedelta(hours=2)
    pts = [IntensityPoint(time=t0 + dt.timedelta(minutes=5 * i), g_co2_per_kwh=100.0 if i < 12 else 200.0)
           for i in range(24)]
    first, y, filled = to_hourly(pts)
    assert first == t0 and list(y) == [100.0, 200.0] and filled == 0


def test_same_inputs_give_identical_forecasts():
    a = CarbonForecaster().fit(history()).predict(24)
    b = CarbonForecaster().fit(history()).predict(24)
    assert [p.g_co2_per_kwh for p in a] == [p.g_co2_per_kwh for p in b]
