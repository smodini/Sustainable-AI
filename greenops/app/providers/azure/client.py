import os
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient


def get_credential():
    return DefaultAzureCredential()


def get_subscription_id() -> str:
    sub = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not sub:
        raise ValueError("AZURE_SUBSCRIPTION_ID environment variable is not set")
    return sub


def get_compute_client() -> ComputeManagementClient:
    return ComputeManagementClient(get_credential(), get_subscription_id())


def get_metrics_client() -> MonitorManagementClient:
    return MonitorManagementClient(get_credential(), get_subscription_id())
