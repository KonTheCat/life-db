#!/usr/bin/env bash
# notification-dispatcher: same image as mcp-server, different command.
# Event-driven (KEDA azure-servicebus scale rule) instead of a cron poll --
# see service-bus-notifications-plan.md. One execution per queued message,
# scaling from zero.
#
# NOTE (plan §5.2/§8): Container Apps' event-driven job + Service Bus scale
# rule wiring changes across az cli/platform versions -- if `az containerapp
# job create/update` rejects --scale-rule-identity or the metadata keys
# below, re-check current `az containerapp job` docs before falling back to
# connection-string-based scale-rule-auth.
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
  "SERVICE_BUS_NAMESPACE=$SERVICE_BUS_NAMESPACE.servicebus.windows.net"
  "SERVICE_BUS_QUEUE_NAME=$SERVICE_BUS_QUEUE"
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
    --trigger-type Event \
    --min-executions 0 --max-executions 5 \
    --polling-interval 30 \
    --scale-rule-name sb-notifications \
    --scale-rule-type azure-servicebus \
    --scale-rule-metadata "namespace=$SERVICE_BUS_NAMESPACE" "queueName=$SERVICE_BUS_QUEUE" "messageCount=1" \
    --scale-rule-identity "$IDENTITY_ID" \
    --replica-timeout 120 \
    --replica-retry-limit 1 \
    --parallelism 1 --replica-completion-count 1 \
    --cpu 0.25 --memory 0.5Gi \
    --command "uv" --args "run" "python" "dispatcher/run.py" \
    --env-vars "${ENV_VARS[@]}"
fi

echo "== Done. =="
