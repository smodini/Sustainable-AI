from app.services.energy_calculator import calculate_energy_waste
from app.services.idle_detector import is_vm_idle


# --- Energy Calculator Tests ---

def test_full_month():
    assert calculate_energy_waste(720) == 108.0

def test_100_hours():
    assert calculate_energy_waste(100) == 15.0

def test_zero_hours():
    assert calculate_energy_waste(0) == 0.0


# --- Idle Detector Tests ---

def test_idle_both_signals_low():
    assert is_vm_idle(cpu_maximum=2.1, network_mb_per_day=1.5) is True

def test_active_cpu_high():
    assert is_vm_idle(cpu_maximum=8.0, network_mb_per_day=1.5) is False

def test_active_network_high():
    assert is_vm_idle(cpu_maximum=2.1, network_mb_per_day=9.0) is False

def test_boundary_cpu_exactly_threshold():
    assert is_vm_idle(cpu_maximum=5.0, network_mb_per_day=1.0) is False

def test_boundary_network_exactly_threshold():
    assert is_vm_idle(cpu_maximum=1.0, network_mb_per_day=5.0) is False
