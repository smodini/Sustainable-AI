from pydantic import BaseModel


class IdlePolicy(BaseModel):
    cpu_threshold: float = 5.0
    network_threshold_mb_day: float = 5.0
    observation_days: int = 7


policy = IdlePolicy()
