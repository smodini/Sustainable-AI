"""boto3 client factories. boto3 is imported lazily so the rest of the package (schema,
detector, calculator, normalizers) imports and tests without AWS dependencies installed."""

from __future__ import annotations

from typing import Any

# Adaptive retries absorb CloudWatch/EC2 throttling instead of failing a whole scan.
_RETRY = {"max_attempts": 8, "mode": "adaptive"}


def _client(service: str, region: str) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(service, region_name=region, config=Config(retries=_RETRY))


def get_ec2_client(region: str) -> Any:
    return _client("ec2", region)


def get_cloudwatch_client(region: str) -> Any:
    return _client("cloudwatch", region)


def get_account_id() -> str:
    return _client("sts", "us-east-1").get_caller_identity()["Account"]
