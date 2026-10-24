from app.config import IdlePolicy
from app.models.idleness import IdleState, Provider
from app.providers.azure.scanner import scan_azure
from tests.conftest_helpers import NOW, OLD
from tests.fake_http import FakeResponse, rest_with

SUB = "00000000-0000-0000-0000-000000000001"
HOURS = IdlePolicy().observation_days * 24
BASE = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute"


def vm(name, power="PowerState/running", tags=None):
    return {"id": f"{BASE}/virtualMachines/{name}", "name": name, "location": "eastus", "tags": tags or {},
            "properties": {"hardwareProfile": {"vmSize": "Standard_B2s"}, "timeCreated": OLD.isoformat(),
                           "instanceView": {"statuses": [{"code": "ProvisioningState/succeeded"}, {"code": power}]}}}


def metric_resp(cpu_avg, cpu_max, net, points=HOURS):
    def rows(**kv): return [{"timeStamp": f"t{i}", **kv} for i in range(points)]
    return {"value": [
        {"name": {"value": "Percentage CPU"}, "timeseries": [{"data": rows(average=cpu_avg, maximum=cpu_max)}]},
        {"name": {"value": "Network In Total"}, "timeseries": [{"data": rows(total=net)}]},
        {"name": {"value": "Network Out Total"}, "timeseries": [{"data": rows(total=net)}]}]}


METRICS = {"idle": metric_resp(1.0, 2.0, 1000), "busy": metric_resp(3.0, 60.0, 1000),
           "sparse": metric_resp(1.0, 2.0, 1000, points=40)}


def vm_name(url):
    """VM name from a metrics URL; ARM ids are lowercased by the normalizer."""
    return url.lower().split("/virtualmachines/")[1].split("/")[0]


def make_handler(fail_for=()):
    def handler(url, params):
        if url.endswith("/virtualMachines"):
            return {"value": [vm("idle"), vm("busy")], "nextLink": "https://management.azure.com/page2"}
        if url == "https://management.azure.com/page2":
            return {"value": [vm("sparse"), vm("off", "PowerState/deallocated"),
                              vm("exempt", tags={"hygiene-status": "exempt-from-hygiene"})]}
        if url.endswith("/disks"):
            return {"value": [
                {"id": f"{BASE}/disks/orphan", "name": "orphan", "location": "eastus",
                 "properties": {"diskState": "Unattached", "diskSizeGB": 64}},
                {"id": f"{BASE}/disks/inuse", "name": "inuse", "location": "eastus", "managedBy": "x",
                 "properties": {"diskState": "Attached"}}]}
        if url.endswith("/providers/microsoft.insights/metrics"):
            name = vm_name(url)
            if name in fail_for:
                return FakeResponse(500, {"error": "boom"})
            return METRICS[name]
        raise AssertionError(f"unexpected url {url}")
    return handler


def run(**kw):
    rest, session = rest_with(make_handler(**kw), max_attempts=1)
    s = scan_azure(subscriptions=[SUB], now=NOW, rest_factory=lambda: rest)
    return s, session, {r.identity.name: r for r in s.records}


def test_end_to_end_mixed_estate_follows_next_link():
    s, _, by = run()
    assert by["idle"].state is IdleState.IDLE and by["idle"].energy.e_waste_kwh_monthly == 108.0
    assert by["busy"].state is IdleState.ACTIVE
    assert by["sparse"].state is IdleState.UNKNOWN          # ~12% coverage
    assert by["off"].state is IdleState.STOPPED             # deallocated
    assert by["exempt"].state is IdleState.EXEMPT
    assert by["orphan"].state is IdleState.ORPHANED and "inuse" not in by
    assert s.provider is Provider.AZURE and s.errors == []


def test_exempt_and_stopped_vms_are_never_queried():
    _, session, _ = run()
    queried = {vm_name(c[0]) for c in session.calls if "insights/metrics" in c[0]}
    assert queried == {"idle", "busy", "sparse"}


def test_one_vm_metrics_failure_isolated_and_reported():
    s, _, by = run(fail_for={"idle"})
    assert by["idle"].state is IdleState.UNKNOWN and by["busy"].state is IdleState.ACTIVE
    assert len(s.errors) == 1 and "idle" in s.errors[0]


def test_metric_request_shape():
    _, session, _ = run()
    _, params, _ = next(c for c in session.calls if "insights/metrics" in c[0])
    assert params["interval"] == "PT1H" and params["metricnames"] == "Percentage CPU,Network In Total,Network Out Total"
    assert params["timespan"] == "2026-10-06T12:00:00Z/2026-10-20T12:00:00Z"  # 14 days, hour aligned


def test_no_subscriptions_configured_is_a_clear_error():
    try:
        scan_azure(subscriptions=[], now=NOW, rest_factory=lambda: None)
    except ValueError as exc:
        assert "GREENOPS_AZURE_SUBSCRIPTIONS" in str(exc)
        return
    raise AssertionError("expected ValueError")
