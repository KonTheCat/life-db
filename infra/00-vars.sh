#!/usr/bin/env bash
# Shared variables, sourced by every infra script.
set -euo pipefail

export SUBSCRIPTION_ID="a7edb0c9-d49d-4c7c-a3d7-776c14e253d2"
export LOCATION="eastus2"
export RESOURCE_GROUP="lifedb"

# Cosmos DB
export COSMOS_ACCOUNT="lifedb"
export COSMOS_DATABASE="personaldb"

# Dev-only Cosmos database, used for local testing (build phase 2).
# Same serverless account as production, kept as a separate database so
# local schema/CRUD experiments never touch prod data.
export COSMOS_DEV_DATABASE="personaldb-dev"

# Container Apps (used from build phase 8 onward)
export ACR_NAME="lifedbacr"
export LOG_ANALYTICS_WORKSPACE="lifedb-logs"
export CONTAINERAPPS_ENV="lifedb-env"
export CONTAINER_APP="mcp-server"
export CONTAINER_APP_JOB="notification-dispatcher"

# Storage
export STORAGE_ACCOUNT="lifedbstorage"
export STORAGE_CONTAINER="attachments"

# Key Vault
export KEY_VAULT="lifedb-kv"

# Managed identity
export MANAGED_IDENTITY="lifedb-identity"
