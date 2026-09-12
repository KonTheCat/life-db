#!/usr/bin/env bash
# Entra ID app registration for Microsoft Graph delegated access (calendar +
# contacts). Public client (device code flow) — no client secret needed since
# this is a single-user personal script, not a service acting on behalf of
# many users. Idempotent (check-then-create).
#
# The interactive sign-in/consent step (needed once, from a machine with a
# browser) is NOT part of this script — run:
#   uv run python server/services/graph_auth_setup.py
# afterward to get the refresh token into .env.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

APP_NAME="life-db"
GRAPH_API_ID="00000003-0000-0000-c000-000000000000"
CALENDARS_READWRITE="1ec239c2-d7c9-4623-a91a-a9775856bb36"
CONTACTS_READWRITE="d56682ec-c09e-4743-aaf4-1a3aac4caa21"
OFFLINE_ACCESS="7427e0e9-2fba-42fe-b0c0-848c9e6a8182"

echo "== Entra app registration: $APP_NAME =="
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [[ -n "$APP_ID" ]]; then
  echo "app exists, skipping create ($APP_ID)"
else
  APP_ID=$(az ad app create \
    --display-name "$APP_NAME" \
    --sign-in-audience AzureADandPersonalMicrosoftAccount \
    --is-fallback-public-client true \
    --query "appId" -o tsv)
  echo "created app $APP_ID"
fi

echo "== Delegated Graph permissions =="
az ad app permission add --id "$APP_ID" --api "$GRAPH_API_ID" --api-permissions \
  "${CALENDARS_READWRITE}=Scope" \
  "${CONTACTS_READWRITE}=Scope" \
  "${OFFLINE_ACCESS}=Scope" || echo "(already present)"

echo "== Done. GRAPH_CLIENT_ID=$APP_ID =="
echo "Add GRAPH_CLIENT_ID=$APP_ID to .env, then run the one-time device-code sign-in."
