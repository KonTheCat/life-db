import os
import uuid
from datetime import datetime, timedelta, timezone

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

from services import cosmos as cosmos_service

CONTAINER_NAME = "attachments"


def _get_service_client() -> BlobServiceClient:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn_str:
        return BlobServiceClient.from_connection_string(conn_str)
    return BlobServiceClient(os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential())


def _get_container_client():
    client = _get_service_client()
    container = client.get_container_client(CONTAINER_NAME)
    if not container.exists():
        container.create_container()
    return container


def _get_doc(collection: str, doc_id: str) -> dict:
    container = cosmos_service.get_or_create_collection_container(collection)
    return container.read_item(item=doc_id, partition_key=doc_id)


def upload_attachment(
    collection: str, doc_id: str, filename: str, content: bytes, content_type: str | None = None
) -> dict:
    attachment_id = str(uuid.uuid4())
    blob_name = f"{collection}/{doc_id}/{attachment_id}-{filename}"
    _get_container_client().upload_blob(blob_name, content, content_type=content_type)

    metadata = {
        "id": attachment_id,
        "filename": filename,
        "content_type": content_type,
        "size": len(content),
        "blob_name": blob_name,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    doc_container = cosmos_service.get_or_create_collection_container(collection)
    doc = _get_doc(collection, doc_id)
    doc.setdefault("attachments", []).append(metadata)
    doc_container.replace_item(item=doc_id, body=doc)
    return metadata


def list_attachments(collection: str, doc_id: str) -> list[dict]:
    return _get_doc(collection, doc_id).get("attachments", [])


def _find_attachment(collection: str, doc_id: str, attachment_id: str) -> dict:
    for a in list_attachments(collection, doc_id):
        if a["id"] == attachment_id:
            return a
    raise ValueError(f"no attachment '{attachment_id}' on {collection}/{doc_id}")


def get_attachment_link(collection: str, doc_id: str, attachment_id: str, expiry_minutes: int = 15) -> str:
    attachment = _find_attachment(collection, doc_id, attachment_id)
    service_client = _get_service_client()
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=expiry_minutes)

    account_key = getattr(getattr(service_client, "credential", None), "account_key", None)
    if account_key:
        # Local/Azurite path: shared-key SAS (Azurite doesn't support user-delegation SAS).
        sas = generate_blob_sas(
            account_name=service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=attachment["blob_name"],
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
    else:
        # Production path (plan §6/§8): user-delegation SAS via the managed
        # identity's AAD token -- no long-lived account key involved.
        delegation_key = service_client.get_user_delegation_key(now, expiry)
        sas = generate_blob_sas(
            account_name=service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=attachment["blob_name"],
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )

    return f"{service_client.url}{CONTAINER_NAME}/{attachment['blob_name']}?{sas}"


def delete_attachment(collection: str, doc_id: str, attachment_id: str) -> dict:
    attachment = _find_attachment(collection, doc_id, attachment_id)
    _get_container_client().delete_blob(attachment["blob_name"])

    doc_container = cosmos_service.get_or_create_collection_container(collection)
    doc = _get_doc(collection, doc_id)
    doc["attachments"] = [a for a in doc.get("attachments", []) if a["id"] != attachment_id]
    doc_container.replace_item(item=doc_id, body=doc)
    return {"deleted": attachment_id}
