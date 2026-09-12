#!/usr/bin/env bash
# Key Vault for production secrets (Telegram bot token, MCP bearer token, the
# Graph device-code token cache). Standard tier: pay-per-operation, no fixed
# idle cost. RBAC authorization mode (no access policies), consistent with
# the AAD-everywhere approach used throughout this project.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Key Vault: $KEY_VAULT =="
if az keyvault show --name "$KEY_VAULT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "vault exists, skipping create"
else
  az keyvault create \
    --name "$KEY_VAULT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --enable-rbac-authorization true
fi
