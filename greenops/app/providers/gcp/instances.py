"""GCP Compute inventory via the aggregated-list REST endpoints (one paginated call
covers every zone, instead of one call per zone). Returns raw REST dicts for
``normalize.py``.

``returnPartialSuccess`` lets a scan survive an unreachable zone; unreachable scopes are
appended to ``errors`` so the summary shows the totals are incomplete rather than
silently undercounting.
"""

from __future__ import annotations

from typing import Any, Iterator

from app.providers.rest import RestClient

COMPUTE = "https://compute.googleapis.com/compute/v1"


def _aggregated(
    rest: RestClient, project: str, collection: str, field: str, errors: list[str]
) -> Iterator[dict[str, Any]]:
    url = f"{COMPUTE}/projects/{project}/aggregated/{collection}"
    params = {"returnPartialSuccess": "true", "maxResults": 500}
    for page in rest.paginate(url, params):
        for scope, scoped in (page.get("items") or {}).items():
            yield from scoped.get(field, [])
        for scope in page.get("unreachables") or []:
            errors.append(f"{project}: {collection} unreachable scope {scope}")


def iter_instances(rest: RestClient, project: str, errors: list[str]) -> Iterator[dict[str, Any]]:
    return _aggregated(rest, project, "instances", "instances", errors)


def iter_unattached_disks(rest: RestClient, project: str, errors: list[str]) -> Iterator[dict[str, Any]]:
    """Persistent disks with no ``users`` (not attached to any instance)."""
    for disk in _aggregated(rest, project, "disks", "disks", errors):
        if not disk.get("users"):
            yield disk
