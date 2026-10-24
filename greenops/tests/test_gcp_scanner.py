import datetime as dt

from app.config import IdlePolicy
from app.models.idleness import IdleState, Provider
from app.providers.gcp.scanner import instance_key, scan_gcp
from tests.conftest_helpers import NOW, OLD
from tests.fake_http import FakeResponse, rest_with

P = "proj-1"
HOURS = IdlePolicy().observation_days * 24
Z = "https://www.googleapis.com/compute/v1/projects/proj-1/zones/us-central1-a"


def inst(name, status="RUNNING", labels=None):
    return {"name": name, "zone": Z, "status": status, "machineType": f"{Z}/machineTypes/e2-medium",
            "creationTimestamp": OLD.isoformat(), "labels": labels or {}}


def series(metric, name, values, key="doubleValue", extra=None):
    return {"metric": {"type": metric, "labels": {"instance_name": name, **(extra or {})}},
            "resource": {"labels": {"zone": "us-central1-a"}},
            "points": [{"interval": {"endTime": f"t{i:04d}"}, "value": {key: v}} for i, v in enumerate(values)]}


CPU = "compute.googleapis.com/instance/cpu/utilization"
RX = "compute.googleapis.com/instance/network/received_bytes_count"
TX = "compute.googleapis.com/instance/network/sent_bytes_count"


def make_handler(telemetry_fail=False, extra_series=()):
    idle = lambda n: [0.01] * HOURS
    def handler(url, params):
        if url.endswith("/aggregated/instances"):
            return {"items": {"zones/us-central1-a": {"instances": [
                inst("idle"), inst("busy"), inst("nodata"), inst("off", "TERMINATED"),
                inst("exempt", labels={"hygiene-status": "exempt-from-hygiene"})]},
                "zones/europe-west1-b": {"warning": {"code": "NO_RESULTS_ON_PAGE"}}},
                "unreachables": ["zones/asia-east1-a"]}
        if url.endswith("/aggregated/disks"):
            return {"items": {"zones/us-central1-a": {"disks": [
                {"name": "orphan", "zone": Z, "status": "READY", "sizeGb": "50", "type": f"{Z}/diskTypes/pd-ssd",
                 "creationTimestamp": OLD.isoformat()},
                {"name": "attached", "zone": Z, "status": "READY", "users": [f"{Z}/instances/idle"]}]}}}
        if url.endswith("/timeSeries"):
            if telemetry_fail:
                return FakeResponse(403, {"error": "monitoring.viewer missing"})
            metric = params["filter"].split('"')[1]
            aligner = params["aggregation.perSeriesAligner"]
            out = []
            for n, cpu_mean, cpu_max in (("idle", 0.01, 0.02), ("busy", 0.02, 0.41), ("exempt", 0.0, 0.0)):
                if metric == CPU:
                    out.append(series(CPU, n, [cpu_mean if aligner == "ALIGN_MEAN" else cpu_max] * HOURS))
                else:  # two series per instance (loadbalanced true/false) must be summed
                    out.append(series(metric, n, [500] * HOURS, "int64Value", {"loadbalanced": "true"}))
                    out.append(series(metric, n, [500] * HOURS, "int64Value", {"loadbalanced": "false"}))
            out.extend(extra_series)
            return {"timeSeries": out}
        raise AssertionError(f"unexpected url {url}")
    return handler


def run(**kw):
    rest, session = rest_with(make_handler(**kw))
    summary = scan_gcp(projects=[P], now=NOW, rest_factory=lambda: rest)
    return summary, session, {r.identity.name: r for r in summary.records}


def test_end_to_end_mixed_estate():
    s, _, by = run()
    assert by["idle"].state is IdleState.IDLE and by["idle"].energy.e_waste_kwh_monthly == 108.0
    assert by["busy"].state is IdleState.ACTIVE            # peak CPU 41%
    assert by["nodata"].state is IdleState.UNKNOWN         # absent from every series: no data is not idle
    assert by["off"].state is IdleState.STOPPED            # TERMINATED
    assert by["exempt"].state is IdleState.EXEMPT
    assert by["orphan"].state is IdleState.ORPHANED and "attached" not in by
    assert s.provider is Provider.GCP and s.monthly_waste_kwh == 108.0


def test_network_series_are_summed_and_coverage_not_inflated():
    _, _, by = run()
    t = by["idle"].telemetry
    assert t.coverage == 1.0                                # duplicates never exceed distinct timestamps
    assert abs(t.network_mb_per_day - (HOURS * 2 * 1000 / 1048576 / 14)) < 1e-3  # 2 series x 2 dirs x 500 B
    assert abs(t.cpu_maximum - 2.0) < 1e-6                  # 0.02 fraction -> 2 %


def test_unreachable_zone_recorded_as_error():
    s, _, _ = run()
    assert any("asia-east1-a" in e for e in s.errors)


def test_only_four_project_wide_metric_queries_and_nothing_for_stopped_or_exempt_alone():
    _, session, _ = run()
    ts_calls = [c for c in session.calls if c[0].endswith("/timeSeries")]
    assert len(ts_calls) == 4


def test_monitoring_failure_leaves_vms_unknown_not_idle():
    s, _, by = run(telemetry_fail=True)
    assert by["idle"].state is IdleState.UNKNOWN and by["busy"].state is IdleState.UNKNOWN
    assert by["off"].state is IdleState.STOPPED and by["orphan"].state is IdleState.ORPHANED
    assert any("telemetry" in e for e in s.errors)


def test_project_failure_is_isolated():
    def handler(url, params):
        if "bad-proj" in url:
            return FakeResponse(403, {"error": "denied"})
        return make_handler()(url, params)
    rest, _ = rest_with(handler)
    s = scan_gcp(projects=["bad-proj", P], now=NOW, rest_factory=lambda: rest)
    assert s.total > 0 and any("bad-proj" in e for e in s.errors)


def test_no_projects_configured_is_a_clear_error():
    try:
        scan_gcp(projects=[], now=NOW, rest_factory=lambda: None)
    except ValueError as exc:
        assert "GREENOPS_GCP_PROJECTS" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_instance_key_parses_resource_id():
    assert instance_key("//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm-1") == ("us-central1-a", "vm-1")
