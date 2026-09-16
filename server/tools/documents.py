import re
import uuid
from datetime import datetime, timezone
from typing import Any

from azure.cosmos import exceptions
from fastmcp import FastMCP

from services import cosmos as cosmos_service
from services import embeddings as embeddings_service
from services.cosmos import validate_against_schema

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPERATORS = {"eq", "gt", "lt", "in", "contains"}


def _validate_identifier(name: str) -> None:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"invalid field name '{name}'")


def _get_schema_doc(collection: str) -> dict:
    try:
        return cosmos_service.get_schemas_container().read_item(
            item=collection, partition_key=collection
        )
    except exceptions.CosmosResourceNotFoundError:
        raise ValueError(f"no schema for collection '{collection}' -- call create_collection first")


def _build_select_clause(fields: list[str] | None) -> str:
    if not fields:
        return "SELECT *"
    names = ["id"] + [f for f in fields if f != "id"]
    for name in names:
        _validate_identifier(name)
    return "SELECT " + ", ".join(f"c.{name}" for name in names)


def _build_where_clause(filters: dict[str, dict] | None) -> tuple[str, list[dict]]:
    if not filters:
        return "", []
    clauses = []
    params = []
    for i, (field, cond) in enumerate(filters.items()):
        _validate_identifier(field)
        if not isinstance(cond, dict) or len(cond) != 1:
            raise ValueError(f"filter for '{field}' must be a single-key object, e.g. {{'eq': value}}")
        (op, value), = cond.items()
        if op not in _OPERATORS:
            raise ValueError(f"unsupported filter operator '{op}' (allowed: {sorted(_OPERATORS)})")
        param_name = f"@p{i}"
        params.append({"name": param_name, "value": value})
        if op == "eq":
            clauses.append(f"c.{field} = {param_name}")
        elif op == "gt":
            clauses.append(f"c.{field} > {param_name}")
        elif op == "lt":
            clauses.append(f"c.{field} < {param_name}")
        elif op == "in":
            clauses.append(f"c.{field} IN ({param_name})")
        elif op == "contains":
            clauses.append(f"CONTAINS(c.{field}, {param_name})")
    return " AND ".join(clauses), params


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def get_document(collection: str, id: str) -> dict:
        """Fetch a single document by id from a collection.

        If the collection's schema has `instructions` set, they're returned
        here as `_instructions` (not persisted).
        """
        schema = _get_schema_doc(collection)  # also guards against silently creating a container for a typo'd name
        container = cosmos_service.get_or_create_collection_container(collection)
        try:
            doc = container.read_item(item=id, partition_key=id)
        except exceptions.CosmosResourceNotFoundError:
            raise ValueError(f"no document '{id}' in collection '{collection}'")
        if schema.get("instructions"):
            doc = dict(doc)
            doc["_instructions"] = schema["instructions"]
        return doc

    @mcp.tool
    def query_documents(
        collection: str,
        filters: dict[str, dict] | None = None,
        fields: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query documents in a collection.

        filters: {field_name: {"eq"|"gt"|"lt"|"in"|"contains": value}}, ANDed together.
        fields: project only these field names (plus id) to keep responses lean;
                omit for full documents.
        """
        _get_schema_doc(collection)  # also guards against silently creating a container for a typo'd name
        container = cosmos_service.get_or_create_collection_container(collection)
        select_clause = _build_select_clause(fields)
        where_clause, params = _build_where_clause(filters)
        query = f"{select_clause} FROM c"
        if where_clause:
            query += f" WHERE {where_clause}"
        query += f" OFFSET 0 LIMIT {int(limit)}"
        return list(
            container.query_items(query=query, parameters=params, enable_cross_partition_query=True)
        )

    @mcp.tool
    def upsert_document(collection: str, data: dict, id: str | None = None) -> dict:
        """Create or update a document.

        Validates `data` against the collection's schema first: unknown fields are
        rejected, and required fields must be present when creating (id omitted).
        Updating an existing document (id given) is a partial merge — omitted
        fields keep their prior value. System fields (id, _schemaVersion,
        created_at, updated_at, attachments) are set by the server and ignored
        if passed in `data`. If the collection's schema has `instructions` set,
        they're returned here as `_instructions` (not persisted) -- read them
        for formatting guidance or follow-up steps.
        """
        schema = _get_schema_doc(collection)
        container = cosmos_service.get_or_create_collection_container(collection)

        existing: dict[str, Any] | None = None
        if id is not None:
            try:
                existing = container.read_item(item=id, partition_key=id)
            except exceptions.CosmosResourceNotFoundError:
                existing = None
        if id is None:
            id = str(uuid.uuid4())

        cleaned = validate_against_schema(schema, data, partial=existing is not None)

        now = datetime.now(timezone.utc).isoformat()
        doc = dict(existing) if existing else {}
        doc.update(cleaned)
        doc["id"] = id
        doc["_schemaVersion"] = schema["version"]
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        doc.setdefault("attachments", [])

        container.upsert_item(doc)

        snippet = embeddings_service.build_snippet(schema, doc)
        if snippet:
            embeddings_service.schedule_embedding(collection, id, snippet)

        if schema.get("instructions"):
            doc = dict(doc)
            doc["_instructions"] = schema["instructions"]
        return doc

    @mcp.tool
    def delete_document(collection: str, id: str) -> dict:
        """Delete a document by id."""
        schema = _get_schema_doc(collection)
        container = cosmos_service.get_or_create_collection_container(collection)
        try:
            container.delete_item(item=id, partition_key=id)
        except exceptions.CosmosResourceNotFoundError:
            raise ValueError(f"no document '{id}' in collection '{collection}'")
        if schema.get("embed_fields"):
            embeddings_service.schedule_deindex(collection, id)
        return {"deleted": id}
