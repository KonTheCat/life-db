#!/usr/bin/env bash
# Service Bus namespace + queues for notification wake-up scheduling
# (service-bus-notifications-plan.md §3). Basic tier -- no topics support and
# none needed (single producer, single consumer). Idempotent.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./00-vars.sh

echo "== Service Bus namespace: $SERVICE_BUS_NAMESPACE (Basic) =="
if az servicebus namespace show --name "$SERVICE_BUS_NAMESPACE" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "namespace exists, skipping create"
else
  az servicebus namespace create \
    --name "$SERVICE_BUS_NAMESPACE" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Basic
fi

create_queue() {
  local queue="$1"
  echo "== Queue: $queue =="
  if az servicebus queue show --namespace-name "$SERVICE_BUS_NAMESPACE" --resource-group "$RESOURCE_GROUP" --name "$queue" &>/dev/null; then
    echo "queue exists, skipping create"
  else
    az servicebus queue create \
      --namespace-name "$SERVICE_BUS_NAMESPACE" --resource-group "$RESOURCE_GROUP" \
      --name "$queue" \
      --max-delivery-count 5 \
      --default-message-time-to-live P14D
  fi
}

create_queue "$SERVICE_BUS_QUEUE"
create_queue "$SERVICE_BUS_QUEUE_DEV"

echo "== Grant self (for local dev) Azure Service Bus Data Owner =="
SELF_ID=$(az ad signed-in-user show --query id -o tsv)
SB_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ServiceBus/namespaces/$SERVICE_BUS_NAMESPACE"
if az role assignment list --assignee "$SELF_ID" --scope "$SB_SCOPE" --query "[?roleDefinitionName=='Azure Service Bus Data Owner']" -o tsv | grep -q .; then
  echo "  already granted"
else
  az role assignment create --assignee-object-id "$SELF_ID" --assignee-principal-type User \
    --role "Azure Service Bus Data Owner" --scope "$SB_SCOPE" >/dev/null
  echo "  granted"
fi

echo "== Done. Namespace host: =="
echo "${SERVICE_BUS_NAMESPACE}.servicebus.windows.net"
