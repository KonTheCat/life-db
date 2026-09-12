import os
from functools import lru_cache
from typing import Any

from azure.cosmos import ContainerProxy, CosmosClient, exceptions
from azure.identity import DefaultAzureCredential
from azure.mgmt.cosmosdb import CosmosDBManagementClient
from azure.mgmt.cosmosdb.models import (
    ContainerPartitionKey,
    SqlContainerCreateUpdateParameters,
    SqlContainerResource,
)

SYSTEM_FIELDS = {"id", "_schemaVersion", "created_at", "updated_at", "attachments"}

ALLOWED_FIELD_TYPES: dict[str, Any] = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class SchemaValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_against_schema(schema: dict, payload: dict, *, partial: bool) -> dict:
    """Validate a user-supplied payload against a `_schemas` document.

    Strict: unknown fields are rejected outright (not silently dropped), so
    typos surface immediately instead of vanishing into a write that looks
    like it succeeded.
    """
    fields = schema["fields"]
    errors: list[str] = []
    cleaned: dict[str, Any] = {}

    for key, value in payload.items():
        if key in SYSTEM_FIELDS:
            continue
        if key not in fields:
            errors.append(f"unknown field '{key}'")
            continue
        cleaned[key] = value

    if not partial:
        for name, spec in fields.items():
            if spec.get("required") and name not in cleaned:
                errors.append(f"missing required field '{name}'")

    for name, value in cleaned.items():
        expected = ALLOWED_FIELD_TYPES.get(fields[name]["type"])
        if expected is not None and not isinstance(value, expected):
            errors.append(
                f"field '{name}' expected type {fields[name]['type']}, got {type(value).__name__}"
            )

    if errors:
        raise SchemaValidationError(errors)
    return cleaned


@lru_cache(maxsize=1)
def get_client() -> CosmosClient:
    """Prefer AAD auth (DefaultAzureCredential, e.g. `az login`) over a raw key.

    Set COSMOS_KEY only if data-plane RBAC isn't set up for your identity; AAD
    is what's granted by `az cosmosdb sql role assignment create` in infra/05.
    """
    endpoint = os.environ["COSMOS_ENDPOINT"]
    key = os.environ.get("COSMOS_KEY")
    credential = key if key else DefaultAzureCredential()
    return CosmosClient(endpoint, credential=credential)


@lru_cache(maxsize=1)
def get_database():
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "personaldb-dev")
    return get_client().get_database_client(database_name)


@lru_cache(maxsize=1)
def _get_mgmt_client() -> CosmosDBManagementClient:
    """ARM (control-plane) client, used only for container/database structural
    changes. Azure Cosmos DB's AAD data-plane RBAC explicitly does not cover
    create/delete of containers or databases — only item-level operations —
    so dynamic collection creation has to go through ARM instead of the
    regular azure-cosmos SDK. See https://aka.ms/cosmos-native-rbac.
    """
    return CosmosDBManagementClient(
        DefaultAzureCredential(), os.environ["COSMOS_SUBSCRIPTION_ID"]
    )


_container_cache: dict[str, ContainerProxy] = {}


def _cached_container(name: str) -> ContainerProxy:
    if name not in _container_cache:
        _container_cache[name] = get_database().get_container_client(name)
    return _container_cache[name]


def get_schemas_container() -> ContainerProxy:
    return _cached_container("_schemas")


def get_notifications_container() -> ContainerProxy:
    return _cached_container("_notifications")


def get_search_index_container() -> ContainerProxy:
    return _cached_container("_search_index")


def get_or_create_collection_container(collection_name: str) -> ContainerProxy:
    if collection_name in _container_cache:
        return _container_cache[collection_name]

    database = get_database()
    container = database.get_container_client(collection_name)
    try:
        container.read()  # cheap data-plane metadata read; AAD RBAC allows this
    except exceptions.CosmosResourceNotFoundError:
        mgmt = _get_mgmt_client()
        mgmt.sql_resources.begin_create_update_sql_container(
            os.environ["COSMOS_RESOURCE_GROUP"],
            os.environ["COSMOS_ACCOUNT_NAME"],
            os.environ.get("COSMOS_DATABASE_NAME", "personaldb-dev"),
            collection_name,
            SqlContainerCreateUpdateParameters(
                resource=SqlContainerResource(
                    id=collection_name,
                    partition_key=ContainerPartitionKey(paths=["/id"], kind="Hash"),
                ),
                options={},
            ),
        ).result()

    _container_cache[collection_name] = container
    return container
