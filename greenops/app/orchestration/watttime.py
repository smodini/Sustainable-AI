"""WattTime v3 grid-intensity provider.

Endpoints used (api.watttime.org):
  GET /login                    HTTP Basic -> {"token": ...}   (token valid ~30 min)
  GET /v3/region-from-loc       latitude, longitude, signal_type -> {"region": ...}
  GET /v3/data                  region, signal_type, start, end (<= 32 days per call)
                                -> {"meta": {"units": ...}, "data": [{"point_time", "value"}]}

``signal_type=co2_moer`` (marginal emissions) is reported in lbs CO2/MWh and converted to
g/kWh. ``meta.units`` is checked on every response and any other unit is rejected, never
guessed. Region and history access depend on the WattTime plan (a 403 propagates as a
``RestError``).

NOT yet verified against the live API: no WattTime credentials were available when this was
written; request and response handling follows the published OpenAPI spec and is covered by
fake-session tests. Run one real ``history()`` call and compare against the WattTime
dashboard before relying on it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Mapping, Optional

from app.orchestration.models import IntensityPoint, lbs_per_mwh_to_g_per_kwh
from app.providers.rest import CachedToken, RestClient

BASE = "https://api.watttime.org"
SIGNAL = "co2_moer"
MAX_WINDOW = dt.timedelta(days=32)
EXPECTED_UNITS = "lbs_co2_per_mwh"

# Approximate data-centre locations (lat, lon) used only to look up the WattTime balancing
# region. They are coarse on purpose; override or extend with GREENOPS_REGION_COORDS
# ('{"us-east-1": [39.04, -77.49], ...}'). WattTime coverage outside the US is limited.
DEFAULT_REGION_COORDS: dict[str, tuple[float, float]] = {
    # AWS
    "us-east-1": (39.04, -77.49), "us-east-2": (39.96, -83.00),
    "us-west-1": (37.35, -121.96), "us-west-2": (45.84, -119.70),
    # GCP
    "us-central1": (41.26, -95.86), "us-east1": (33.20, -80.01),
    "us-east4": (39.04, -77.49), "us-west1": (45.60, -121.18),
    # Azure
    "eastus": (37.37, -79.82), "eastus2": (36.67, -78.39), "centralus": (41.59, -93.62),
    "southcentralus": (29.42, -98.49), "westus2": (47.23, -119.85),
}


def coords_from_env(env: Optional[Mapping[str, str]] = None) -> dict[str, tuple[float, float]]:
    env = os.environ if env is None else env
    coords = dict(DEFAULT_REGION_COORDS)
    raw = env.get("GREENOPS_REGION_COORDS")
    if raw:
        coords.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()})
    return coords


def get_rest_client(username: str, password: str) -> RestClient:
    """Authenticated client; logs in with Basic auth and refreshes the 30-minute token early."""
    import requests

    def fetch() -> tuple[str, float]:
        resp = requests.get(f"{BASE}/login", auth=(username, password), timeout=30)
        resp.raise_for_status()
        return resp.json()["token"], time.time() + 25 * 60

    return RestClient(CachedToken(fetch))


def _parse_time(value: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t.astimezone(dt.timezone.utc)


class WattTimeProvider:
    def __init__(self, rest: RestClient, coords: Optional[Mapping[str, tuple[float, float]]] = None):
        self._rest = rest
        self._coords = dict(coords) if coords is not None else coords_from_env()
        self._regions: dict[str, str] = {}

    def resolve_region(self, cloud_region: str) -> str:
        """WattTime balancing-authority region for a cloud region (cached)."""
        if cloud_region not in self._regions:
            if cloud_region not in self._coords:
                raise KeyError(
                    f"no coordinates for cloud region {cloud_region!r}; add it via GREENOPS_REGION_COORDS"
                )
            lat, lon = self._coords[cloud_region]
            resp = self._rest.get_json(
                f"{BASE}/v3/region-from-loc",
                {"latitude": lat, "longitude": lon, "signal_type": SIGNAL},
            )
            self._regions[cloud_region] = resp["region"]
        return self._regions[cloud_region]

    def history(self, cloud_region: str, start: dt.datetime, end: dt.datetime) -> list[IntensityPoint]:
        """Intensity points in g CO2e/kWh over [start, end), fetched in <=32-day chunks."""
        region = self.resolve_region(cloud_region)
        points: list[IntensityPoint] = []
        lo = start
        while lo < end:
            hi = min(lo + MAX_WINDOW, end)
            resp = self._rest.get_json(
                f"{BASE}/v3/data",
                {
                    "region": region,
                    "signal_type": SIGNAL,
                    "start": lo.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": hi.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            units = resp.get("meta", {}).get("units")
            if units != EXPECTED_UNITS:
                raise ValueError(f"unexpected WattTime units {units!r} (expected {EXPECTED_UNITS!r})")
            for row in resp.get("data", []):
                if row.get("value") is None:
                    continue
                points.append(
                    IntensityPoint(
                        time=_parse_time(row["point_time"]),
                        g_co2_per_kwh=max(lbs_per_mwh_to_g_per_kwh(float(row["value"])), 0.0),
                    )
                )
            lo = hi
        return points
