import datetime as dt

from app.config import IdlePolicy
from app.models.idleness import IdleState, Provider
from app.providers.aws.metrics import INSTANCES_PER_CALL, fetch_ec2_telemetry
from app.providers.aws.scanner import scan_aws
from tests.conftest_helpers import NOW, OLD, WINDOW_END, WINDOW_START

HOURS = IdlePolicy().observation_days * 24  # default 14-day window, hourly buckets


def instance(iid, state="running", tags=None, launch=OLD):
    return {"InstanceId": iid, "InstanceType": "t3.medium", "State": {"Name": state}, "LaunchTime": launch,
            "Tags": [{"Key": k, "Value": v} for k, v in (tags or {}).items()]}


class FakePaginator:
    def __init__(self, pages): self.pages = pages
    def paginate(self, **_): return iter(self.pages)


class FakeEC2:
    def __init__(self, instances=(), volumes=()):
        self.instances, self.volumes = list(instances), list(volumes)
    def get_paginator(self, name):
        if name == "describe_instances":
            return FakePaginator([{"Reservations": [{"Instances": self.instances}]}])
        return FakePaginator([{"Volumes": self.volumes}])


class FakeCW:
    """Answers GetMetricData from per-instance series; optionally splits across two pages."""
    KEYS = {"CPUUtilization": {"Average": "cpu_avg", "Maximum": "cpu_max"},
            "NetworkIn": {"Sum": "net_in"}, "NetworkOut": {"Sum": "net_out"}}

    def __init__(self, series, paged=False):
        self.series, self.paged, self.calls = series, paged, []

    def get_metric_data(self, **kw):
        self.calls.append(kw)
        second = "NextToken" in kw
        results = []
        for q in kw["MetricDataQueries"]:
            m = q["MetricStat"]["Metric"]
            iid = m["Dimensions"][0]["Value"]
            vals = self.series.get(iid, {}).get(self.KEYS[m["MetricName"]][q["MetricStat"]["Stat"]], [])
            if self.paged:
                half = len(vals) // 2
                vals = vals[half:] if second else vals[:half]
            results.append({"Id": q["Id"], "Values": vals, "StatusCode": "PartialData" if self.paged and not second else "Complete"})
        out = {"MetricDataResults": results}
        if self.paged and not second:
            out["NextToken"] = "page2"
        return out


def idle_series(): return {"cpu_avg": [1.0] * HOURS, "cpu_max": [2.0] * HOURS, "net_in": [1000.0] * HOURS, "net_out": [1000.0] * HOURS}
def busy_series(): return {**idle_series(), "cpu_max": [2.0] * (HOURS - 1) + [41.0]}


def run(ec2, cw, **kw):
    return scan_aws(account_id="123456789012", regions=["us-east-1"], now=NOW,
                    ec2_factory=lambda r: ec2, cw_factory=lambda r: cw, **kw)


def test_end_to_end_mixed_estate():
    ec2 = FakeEC2(
        instances=[instance("i-idle"), instance("i-busy"), instance("i-nodata"), instance("i-off", "stopped"),
                   instance("i-exempt", tags={"hygiene-status": "exempt-from-hygiene"})],
        volumes=[{"VolumeId": "vol-1", "State": "available", "Attachments": [], "Size": 50, "VolumeType": "gp3"}])
    cw = FakeCW({"i-idle": idle_series(), "i-busy": busy_series(), "i-exempt": idle_series()})
    s = run(ec2, cw)
    by = {r.identity.resource_id.rsplit("/", 1)[-1]: r for r in s.records}

    assert by["i-idle"].state is IdleState.IDLE and by["i-idle"].energy.e_waste_kwh_monthly == 108.0
    assert by["i-busy"].state is IdleState.ACTIVE
    assert by["i-nodata"].state is IdleState.UNKNOWN          # no data is not idle
    assert by["i-off"].state is IdleState.STOPPED
    assert by["i-exempt"].state is IdleState.EXEMPT           # reported, not silently dropped
    assert by["vol-1"].state is IdleState.ORPHANED
    assert (s.total, s.idle, s.orphaned, s.exempt, s.unknown, s.stopped, s.active) == (6, 1, 1, 1, 1, 1, 1)
    assert s.monthly_waste_kwh == 108.0 and s.provider is Provider.AWS and s.errors == []


def test_exempt_and_stopped_instances_are_never_queried():
    ec2 = FakeEC2(instances=[instance("i-idle"), instance("i-off", "stopped"), instance("i-exempt", tags={"hygiene-status": "exempt-from-hygiene"})])
    cw = FakeCW({"i-idle": idle_series()})
    run(ec2, cw)
    queried = {q["MetricStat"]["Metric"]["Dimensions"][0]["Value"] for c in cw.calls for q in c["MetricDataQueries"]}
    assert queried == {"i-idle"}


def test_network_is_summed_across_all_datapoints_and_paginated():
    ec2 = FakeEC2(instances=[instance("i-idle")])
    paged = run(ec2, FakeCW({"i-idle": idle_series()}, paged=True))
    plain = run(ec2, FakeCW({"i-idle": idle_series()}))
    p, q = paged.records[0].telemetry, plain.records[0].telemetry
    assert p.network_mb_per_day == q.network_mb_per_day
    assert p.coverage == q.coverage == 1.0
    # HOURS x (1000 in + 1000 out) bytes over the observation window
    assert abs(q.network_mb_per_day - (HOURS * 2000 / 1048576 / (HOURS / 24))) < 1e-3


def test_batching_respects_500_query_limit():
    ids = [f"i-{n:03d}" for n in range(130)]
    cw = FakeCW({i: idle_series() for i in ids})
    out = fetch_ec2_telemetry(cw, [(i, OLD) for i in ids], WINDOW_START, WINDOW_END)
    assert len(out) == 130 and len(cw.calls) == 2
    assert all(len(c["MetricDataQueries"]) <= 500 for c in cw.calls)
    assert len(cw.calls[0]["MetricDataQueries"]) == INSTANCES_PER_CALL * 4


def test_sparse_telemetry_becomes_unknown_not_idle():
    sparse = {k: v[:40] for k, v in idle_series().items()}  # ~24% coverage
    s = run(FakeEC2(instances=[instance("i-sparse")]), FakeCW({"i-sparse": sparse}))
    assert s.records[0].state is IdleState.UNKNOWN


def test_brand_new_instance_is_judged_on_its_own_lifetime():
    launched = WINDOW_END - dt.timedelta(hours=48)
    series = {k: v[:48] for k, v in idle_series().items()}
    s = run(FakeEC2(instances=[instance("i-new", launch=launched)]), FakeCW({"i-new": series}))
    r = s.records[0]
    assert r.state is IdleState.IDLE and r.energy.idle_hours_observed == 48.0


def test_failed_region_is_reported_not_swallowed():
    def bad_ec2(region):
        raise RuntimeError("AccessDenied by SCP")
    s = scan_aws(account_id="1", regions=["me-south-1"], now=NOW, ec2_factory=bad_ec2, cw_factory=lambda r: None)
    assert s.total == 0 and len(s.errors) == 1 and "me-south-1" in s.errors[0]


def test_policy_thresholds_are_honoured():
    ec2 = FakeEC2(instances=[instance("i-idle")])
    s = run(ec2, FakeCW({"i-idle": idle_series()}), policy=IdlePolicy(cpu_threshold_pct=1.5))
    assert s.records[0].state is IdleState.ACTIVE  # peak CPU 2.0% >= 1.5%
