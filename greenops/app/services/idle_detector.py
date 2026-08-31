CPU_THRESHOLD = 5.0
NETWORK_THRESHOLD_MB = 5.0


def is_vm_idle(cpu_maximum: float, network_mb_per_day: float) -> bool:
    """
    Returns True if both CPU and network signals are below idle thresholds.
    Thresholds configurable via app/config.py IdlePolicy.
    """
    if cpu_maximum >= CPU_THRESHOLD:
        return False
    if network_mb_per_day >= NETWORK_THRESHOLD_MB:
        return False
    return True
