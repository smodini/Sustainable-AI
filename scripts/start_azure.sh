#!/bin/bash
# Start GreenOps test Azure VM

RESOURCE_GROUP="greenops-rg"
VM_NAME="greenops-test-vm"

echo "Starting VM $VM_NAME in resource group $RESOURCE_GROUP..."
az vm start --resource-group $RESOURCE_GROUP --name $VM_NAME

echo "VM status:"
az vm show \
  --resource-group $RESOURCE_GROUP \
  --name $VM_NAME \
  --show-details \
  --query "{Name:name, Size:hardwareProfile.vmSize, State:powerState, PublicIP:publicIps, Location:location}" \
  --output table
