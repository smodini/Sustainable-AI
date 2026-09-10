#!/bin/bash
# Start GreenOps test GCP instance

INSTANCE="greenops-test-vm"
ZONE="us-central1-a"
PROJECT="patent-poc-project"

echo "Starting instance $INSTANCE in $ZONE..."
gcloud compute instances start $INSTANCE \
  --zone=$ZONE \
  --project=$PROJECT

echo "Waiting for instance to be running..."
gcloud compute instances wait-until-running $INSTANCE \
  --zone=$ZONE \
  --project=$PROJECT 2>/dev/null || sleep 10

echo "Instance status:"
gcloud compute instances describe $INSTANCE \
  --zone=$ZONE \
  --project=$PROJECT \
  --format="table(name,machineType.basename(),status,networkInterfaces[0].accessConfigs[0].natIP)"
