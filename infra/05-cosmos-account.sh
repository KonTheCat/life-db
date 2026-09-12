#!/usr/bin/env bash
# Cosmos DB: serverless NoSQL account + database + system containers.
# Idempotent (check-then-create): safe to re-run after a partial failure.
#
# Usage:
#   ./05-cosmos-account.sh          # creates/confirms the prod database ($COSMOS_DATABASE)
#   ./05-cosmos-account.sh --dev    # creates/confirms the dev database ($COSMOS_DEV_DATABASE)
#                                    # used for local testing per plan §11/§13 phase 2
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

DATABASE="$COSMOS_DATABASE"
if [[ "${1:-}" == "--dev" ]]; then
  DATABASE="$COSMOS_DEV_DATABASE"
fi

echo "== Cosmos account: $COSMOS_ACCOUNT =="
if az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "account exists, skipping create"
else
  az cosmosdb create \
    --name "$COSMOS_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --locations regionName="$LOCATION" failoverPriority=0 isZoneRedundant=false \
    --capabilities EnableServerless \
    --kind GlobalDocumentDB
fi

echo "== Database: $DATABASE =="
if az cosmosdb sql database show \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --name "$DATABASE" &>/dev/null; then
  echo "database exists, skipping create"
else
  az cosmosdb sql database create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --name "$DATABASE"
fi

echo "== Container: _schemas (partition key /collectionName) =="
if az cosmosdb sql container show \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$DATABASE" --name "_schemas" &>/dev/null; then
  echo "container exists, skipping create"
else
  az cosmosdb sql container create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$DATABASE" --name "_schemas" \
    --partition-key-path "/collectionName"
fi

echo "== Container: _notifications (partition key /status, composite index status+due_at) =="
if az cosmosdb sql container show \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$DATABASE" --name "_notifications" &>/dev/null; then
  echo "container exists, skipping create"
else
  az cosmosdb sql container create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$DATABASE" --name "_notifications" \
    --partition-key-path "/status" \
    --idx @./composite-index-notifications.json
fi

echo "== Container: _search_index (partition key /collection, vector index) =="
if az cosmosdb sql container show \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$DATABASE" --name "_search_index" &>/dev/null; then
  echo "container exists, skipping create"
else
  az cosmosdb sql container create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$DATABASE" --name "_search_index" \
    --partition-key-path "/collection" \
    --idx @./vector-index-search.json \
    --vector-embeddings @./vector-embeddings-search.json
fi

echo "== Done. Database '$DATABASE' ready on account '$COSMOS_ACCOUNT'. =="
