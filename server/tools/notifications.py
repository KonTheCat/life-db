from fastmcp import FastMCP

from services import notifications as notifications_service


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def schedule_notification(
        due_at: str,
        message: str,
        lead_minutes: int = 0,
        item_ref: dict | None = None,
        channel: str = "telegram",
    ) -> dict:
        """Schedule a reminder.

        due_at: ISO 8601 UTC timestamp — the notification fires within
                roughly a minute of due_at (Service Bus scheduled delivery).
                For a relative time ("in 20 minutes", "tomorrow at 9am"),
                call get_current_time first rather than estimating now().
        item_ref: optional {"collection": ..., "docId": ...} linking this
                  reminder to a document elsewhere in the database.
        """
        return notifications_service.create_notification(
            due_at, message, lead_minutes, item_ref, channel
        )

    @mcp.tool
    def cancel_notification(id: str) -> dict:
        """Cancel a pending notification. Fails if it's already sent/failed/cancelled."""
        return notifications_service.cancel(id)

    @mcp.tool
    def list_notifications(status: str | None = None) -> list[dict]:
        """List notifications, optionally filtered by status (pending/sent/cancelled/failed)."""
        return notifications_service.list_notifications(status)

    @mcp.tool
    def send_now(id: str) -> dict:
        """Deliver a pending notification immediately, bypassing its due_at."""
        doc = notifications_service.get_by_id(id)
        if doc["status"] != "pending":
            raise ValueError(f"notification '{id}' is '{doc['status']}', not pending")
        return notifications_service.dispatch_one(doc)
