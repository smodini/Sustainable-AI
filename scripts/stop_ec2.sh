#!/bin/bash
# Stop GreenOps test EC2 instance

INSTANCE_ID="i-0d5d02ea0c1604ee2"
REGION="us-east-1"

echo "Stopping instance $INSTANCE_ID in $REGION..."
aws ec2 stop-instances --instance-ids $INSTANCE_ID --region $REGION

echo "Waiting for instance to be stopped..."
aws ec2 wait instance-stopped --instance-ids $INSTANCE_ID --region $REGION

echo "Instance is stopped. No compute charges will apply."
aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --region $REGION \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' \
  --output table
