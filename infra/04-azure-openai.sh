#!/usr/bin/env bash
# Azure OpenAI account + text-embedding-3-small deployment, used for semantic
# recall (plan §3). Idempotent (check-then-create).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Azure OpenAI account: $AZURE_OPENAI_ACCOUNT =="
if az cognitiveservices account show --name "$AZURE_OPENAI_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "account exists, skipping create"
else
  az cognitiveservices account create \
    --name "$AZURE_OPENAI_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --kind OpenAI \
    --sku S0 \
    --custom-domain "$AZURE_OPENAI_ACCOUNT" \
    --yes
fi

echo "== Deployment: $AZURE_OPENAI_EMBEDDING_DEPLOYMENT (text-embedding-3-small) =="
if az cognitiveservices account deployment show \
    --name "$AZURE_OPENAI_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$AZURE_OPENAI_EMBEDDING_DEPLOYMENT" &>/dev/null; then
  echo "deployment exists, skipping create"
else
  az cognitiveservices account deployment create \
    --name "$AZURE_OPENAI_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$AZURE_OPENAI_EMBEDDING_DEPLOYMENT" \
    --model-name "text-embedding-3-small" \
    --model-version "1" \
    --model-format OpenAI \
    --sku-capacity 10 \
    --sku-name "Standard"
fi

echo "== Endpoint =="
az cognitiveservices account show \
  --name "$AZURE_OPENAI_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
  --query "properties.endpoint" -o tsv
