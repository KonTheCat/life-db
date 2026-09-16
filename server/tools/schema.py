from datetime import datetime, timezone

from azure.cosmos import exceptions
from fastmcp import FastMCP

from services import cosmos as cosmos_service
from services.cosmos import validate_against_schema

ALLOWED_FIELD_TYPES = {"string", "number", "boolean", "array", "object"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_field_defs(fields: dict) -> None:
    for name, spec in fields.items():
        if not isinstance(spec, dict) or spec.get("type") not in ALLOWED_FIELD_TYPES:
            raise ValueError(
                f"field '{name}' must specify a type in {sorted(ALLOWED_FIELD_TYPES)}"
            )


def _get_schema_doc(collection: str) -> dict:
    try:
        return cosmos_service.get_schemas_container().read_item(
            item=collection, partition_key=collection
        )
    except exceptions.CosmosResourceNotFoundError:
        raise ValueError(f"no schema for collection '{collection}' -- call create_collection first")


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def list_collections() -> list[dict]:
        """List all user-defined collections with their current schema version."""
        container = cosmos_service.get_schemas_container()
        items = container.read_all_items()
        return [{"collection": i["collectionName"], "version": i["version"]} for i in items]

    @mcp.tool
    def get_schema(collection: str) -> dict:
        """Get the current schema (field definitions + version) for a collection."""
        return _get_schema_doc(collection)

    @mcp.tool
    def create_collection(
        collection: str,
        fields: dict,
        embed_fields: list[str] | None = None,
        instructions: str | None = None,
    ) -> dict:
        """Create a new collection with a schema.

        fields: {field_name: {"type": "string"|"number"|"boolean"|"array"|"object", "required": bool}}
        embed_fields: field names concatenated to build the search embedding (used once
        semantic search is wired up; harmless to set now).
        instructions: free-text guidance for the calling agent -- how to format data for
        entry, and/or what to do after a write (e.g. follow-up steps, things to check).
        Echoed back on every upsert_document call. Change with update_instructions;
        doesn't require a schema version bump.
        """
        if cosmos_service.is_protected_collection_name(collection):
            raise ValueError(
                f"'{collection}' is a reserved name (system containers, and anything starting "
                "with '_', are off-limits for user collections)"
            )
        _validate_field_defs(fields)
        container = cosmos_service.get_schemas_container()
        try:
            container.read_item(item=collection, partition_key=collection)
            raise ValueError(f"collection '{collection}' already exists")
        except exceptions.CosmosResourceNotFoundError:
            pass

        now = _now()
        doc = {
            "id": collection,
            "collectionName": collection,
            "version": 1,
            "fields": fields,
            "embed_fields": embed_fields or [],
            "instructions": instructions or "",
            "created_at": now,
            "updated_at": now,
        }
        container.create_item(doc)
        cosmos_service.get_or_create_collection_container(collection)
        return doc

    @mcp.tool
    def delete_collection(collection: str, confirm: bool = False) -> dict:
        """Permanently delete a collection: its schema AND every document in it.

        This cannot be undone -- pass confirm=True explicitly to proceed.
        To remove individual documents instead, use delete_document.
        """
        if cosmos_service.is_protected_collection_name(collection):
            raise ValueError(f"'{collection}' is a reserved system name and cannot be deleted this way")
        if not confirm:
            raise ValueError(
                f"this permanently deletes collection '{collection}' and all its documents -- "
                "call again with confirm=True to proceed"
            )
        _get_schema_doc(collection)  # raises if it doesn't exist
        cosmos_service.delete_collection_container(collection)
        cosmos_service.get_schemas_container().delete_item(item=collection, partition_key=collection)
        return {"deleted_collection": collection}

    @mcp.tool
    def update_schema(
        collection: str, fields: dict, embed_fields: list[str] | None = None
    ) -> dict:
        """Replace the field definitions for a collection and bump its schema version.

        This only changes the schema document — existing documents are untouched.
        Run migrate_schema afterward to bring them in line.
        """
        _validate_field_defs(fields)
        doc = _get_schema_doc(collection)
        doc["fields"] = fields
        if embed_fields is not None:
            doc["embed_fields"] = embed_fields
        doc["version"] += 1
        doc["updated_at"] = _now()
        cosmos_service.get_schemas_container().replace_item(item=doc, body=doc)
        return doc

    @mcp.tool
    def update_instructions(collection: str, instructions: str) -> dict:
        """Replace the free-text agent instructions for a collection.

        Unlike update_schema, this does not bump the schema version and never
        requires migrate_schema -- instructions don't affect document shape or
        validation, only how the calling agent should format entries or handle
        follow-up steps after a write.
        """
        doc = _get_schema_doc(collection)
        doc["instructions"] = instructions
        doc["updated_at"] = _now()
        cosmos_service.get_schemas_container().replace_item(item=doc, body=doc)
        return doc

    @mcp.tool
    def migrate_schema(
        collection: str,
        mode: str = "preview",
        defaults: dict | None = None,
        drop_fields: list[str] | None = None,
    ) -> dict:
        """Bring existing documents in a collection in line with its current schema version.

        mode: "preview" reports what would happen without writing anything;
              "apply" performs the writes. Always run preview first.
        defaults: {field_name: default_value} backfilled onto documents missing a
                  newly-required field.
        drop_fields: field names to strip from every document (e.g. fields removed
                     from the schema since they were written).

        A document that still fails validation after defaults/drops are applied is
        reported as failed and left untouched in both modes — migration never
        silently overwrites or discards data it can't reconcile.
        """
        if mode not in ("preview", "apply"):
            raise ValueError("mode must be 'preview' or 'apply'")

        schema = _get_schema_doc(collection)
        container = cosmos_service.get_or_create_collection_container(collection)
        defaults = defaults or {}
        drop_fields = drop_fields or []

        scanned = 0
        matched = 0
        would_update: list[str] = []
        failed: list[dict] = []
        now = _now()

        for doc in container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True):
            scanned += 1
            doc_id = doc["id"]
            for field in drop_fields:
                doc.pop(field, None)
            for field, default in defaults.items():
                if field not in doc:
                    doc[field] = default

            user_fields = {k: v for k, v in doc.items() if k not in cosmos_service.SYSTEM_FIELDS}
            try:
                validate_against_schema(schema, user_fields, partial=False)
            except cosmos_service.SchemaValidationError as e:
                failed.append({"id": doc_id, "errors": e.errors})
                continue

            matched += 1
            if doc.get("_schemaVersion") == schema["version"] and not drop_fields and not defaults:
                continue  # already current, nothing to do

            would_update.append(doc_id)
            if mode == "apply":
                doc["_schemaVersion"] = schema["version"]
                doc["updated_at"] = now
                container.replace_item(item=doc_id, body=doc)

        return {
            "mode": mode,
            "scanned": scanned,
            "matched": matched,
            "updated" if mode == "apply" else "would_update": would_update,
            "failed": failed,
        }
