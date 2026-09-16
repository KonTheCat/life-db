#!/usr/bin/env bash
# mcp-server Web App (build phase 9): same image as the old mcp-server
# Container App, but on App Service with Always On so there's no cold start
# -- Always On needs Basic tier+, which the shared B1 plan already covers at
# a flat cost cheaper than a warm Container App replica. Site itself
# (Microsoft.Web/sites/lifedb) and its App Service plan
# (shared-linux-asp-west-us-3, in shared-global like ACR) are provisioned
# outside this script; this only configures the container + identity + env
# vars on top of an existing site.
#
# Superseded the mcp-server Container App from infra/10-container-app.sh --
# see infra/10-container-app.sh's header for why that one still exists
# (kept for reference / rollback, not run by deploy.sh anymore).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query loginServer -o tsv)
IMAGE="$LOGIN_SERVER/lifedb/mcp-server:latest"
IDENTITY_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
IDENTITY_CLIENT_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query clientId -o tsv)
KEY_VAULT_URL=$(az keyvault show --name "$KEY_VAULT" --resource-group "$RESOURCE_GROUP" --query properties.vaultUri -o tsv)
COSMOS_ENDPOINT=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query documentEndpoint -o tsv)
STORAGE_URL=$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query primaryEndpoints.blob -o tsv)
OPENAI_ENDPOINT=$(az cognitiveservices account show --name "$AZURE_OPENAI_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query properties.endpoint -o tsv)

echo "== Web App: $WEB_APP -- assigning identity + ACR pull creds =="
az webapp identity assign \
  --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP" \
  --identities "$IDENTITY_ID" -o none
az webapp config set \
  --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP" \
  --acr-identity "$IDENTITY_ID" \
  --generic-configurations '{"acrUseManagedIdentityCreds": true}' \
  --always-on true \
  -o none

echo "== Web App: $WEB_APP -- setting image =="
az webapp config container set \
  --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP" \
  --container-image-name "$IMAGE" \
  --container-registry-url "https://$LOGIN_SERVER" \
  -o none

echo "== Web App: $WEB_APP -- setting env vars =="
az webapp config appsettings set \
  --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP" \
  --settings \
  "WEBSITES_PORT=8000" \
  "MCP_TRANSPORT=http" \
  "MCP_PORT=8000" \
  "AZURE_CLIENT_ID=$IDENTITY_CLIENT_ID" \
  "AZURE_KEY_VAULT_URL=$KEY_VAULT_URL" \
  "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
  "COSMOS_DATABASE_NAME=$COSMOS_DATABASE" \
  "COSMOS_SUBSCRIPTION_ID=$SUBSCRIPTION_ID" \
  "COSMOS_RESOURCE_GROUP=$RESOURCE_GROUP" \
  "COSMOS_ACCOUNT_NAME=$COSMOS_ACCOUNT" \
  "AZURE_STORAGE_ACCOUNT_URL=$STORAGE_URL" \
  "AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT" \
  "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$AZURE_OPENAI_EMBEDDING_DEPLOYMENT" \
  "GRAPH_CLIENT_ID=$GRAPH_CLIENT_ID" \
  "TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID" \
  "SERVICE_BUS_NAMESPACE=$SERVICE_BUS_NAMESPACE.servicebus.windows.net" \
  "SERVICE_BUS_QUEUE_NAME=$SERVICE_BUS_QUEUE" \
  "USER_TIMEZONE=$USER_TIMEZONE" \
  -o none

echo "== Hostname: =="
az webapp show --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP" --query defaultHostName -o tsv
