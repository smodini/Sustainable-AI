#!/bin/bash
# Stop GreenOps test Azure VM

RESOURCE_GROUP="greenops-rg"
VM_NAME="greenops-test-vm"

echo "Stopping VM $VM_NAME in resource group $RESOURCE_GROUP..."
az vm deallocate --resource-group $RESOURCE_GROUP --name $VM_NAME

echo "VM status:"
az vm show \
  --resource-group $RESOURCE_GROUP \
  --name $VM_NAME \
  --show-details \
  --query "{Name:name, Size:hardwareProfile.vmSize, State:powerState, Location:location}" \
  --output table

echo "VM deallocated. No compute charges will apply."
