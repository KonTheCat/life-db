#!/usr/bin/env bash
# mcp-server Container App: streamable-http, bearer auth, min replicas 0
# (cold start of a few seconds after idle -- fine for solo interactive use).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

IMAGE="$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query loginServer -o tsv)/lifedb/mcp-server:latest"
IDENTITY_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
IDENTITY_CLIENT_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query clientId -o tsv)
KEY_VAULT_URL=$(az keyvault show --name "$KEY_VAULT" --resource-group "$RESOURCE_GROUP" --query properties.vaultUri -o tsv)
COSMOS_ENDPOINT=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query documentEndpoint -o tsv)
STORAGE_URL=$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query primaryEndpoints.blob -o tsv)
OPENAI_ENDPOINT=$(az cognitiveservices account show --name "$AZURE_OPENAI_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query properties.endpoint -o tsv)

ENV_VARS=(
  "MCP_TRANSPORT=http"
  "MCP_PORT=8000"
  "AZURE_CLIENT_ID=$IDENTITY_CLIENT_ID"
  "AZURE_KEY_VAULT_URL=$KEY_VAULT_URL"
  "COSMOS_ENDPOINT=$COSMOS_ENDPOINT"
  "COSMOS_DATABASE_NAME=$COSMOS_DATABASE"
  "COSMOS_SUBSCRIPTION_ID=$SUBSCRIPTION_ID"
  "COSMOS_RESOURCE_GROUP=$RESOURCE_GROUP"
  "COSMOS_ACCOUNT_NAME=$COSMOS_ACCOUNT"
  "AZURE_STORAGE_ACCOUNT_URL=$STORAGE_URL"
  "AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT"
  "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
  "GRAPH_CLIENT_ID=$GRAPH_CLIENT_ID"
  "TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID"
)

echo "== Container App: $CONTAINER_APP =="
if az containerapp show --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "app exists, updating image + env"
  az containerapp update \
    --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" \
    --image "$IMAGE" \
    --set-env-vars "${ENV_VARS[@]}"
else
  az containerapp create \
    --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" \
    --environment "$CONTAINERAPPS_ENV" \
    --image "$IMAGE" \
    --registry-server "$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query loginServer -o tsv)" \
    --registry-identity "$IDENTITY_ID" \
    --user-assigned "$IDENTITY_ID" \
    --min-replicas 0 --max-replicas 1 \
    --cpu 0.5 --memory 1.0Gi \
    --ingress external --target-port 8000 \
    --env-vars "${ENV_VARS[@]}"
fi

echo "== FQDN: =="
az containerapp show --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv
