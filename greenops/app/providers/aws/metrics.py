import datetime
from app.providers.aws.client import get_cloudwatch_client


def get_cpu_metrics(instance_id: str, region: str, days: int = 7) -> dict:
    cw = get_cloudwatch_client(region)
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)

    response = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Average", "Maximum"],
    )

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return {"avg": 0.0, "max": 0.0}

    avgs = [d["Average"] for d in datapoints]
    maxs = [d["Maximum"] for d in datapoints]
    return {
        "avg": round(sum(avgs) / len(avgs), 2),
        "max": round(max(maxs), 2),
    }


def get_network_metrics(instance_id: str, region: str, days: int = 7) -> float:
    cw = get_cloudwatch_client(region)
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)

    total_bytes = 0.0
    for metric in ("NetworkIn", "NetworkOut"):
        response = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName=metric,
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=days * 86400,
            Statistics=["Sum"],
        )
        datapoints = response.get("Datapoints", [])
        if datapoints:
            total_bytes += datapoints[0].get("Sum", 0.0)

    mb_per_day = round((total_bytes / 1024 / 1024) / days, 2)
    return mb_per_day
