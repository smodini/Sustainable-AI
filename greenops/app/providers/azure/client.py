"""Azure auth via DefaultAzureCredential (env vars, managed identity, CLI, ...).
azure-identity is imported lazily so the rest of the package imports and tests without it.

Required RBAC on each scanned subscription: Reader (inventory) and Monitoring Reader
(metrics). One ARM-scoped token serves both the inventory and Azure Monitor metrics APIs.
"""

from __future__ import annotations

import os
from typing import Optional

from app.providers.rest import CachedToken, RestClient

_SCOPE = "https://management.azure.com/.default"


def get_rest_client() -> RestClient:
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()

    def fetch() -> tuple[str, float]:
        token = credential.get_token(_SCOPE)
        return token.token, float(token.expires_on)

    return RestClient(CachedToken(fetch))


def configured_subscriptions(env: Optional[dict[str, str]] = None) -> list[str]:
    """Subscriptions to scan from GREENOPS_AZURE_SUBSCRIPTIONS (comma separated)."""
    env = dict(os.environ) if env is None else env
    return [s.strip() for s in env.get("GREENOPS_AZURE_SUBSCRIPTIONS", "").split(",") if s.strip()]
