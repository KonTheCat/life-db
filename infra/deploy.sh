#!/usr/bin/env bash
# Build + push the image, then roll it out to both the mcp-server web app
# and the notification-dispatcher job. This is the one script to re-run on
# every code change (plan §12).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

REPO_ROOT="$(cd .. && pwd)"
LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query loginServer -o tsv)
IMAGE="$LOGIN_SERVER/lifedb/mcp-server:latest"

echo "== Building + pushing $IMAGE =="
az acr build --registry "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --image "lifedb/mcp-server:latest" "$REPO_ROOT"

echo "== Updating mcp-server web app =="
az webapp config container set \
  --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP" \
  --container-image-name "$IMAGE" \
  --container-registry-url "https://$LOGIN_SERVER"
az webapp restart --name "$WEB_APP" --resource-group "$WEB_APP_RESOURCE_GROUP"

echo "== Updating notification-dispatcher job =="
az containerapp job update --name "$CONTAINER_APP_JOB" --resource-group "$RESOURCE_GROUP" --image "$IMAGE"

echo "== Done. =="
