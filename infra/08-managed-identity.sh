#!/usr/bin/env bash
# User-assigned managed identity shared by mcp-server and the dispatcher job,
# plus every RBAC role it needs (plan §2). Idempotent.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Managed identity: $MANAGED_IDENTITY =="
if az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "identity exists, skipping create"
else
  az identity create --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --location "$LOCATION"
fi

PRINCIPAL_ID=$(az identity show --name "$MANAGED_IDENTITY" --resource-group "$RESOURCE_GROUP" --query "principalId" -o tsv)
echo "principalId: $PRINCIPAL_ID"

assign_arm_role() {
  local role="$1" scope="$2"
  if az role assignment list --assignee "$PRINCIPAL_ID" --scope "$scope" --query "[?roleDefinitionName=='$role']" -o tsv | grep -q .; then
    echo "  already has '$role' at $scope"
  else
    az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$scope" >/dev/null
    echo "  granted '$role' at $scope"
  fi
}

echo "== ARM (control-plane) roles =="
assign_arm_role "Cosmos DB Operator" "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DocumentDB/databaseAccounts/$COSMOS_ACCOUNT"
assign_arm_role "Storage Blob Data Contributor" "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"
assign_arm_role "Key Vault Secrets User" "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$KEY_VAULT"
assign_arm_role "Cognitive Services OpenAI User" "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AZURE_OPENAI_ACCOUNT"
assign_arm_role "AcrPull" "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$ACR_RESOURCE_GROUP/providers/Microsoft.ContainerRegistry/registries/$ACR_NAME"
# One namespace, one identity, both send (app) and receive (job) -- Owner is
# simplest; split into Sender/Receiver roles later only if it starts to matter.
assign_arm_role "Azure Service Bus Data Owner" "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ServiceBus/namespaces/$SERVICE_BUS_NAMESPACE"

echo "== Cosmos data-plane role (separate RBAC model -- see infra/05) =="
if az cosmosdb sql role assignment list --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --query "[?principalId=='$PRINCIPAL_ID']" -o tsv | grep -q .; then
  echo "  already has Cosmos data-plane role"
else
  az cosmosdb sql role assignment create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --role-definition-id "00000000-0000-0000-0000-000000000002" \
    --principal-id "$PRINCIPAL_ID" --scope "/" >/dev/null
  echo "  granted Cosmos data-plane role"
fi

echo "== Done. =="
