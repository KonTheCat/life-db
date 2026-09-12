#!/usr/bin/env bash
# Container Apps Environment (Consumption workload profile -- no fixed idle
# cost, pay only for the vCPU/memory-seconds actually used).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Container Apps extension =="
az extension add --name containerapp --upgrade -y &>/dev/null || true

echo "== Container Apps Environment: $CONTAINERAPPS_ENV =="
if az containerapp env show --name "$CONTAINERAPPS_ENV" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "environment exists, skipping create"
else
  WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
    --query "customerId" -o tsv)
  WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
    --query "primarySharedKey" -o tsv)

  az containerapp env create \
    --name "$CONTAINERAPPS_ENV" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --logs-workspace-id "$WORKSPACE_ID" \
    --logs-workspace-key "$WORKSPACE_KEY" \
    --enable-workload-profiles false
fi
