import datetime as dt

from app.orchestration.models import lbs_per_mwh_to_g_per_kwh
from app.orchestration.watttime import WattTimeProvider, coords_from_env
from app.providers.rest import RestError
from tests.fake_http import FakeResponse, rest_with

UTC = dt.timezone.utc
START = dt.datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
COORDS = {"us-east-1": (39.04, -77.49)}


def handler_factory(units="lbs_co2_per_mwh", value=1000.0):
    def handler(url, params):
        if url.endswith("/v3/region-from-loc"):
            return {"region": "PJM_DC", "signal_type": "co2_moer"}
        if url.endswith("/v3/data"):
            s = dt.datetime.fromisoformat(params["start"].replace("Z", "+00:00"))
            return {"meta": {"region": "PJM_DC", "signal_type": "co2_moer", "units": units},
                    "data": [{"point_time": (s + dt.timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "value": value if i != 3 else None} for i in range(24)]}
        raise AssertionError(url)
    return handler


def provider(**kw):
    rest, session = rest_with(handler_factory(**kw))
    return WattTimeProvider(rest, COORDS), session


def test_unit_conversion_and_null_points_skipped():
    p, _ = provider()
    pts = p.history("us-east-1", START, START + dt.timedelta(hours=2))
    assert len(pts) == 23  # one null dropped
    assert abs(pts[0].g_co2_per_kwh - lbs_per_mwh_to_g_per_kwh(1000.0)) < 1e-9
    assert abs(pts[0].g_co2_per_kwh - 453.59237) < 1e-6
    assert pts[0].time == START


def test_requests_carry_region_signal_and_window_and_region_lookup_is_cached():
    p, session = provider()
    p.history("us-east-1", START, START + dt.timedelta(hours=2))
    p.history("us-east-1", START, START + dt.timedelta(hours=2))
    lookups = [c for c in session.calls if c[0].endswith("region-from-loc")]
    data = [c for c in session.calls if c[0].endswith("/v3/data")]
    assert len(lookups) == 1 and lookups[0][1]["latitude"] == 39.04
    assert data[0][1]["region"] == "PJM_DC" and data[0][1]["signal_type"] == "co2_moer"
    assert data[0][1]["start"] == "2026-10-20T10:00:00Z" and data[0][1]["end"] == "2026-10-20T12:00:00Z"


def test_windows_over_32_days_are_chunked():
    p, session = provider()
    p.history("us-east-1", START, START + dt.timedelta(days=40))
    data = [c[1] for c in session.calls if c[0].endswith("/v3/data")]
    assert len(data) == 2 and data[0]["end"] == data[1]["start"]


def test_unexpected_units_are_rejected_not_guessed():
    p, _ = provider(units="g_co2_per_kwh")
    try:
        p.history("us-east-1", START, START + dt.timedelta(hours=1))
    except ValueError as exc:
        assert "units" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_unknown_cloud_region_is_a_clear_error():
    p, _ = provider()
    try:
        p.resolve_region("mars-1")
    except KeyError as exc:
        assert "GREENOPS_REGION_COORDS" in str(exc)
        return
    raise AssertionError("expected KeyError")


def test_plan_denied_region_propagates_as_rest_error():
    def handler(url, params):
        return {"region": "X"} if url.endswith("region-from-loc") else FakeResponse(403, {"error": "plan does not include region"})
    rest, _ = rest_with(handler)
    try:
        WattTimeProvider(rest, COORDS).history("us-east-1", START, START + dt.timedelta(hours=1))
    except RestError as exc:
        assert exc.status == 403
        return
    raise AssertionError("expected RestError")


def test_region_coordinate_override_from_env():
    c = coords_from_env({"GREENOPS_REGION_COORDS": '{"my-region": [1.5, 2.5]}'})
    assert c["my-region"] == (1.5, 2.5) and "us-east-1" in c
