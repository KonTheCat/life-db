#!/usr/bin/env bash
# Shared Azure Container Registry, in the cross-project shared-global RG, not
# lifedb -- ACR (even Basic tier) bills a small fixed daily rate regardless of
# usage, so one shared registry for all projects beats one per project.
# Idempotent (check-then-create).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Container registry: $ACR_NAME (in $ACR_RESOURCE_GROUP) =="
if az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" &>/dev/null; then
  echo "registry exists, skipping create"
else
  az acr create \
    --name "$ACR_NAME" \
    --resource-group "$ACR_RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Basic
fi

echo "== Login server: =="
az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query "loginServer" -o tsv
