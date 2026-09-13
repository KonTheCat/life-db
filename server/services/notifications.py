import uuid
from datetime import datetime, timedelta, timezone

from services import cosmos as cosmos_service
from services import servicebus as servicebus_service
from services import telegram as telegram_service

MAX_DELIVERY_ATTEMPTS = 5
RETRY_BACKOFF_MINUTES = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_notification(
    due_at: str,
    message: str,
    lead_minutes: int = 0,
    item_ref: dict | None = None,
    channel: str = "telegram",
) -> dict:
    if channel != "telegram":
        raise ValueError("only the 'telegram' channel is supported right now")
    doc = {
        "id": str(uuid.uuid4()),
        "item_ref": item_ref,
        "due_at": due_at,
        "lead_minutes": lead_minutes,
        "message": message,
        "status": "pending",
        "channel": channel,
        "attempts": 0,
        "sb_sequence_number": None,
        "created_at": _now_iso(),
    }
    container = cosmos_service.get_notifications_container()
    container.create_item(doc)
    try:
        doc["sb_sequence_number"] = servicebus_service.schedule_wakeup(doc["id"], due_at)
    except Exception:
        # Nothing will ever wake this notification up -- don't leave an
        # orphaned record behind.
        container.delete_item(item=doc["id"], partition_key="pending")
        raise
    container.replace_item(item=doc["id"], body=doc)
    return doc


def get_by_id(id: str) -> dict:
    container = cosmos_service.get_notifications_container()
    results = list(
        container.query_items(
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": id}],
            enable_cross_partition_query=True,
        )
    )
    if not results:
        raise ValueError(f"no notification '{id}'")
    return results[0]


def _move_to_status(doc: dict, new_status: str, **extra) -> dict:
    """`status` is the container's partition key, so changing it means
    delete-then-recreate rather than an in-place replace.
    """
    container = cosmos_service.get_notifications_container()
    container.delete_item(item=doc["id"], partition_key=doc["status"])
    doc = dict(doc)
    doc["status"] = new_status
    doc.update(extra)
    container.create_item(doc)
    return doc


def cancel(id: str) -> dict:
    doc = get_by_id(id)
    if doc["status"] != "pending":
        raise ValueError(f"notification '{id}' is '{doc['status']}', not pending")
    servicebus_service.cancel_wakeup(doc.get("sb_sequence_number"))
    return _move_to_status(doc, "cancelled", cancelled_at=_now_iso())


def list_notifications(status: str | None = None) -> list[dict]:
    container = cosmos_service.get_notifications_container()
    if status is not None:
        return list(container.query_items(query="SELECT * FROM c", partition_key=status))
    return list(container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))


def dispatch_one(doc: dict) -> dict:
    """Attempt delivery once.

    Success moves the notification to 'sent'. Failure increments its attempt
    count and moves it to 'failed' once MAX_DELIVERY_ATTEMPTS is reached;
    otherwise it stays 'pending' and a new Service Bus wakeup is scheduled a
    short backoff out, since there's no cron pass left to retry it later —
    one bad delivery never loops forever, but it also isn't given up on
    after a single transient error.
    """
    try:
        telegram_service.send_message(doc["message"])
    except Exception as e:  # noqa: BLE001 - any delivery failure is retryable the same way
        attempts = doc.get("attempts", 0) + 1
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            return _move_to_status(
                doc, "failed", attempts=attempts, last_error=str(e), failed_at=_now_iso()
            )
        container = cosmos_service.get_notifications_container()
        doc = dict(doc)
        doc["attempts"] = attempts
        doc["last_error"] = str(e)
        retry_at = (datetime.now(timezone.utc) + timedelta(minutes=RETRY_BACKOFF_MINUTES)).isoformat()
        doc["sb_sequence_number"] = servicebus_service.schedule_wakeup(doc["id"], retry_at)
        container.replace_item(item=doc["id"], body=doc)  # still 'pending' -> same partition
        return doc
    return _move_to_status(doc, "sent", sent_at=_now_iso())


def handle_wakeup(notification_id: str) -> dict:
    """Entry point for the dispatcher job: called once per Service Bus
    message. If the notification isn't 'pending' anymore (already
    sent/cancelled/failed, or handled by an earlier retry of this same
    message), this is a no-op -- the message and the Cosmos record aren't
    updated transactionally, so a stale message doing nothing is expected,
    not an error.
    """
    doc = get_by_id(notification_id)
    if doc["status"] != "pending":
        return {"id": notification_id, "status": doc["status"], "action": "skipped"}
    return dispatch_one(doc)
