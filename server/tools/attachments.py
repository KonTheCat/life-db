import base64

from fastmcp import FastMCP

from services import storage as storage_service


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def upload_attachment(
        collection: str,
        doc_id: str,
        filename: str,
        content_base64: str,
        content_type: str | None = None,
    ) -> dict:
        """Upload a file attachment to a document. content_base64: file bytes, base64-encoded."""
        content = base64.b64decode(content_base64)
        return storage_service.upload_attachment(collection, doc_id, filename, content, content_type)

    @mcp.tool
    def list_attachments(collection: str, doc_id: str) -> list[dict]:
        """List attachment metadata (filename, content_type, size, uploaded_at) for a document."""
        return storage_service.list_attachments(collection, doc_id)

    @mcp.tool
    def get_attachment_link(collection: str, doc_id: str, attachment_id: str, expiry_minutes: int = 15) -> str:
        """Get a time-limited download URL for an attachment (default 15 min expiry).
        Never returns file content inline or an unexpiring URL.
        """
        return storage_service.get_attachment_link(collection, doc_id, attachment_id, expiry_minutes)

    @mcp.tool
    def delete_attachment(collection: str, doc_id: str, attachment_id: str) -> dict:
        """Delete an attachment from a document."""
        return storage_service.delete_attachment(collection, doc_id, attachment_id)
