"""Azure ARM inventory: VMs (with power state) and unattached managed disks, as raw ARM
JSON for ``normalize.py``. ARM list responses are followed via ``nextLink``."""

from __future__ import annotations

from typing import Any, Iterator

from app.providers.rest import RestClient

ARM = "https://management.azure.com"
COMPUTE_API = "2024-07-01"
DISK_API = "2023-10-02"


def iter_vms(rest: RestClient, subscription: str) -> Iterator[dict[str, Any]]:
    """All VMs in the subscription; ``$expand=instanceView`` supplies the power state."""
    url = f"{ARM}/subscriptions/{subscription}/providers/Microsoft.Compute/virtualMachines"
    params = {"api-version": COMPUTE_API, "$expand": "instanceView"}
    for page in rest.paginate(url, params, link_field="nextLink"):
        yield from page.get("value", [])


def iter_unattached_disks(rest: RestClient, subscription: str) -> Iterator[dict[str, Any]]:
    """Managed disks with ``diskState == Unattached`` and no ``managedBy`` (the Azure
    counterpart of an AWS EBS volume in state ``available``)."""
    url = f"{ARM}/subscriptions/{subscription}/providers/Microsoft.Compute/disks"
    for page in rest.paginate(url, {"api-version": DISK_API}, link_field="nextLink"):
        for disk in page.get("value", []):
            if disk.get("properties", {}).get("diskState") == "Unattached" and not disk.get("managedBy"):
                yield disk
