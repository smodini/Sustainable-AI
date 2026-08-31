from fastapi import FastAPI
from app.providers.aws.scanner import scan_aws

app = FastAPI(title="GreenOps Multi-Cloud Energy Waste Platform")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/aws/scan")
def aws_scan():
    return scan_aws()
