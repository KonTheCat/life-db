#!/usr/bin/env bash
# Blob storage for attachments (plan §6). Idempotent (check-then-create).
# lifedbstor already existed in the lifedb resource group (pre-dating this
# script) -- this just confirms it and ensures the attachments container.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Storage account: $STORAGE_ACCOUNT =="
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "account exists, skipping create"
else
  az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2
fi

echo "== Container: $STORAGE_CONTAINER (private, AAD auth) =="
if az storage container show \
    --account-name "$STORAGE_ACCOUNT" --name "$STORAGE_CONTAINER" \
    --auth-mode login &>/dev/null; then
  echo "container exists, skipping create"
else
  az storage container create \
    --account-name "$STORAGE_ACCOUNT" --name "$STORAGE_CONTAINER" \
    --public-access off \
    --auth-mode login
fi

echo "== Done. Blob endpoint: =="
az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
  --query "primaryEndpoints.blob" -o tsv
