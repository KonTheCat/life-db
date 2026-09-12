from azure.cosmos import exceptions
from fastmcp import FastMCP

from services import cosmos as cosmos_service
from services import embeddings as embeddings_service


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def search(query: str, collection: str | None = None, limit: int = 10) -> list[dict]:
        """Semantic search across every collection's embedded fields.

        Returns pointers, not full documents: {collection, id, snippet, score}.
        Follow up with get_document(collection, id) for the full record.
        collection: optionally restrict the search to one collection.
        """
        vector = embeddings_service.get_embedding(query)
        container = cosmos_service.get_search_index_container()

        select = "SELECT TOP @limit c.collection, c.docId AS id, c.snippet, VectorDistance(c.vector, @vector) AS score FROM c"
        params = [{"name": "@limit", "value": limit}, {"name": "@vector", "value": vector}]
        if collection is not None:
            select += " WHERE c.collection = @collection"
            params.append({"name": "@collection", "value": collection})
        # Cosmos always sorts VectorDistance most-similar-first; ASC/DESC isn't allowed.
        select += " ORDER BY VectorDistance(c.vector, @vector)"

        return list(
            container.query_items(query=select, parameters=params, enable_cross_partition_query=True)
        )

    @mcp.tool
    def reembed_collection(collection: str) -> dict:
        """Recompute embeddings for every document in a collection.

        Use after changing embed_fields via update_schema, or to recover from
        embedding failures logged during normal writes (see the server log
        for "embedding failed" entries naming the affected collection).
        """
        try:
            schema = cosmos_service.get_schemas_container().read_item(
                item=collection, partition_key=collection
            )
        except exceptions.CosmosResourceNotFoundError:
            raise ValueError(f"no schema for collection '{collection}'")

        doc_container = cosmos_service.get_or_create_collection_container(collection)
        scheduled = 0
        skipped = 0
        for doc in doc_container.query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True
        ):
            snippet = embeddings_service.build_snippet(schema, doc)
            if snippet:
                embeddings_service.schedule_embedding(collection, doc["id"], snippet)
                scheduled += 1
            else:
                skipped += 1

        return {"collection": collection, "scheduled": scheduled, "skipped_no_snippet": skipped}
