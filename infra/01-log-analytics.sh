#!/usr/bin/env bash
# Log Analytics workspace for Container Apps logs. Pay-per-GB ingestion, no
# fixed idle cost -- fine to keep in lifedb alongside everything else.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Log Analytics workspace: $LOG_ANALYTICS_WORKSPACE =="
if az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_WORKSPACE" &>/dev/null; then
  echo "workspace exists, skipping create"
else
  az monitor log-analytics workspace create \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
    --location "$LOCATION"
fi
