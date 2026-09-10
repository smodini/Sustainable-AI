import datetime
from google.cloud.monitoring_v3 import MetricServiceClient
from google.cloud.monitoring_v3.types import ListTimeSeriesRequest, TimeInterval
from google.protobuf.timestamp_pb2 import Timestamp
from app.providers.gcp.client import get_monitoring_client


def _make_interval(days: int) -> TimeInterval:
    end_dt = datetime.datetime.utcnow()
    start_dt = end_dt - datetime.timedelta(days=days)

    end_ts = Timestamp()
    end_ts.FromDatetime(end_dt)
    start_ts = Timestamp()
    start_ts.FromDatetime(start_dt)

    interval = TimeInterval()
    interval.end_time = end_ts
    interval.start_time = start_ts
    return interval


def get_cpu_metrics(instance_id: str, project_id: str, days: int = 7) -> dict:
    client: MetricServiceClient = get_monitoring_client()
    project_name = f"projects/{project_id}"

    results = client.list_time_series(
        name=project_name,
        filter=f'metric.type="compute.googleapis.com/instance/cpu/utilization" AND resource.labels.instance_id="{instance_id}"',
        interval=_make_interval(days),
        view=ListTimeSeriesRequest.TimeSeriesView.FULL,
    )

    values = [point.value.double_value * 100 for ts in results for point in ts.points]
    if not values:
        return {"avg": 0.0, "max": 0.0}

    return {
        "avg": round(sum(values) / len(values), 2),
        "max": round(max(values), 2),
    }


def get_network_metrics(instance_id: str, project_id: str, days: int = 7) -> float:
    client: MetricServiceClient = get_monitoring_client()
    project_name = f"projects/{project_id}"
    total_bytes = 0.0

    for direction in ("sent_bytes_count", "received_bytes_count"):
        results = client.list_time_series(
            name=project_name,
            filter=f'metric.type="compute.googleapis.com/instance/network/{direction}" AND resource.labels.instance_id="{instance_id}"',
            interval=_make_interval(days),
            view=ListTimeSeriesRequest.TimeSeriesView.FULL,
        )
        for ts in results:
            for point in ts.points:
                total_bytes += point.value.int64_value

    mb_per_day = round((total_bytes / 1024 / 1024) / days, 2)
    return mb_per_day
