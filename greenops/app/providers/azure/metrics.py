import datetime
from app.providers.azure.client import get_metrics_client


def get_cpu_metrics(resource_id: str, days: int = 7) -> dict:
    client = get_metrics_client()
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)

    response = client.metrics.list(
        resource_id,
        timespan=f"{start.isoformat()}Z/{end.isoformat()}Z",
        interval="PT1H",
        metricnames="Percentage CPU",
        aggregation="Average,Maximum",
    )

    avgs, maxs = [], []
    for metric in response.value:
        for ts in metric.timeseries:
            for point in ts.data:
                if point.average is not None:
                    avgs.append(point.average)
                if point.maximum is not None:
                    maxs.append(point.maximum)

    return {
        "avg": round(sum(avgs) / len(avgs), 2) if avgs else 0.0,
        "max": round(max(maxs), 2) if maxs else 0.0,
    }


def get_network_metrics(resource_id: str, days: int = 7) -> float:
    client = get_metrics_client()
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)

    total_bytes = 0.0
    for metric_name in ["Network In Total", "Network Out Total"]:
        response = client.metrics.list(
            resource_id,
            timespan=f"{start.isoformat()}Z/{end.isoformat()}Z",
            interval=f"P{days}D",
            metricnames=metric_name,
            aggregation="Total",
        )
        for metric in response.value:
            for ts in metric.timeseries:
                for point in ts.data:
                    if point.total is not None:
                        total_bytes += point.total

    mb_per_day = round((total_bytes / 1024 / 1024) / days, 2)
    return mb_per_day
