#!/usr/bin/env bash
# notification-dispatcher: same image as mcp-server, different command,
# Schedule trigger every 5 minutes (plan §5).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

IMAGE="$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query loginServer -o tsv)/lifedb/mcp-server:latest"
IDENTITY_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
IDENTITY_CLIENT_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query clientId -o tsv)
KEY_VAULT_URL=$(az keyvault show --name "$KEY_VAULT" --resource-group "$RESOURCE_GROUP" --query properties.vaultUri -o tsv)
COSMOS_ENDPOINT=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query documentEndpoint -o tsv)

ENV_VARS=(
  "AZURE_CLIENT_ID=$IDENTITY_CLIENT_ID"
  "AZURE_KEY_VAULT_URL=$KEY_VAULT_URL"
  "COSMOS_ENDPOINT=$COSMOS_ENDPOINT"
  "COSMOS_DATABASE_NAME=$COSMOS_DATABASE"
  "TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID"
)

echo "== Container Apps Job: $CONTAINER_APP_JOB =="
if az containerapp job show --name "$CONTAINER_APP_JOB" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "job exists, updating image + env"
  az containerapp job update \
    --name "$CONTAINER_APP_JOB" --resource-group "$RESOURCE_GROUP" \
    --image "$IMAGE" \
    --set-env-vars "${ENV_VARS[@]}"
else
  az containerapp job create \
    --name "$CONTAINER_APP_JOB" --resource-group "$RESOURCE_GROUP" \
    --environment "$CONTAINERAPPS_ENV" \
    --image "$IMAGE" \
    --registry-server "$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query loginServer -o tsv)" \
    --registry-identity "$IDENTITY_ID" \
    --user-assigned "$IDENTITY_ID" \
    --trigger-type Schedule \
    --cron-expression "*/5 * * * *" \
    --replica-timeout 120 \
    --replica-retry-limit 1 \
    --parallelism 1 --replica-completion-count 1 \
    --cpu 0.25 --memory 0.5Gi \
    --command "uv" --args "run" "python" "dispatcher/run.py" \
    --env-vars "${ENV_VARS[@]}"
fi
