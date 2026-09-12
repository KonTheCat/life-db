import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from services import cosmos as cosmos_service

logger = logging.getLogger("personal_db.embeddings")

_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
_EMBEDDING_DIMENSIONS = 1536
_MAX_RETRIES = 3
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed")

_token_provider = None


def _get_token_provider():
    global _token_provider
    if _token_provider is None:
        _token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), _COGNITIVE_SERVICES_SCOPE
        )
    return _token_provider


def get_embedding(text: str) -> list[float]:
    """Call the Azure OpenAI embeddings endpoint. Raises on failure — callers
    that want fire-and-forget semantics should go through schedule_embedding.
    """
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    url = f"{endpoint}/openai/deployments/{deployment}/embeddings?api-version={api_version}"

    api_key = os.environ.get("AZURE_OPENAI_KEY")
    headers = {"api-key": api_key} if api_key else {"Authorization": f"Bearer {_get_token_provider()()}"}

    response = httpx.post(url, headers=headers, json={"input": text}, timeout=30.0)
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def _index_key(collection: str, doc_id: str) -> str:
    return f"{collection}:{doc_id}"


def _do_embed_and_index(collection: str, doc_id: str, snippet: str) -> None:
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            vector = get_embedding(snippet)
            container = cosmos_service.get_search_index_container()
            container.upsert_item(
                {
                    "id": _index_key(collection, doc_id),
                    "collection": collection,
                    "docId": doc_id,
                    "snippet": snippet[:500],
                    "vector": vector,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return
        except Exception as e:  # noqa: BLE001 - genuinely want to retry any failure mode
            last_error = e
            if attempt < _MAX_RETRIES:
                time.sleep(2**attempt)

    # Dead-letter: don't let a failed embedding silently vanish. At personal
    # scale, a loud log line (visible in Claude Desktop's MCP log per plan
    # §11) that names exactly what to re-run is enough of a dead-letter.
    logger.error(
        "embedding failed after %d attempts for %s/%s -- rerun via reembed_collection('%s'): %s",
        _MAX_RETRIES,
        collection,
        doc_id,
        collection,
        last_error,
    )


def schedule_embedding(collection: str, doc_id: str, snippet: str) -> None:
    """Fire-and-forget: queue the embed+index call on a background thread so
    the calling tool (upsert_document) returns immediately.
    """
    _executor.submit(_do_embed_and_index, collection, doc_id, snippet)


def schedule_deindex(collection: str, doc_id: str) -> None:
    def _do_delete() -> None:
        container = cosmos_service.get_search_index_container()
        try:
            container.delete_item(item=_index_key(collection, doc_id), partition_key=collection)
        except Exception as e:  # noqa: BLE001
            logger.error("failed to de-index %s/%s: %s", collection, doc_id, e)

    _executor.submit(_do_delete)


def build_snippet(schema: dict, doc: dict) -> str | None:
    embed_fields = schema.get("embed_fields") or []
    if not embed_fields:
        return None
    parts = [str(doc[f]) for f in embed_fields if f in doc and doc[f] is not None]
    return " | ".join(parts) if parts else None
