import datetime as dt

from app.config import IdlePolicy
from app.models.idleness import IdleState, LifecycleState, Telemetry
from app.services.idle_detector import classify, find_exemption, is_vm_idle
from tests.conftest_helpers import NOW, WINDOW_END, WINDOW_START, disk, tel, vm


def test_idle_vm_gets_patent_baseline_energy():
    r = classify(vm(), tel(cpu_max=2.1, net=1.5), NOW)
    assert r.state is IdleState.IDLE
    assert r.energy.e_waste_kwh_monthly == 108.0
    assert r.energy.e_waste_kwh_observed == 25.2  # 168 h observed
    assert r.is_wasteful


def test_active_when_cpu_high_or_network_high():
    assert classify(vm(), tel(cpu_max=8.0), NOW).state is IdleState.ACTIVE
    assert classify(vm(), tel(net=9.0), NOW).state is IdleState.ACTIVE


def test_thresholds_are_strict_boundaries_are_active():
    assert classify(vm(), tel(cpu_max=5.0, net=1.0), NOW).state is IdleState.ACTIVE
    assert classify(vm(), tel(cpu_max=1.0, net=5.0), NOW).state is IdleState.ACTIVE
    assert classify(vm(), tel(cpu_max=4.99, net=4.99), NOW).state is IdleState.IDLE


def test_no_data_is_unknown_never_idle():
    empty = Telemetry(window_start=WINDOW_START, window_end=WINDOW_END, coverage=0.0)
    assert classify(vm(), None, NOW).state is IdleState.UNKNOWN
    assert classify(vm(), empty, NOW).state is IdleState.UNKNOWN
    r = classify(vm(), Telemetry(window_start=WINDOW_START, window_end=WINDOW_END,
                                 cpu_maximum=1.0, coverage=0.9), NOW)  # network missing
    assert r.state is IdleState.UNKNOWN and r.energy is None


def test_low_coverage_is_unknown():
    r = classify(vm(), tel(coverage=0.5), NOW)
    assert r.state is IdleState.UNKNOWN
    assert "coverage" in r.reason


def test_exemption_tag_wins_even_without_telemetry_case_insensitive():
    for tags in ({"greenops-ignore": "true"}, {"GreenOps-Ignore": "TRUE"}, {"greenops-ignore": " yes "}):
        r = classify(vm(tags=tags), None, NOW)
        assert r.state is IdleState.EXEMPT and r.exemption.exempt and r.energy is None
    # exempt even though it would otherwise be flagged orphaned
    assert classify(disk(tags={"greenops-ignore": "true"}), None, NOW).state is IdleState.EXEMPT


def test_falsey_exemption_value_does_not_exempt():
    assert not find_exemption({"greenops-ignore": "false"}).exempt
    assert classify(vm(tags={"greenops-ignore": "false"}), tel(), NOW).state is IdleState.IDLE


def test_user_defined_exemption_keys():
    policy = IdlePolicy(exemption_tag_keys=("keep-alive", "team-protected"))
    assert classify(vm(tags={"keep-alive": "true"}), tel(), NOW, policy).state is IdleState.EXEMPT
    # default key no longer applies once overridden
    assert classify(vm(tags={"greenops-ignore": "true"}), tel(), NOW, policy).state is IdleState.IDLE


def test_stopped_vm_and_transitional_vm():
    assert classify(vm(LifecycleState.STOPPED, state="stopped"), None, NOW).state is IdleState.STOPPED
    assert classify(vm(LifecycleState.OTHER, state="pending"), None, NOW).state is IdleState.UNKNOWN


def test_unattached_disk_is_orphaned_without_energy():
    r = classify(disk(), None, NOW)
    assert r.state is IdleState.ORPHANED and r.energy is None  # P_idle undefined for disks
    assert classify(disk(LifecycleState.ATTACHED, state="in-use"), None, NOW).state is IdleState.ACTIVE
    assert classify(disk(LifecycleState.OTHER, state="creating"), None, NOW).state is IdleState.UNKNOWN


def test_young_vm_only_counts_hours_it_existed():
    launched = WINDOW_END - dt.timedelta(hours=48)
    r = classify(vm(created_at=launched), tel(), NOW)
    assert r.state is IdleState.IDLE
    assert r.energy.idle_hours_observed == 48.0
    assert r.energy.e_waste_kwh_observed == 7.2
    assert r.energy.e_waste_kwh_monthly == 108.0


def test_legacy_is_vm_idle_helper():
    assert is_vm_idle(2.1, 1.5) is True
    assert is_vm_idle(8.0, 1.5) is False
    assert is_vm_idle(2.1, 9.0) is False
    assert is_vm_idle(5.0, 1.0) is False
    assert is_vm_idle(1.0, 5.0) is False
