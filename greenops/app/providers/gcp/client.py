"""GCP auth via Application Default Credentials. google-auth is imported lazily so the rest
of the package (schema, detector, normalizers, scanner logic) imports and tests without it.

Required IAM on each scanned project: roles/compute.viewer and roles/monitoring.viewer.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Optional

from app.providers.rest import CachedToken, RestClient

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def get_rest_client() -> RestClient:
    import google.auth
    from google.auth.transport.requests import Request

    creds, _ = google.auth.default(scopes=[_SCOPE])

    def fetch() -> tuple[str, float]:
        creds.refresh(Request())
        # google-auth reports expiry as a naive UTC datetime.
        expiry = creds.expiry.replace(tzinfo=dt.timezone.utc) if creds.expiry else None
        return creds.token, expiry.timestamp() if expiry else 0.0

    return RestClient(CachedToken(fetch))


def configured_projects(env: Optional[dict[str, str]] = None) -> list[str]:
    """Projects to scan from GREENOPS_GCP_PROJECTS (comma separated)."""
    env = dict(os.environ) if env is None else env
    return [p.strip() for p in env.get("GREENOPS_GCP_PROJECTS", "").split(",") if p.strip()]
