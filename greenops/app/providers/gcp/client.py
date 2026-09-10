from google.cloud import compute_v1
from google.cloud.monitoring_v3 import MetricServiceClient


def get_compute_client() -> compute_v1.InstancesClient:
    return compute_v1.InstancesClient()


def get_zones_client() -> compute_v1.ZonesClient:
    return compute_v1.ZonesClient()


def get_monitoring_client() -> MetricServiceClient:
    return MetricServiceClient()
