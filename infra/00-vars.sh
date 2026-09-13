#!/usr/bin/env bash
# Shared variables, sourced by every infra script.
set -euo pipefail

export SUBSCRIPTION_ID="a7edb0c9-d49d-4c7c-a3d7-776c14e253d2"
export LOCATION="eastus2"
export RESOURCE_GROUP="lifedb"

# Azure OpenAI (embeddings, plan §3)
export AZURE_OPENAI_ACCOUNT="lifedb-openai"
export AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-small"

# Cosmos DB
export COSMOS_ACCOUNT="lifedb"
export COSMOS_DATABASE="personaldb"

# Dev-only Cosmos database, used for local testing (build phase 2).
# Same serverless account as production, kept as a separate database so
# local schema/CRUD experiments never touch prod data.
export COSMOS_DEV_DATABASE="personaldb-dev"

# Container Apps (used from build phase 8 onward)
# ACR is shared across projects -- billed a small fixed daily rate regardless
# of usage, unlike everything else here, so it lives in the cross-project
# shared-global RG instead of lifedb. Everything else in this section has no
# fixed idle cost (Consumption Container Apps env, pay-per-GB Log Analytics).
export ACR_RESOURCE_GROUP="shared-global"
# ACR names are globally unique across all of Azure, not just this
# subscription -- "sharedacreastus2" was already taken by someone else.
export ACR_NAME="sharedacra7edb0c9"
export LOG_ANALYTICS_WORKSPACE="lifedb-logs"
export CONTAINERAPPS_ENV="lifedb-env"
export CONTAINER_APP="mcp-server"
export CONTAINER_APP_JOB="notification-dispatcher"

# Service Bus (notification wake-up scheduling, replaces the cron dispatcher --
# see service-bus-notifications-plan.md). Basic tier, two queues on one
# namespace mirroring the Cosmos personaldb/personaldb-dev split.
export SERVICE_BUS_NAMESPACE="lifedb-bus"
export SERVICE_BUS_QUEUE="notifications"
export SERVICE_BUS_QUEUE_DEV="notifications-dev"

# Storage
export STORAGE_ACCOUNT="lifedbstor"
export STORAGE_CONTAINER="attachments"

# Key Vault
export KEY_VAULT="lifedb-kv"

# Managed identity
export MANAGED_IDENTITY="lifedb-identity"

# Non-secret app config (secrets themselves live in Key Vault, see infra/07)
export TELEGRAM_CHAT_ID="5113962030"
export GRAPH_CLIENT_ID="3336a280-393b-4055-9b97-0e1e7f9106b6"
