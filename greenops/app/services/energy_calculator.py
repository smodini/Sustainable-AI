IDLE_POWER_KW = 0.10
PUE = 1.50
MONTHLY_HOURS = 720


def calculate_energy_waste(idle_hours: float = MONTHLY_HOURS) -> float:
    """
    E_waste = P_idle x PUE x T

    Patent baseline: 0.10 x 1.50 x 720 = 108.0 kWh per idle VM per month
    """
    return round(IDLE_POWER_KW * PUE * idle_hours, 2)
