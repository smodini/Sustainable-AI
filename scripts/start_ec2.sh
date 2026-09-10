#!/bin/bash
# Start GreenOps test EC2 instance

INSTANCE_ID="i-0d5d02ea0c1604ee2"
REGION="us-east-1"

echo "Starting instance $INSTANCE_ID in $REGION..."
aws ec2 start-instances --instance-ids $INSTANCE_ID --region $REGION

echo "Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $REGION

echo "Instance is running."
aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --region $REGION \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,PublicIpAddress]' \
  --output table
