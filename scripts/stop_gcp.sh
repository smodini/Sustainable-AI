#!/bin/bash
# Stop GreenOps test GCP instance

INSTANCE="greenops-test-vm"
ZONE="us-central1-a"
PROJECT="patent-poc-project"

echo "Stopping instance $INSTANCE in $ZONE..."
gcloud compute instances stop $INSTANCE \
  --zone=$ZONE \
  --project=$PROJECT

echo "Instance status:"
gcloud compute instances describe $INSTANCE \
  --zone=$ZONE \
  --project=$PROJECT \
  --format="table(name,machineType.basename(),status)"

echo "Instance stopped. No compute charges will apply."
