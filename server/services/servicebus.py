import json
import os
from datetime import datetime
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import MessageNotFoundError


@lru_cache(maxsize=1)
def _client() -> ServiceBusClient:
    namespace = os.environ["SERVICE_BUS_NAMESPACE"]
    return ServiceBusClient(namespace, credential=DefaultAzureCredential())


def _queue_name() -> str:
    return os.environ["SERVICE_BUS_QUEUE_NAME"]


def schedule_wakeup(notification_id: str, due_at: str) -> int:
    """Schedule a Service Bus message to become available at due_at.

    Returns the sequence number, which is what cancel_wakeup needs later.
    """
    scheduled_time = datetime.fromisoformat(due_at)
    message = ServiceBusMessage(json.dumps({"notification_id": notification_id}))
    with _client() as client, client.get_queue_sender(_queue_name()) as sender:
        sequence_numbers = sender.schedule_messages(message, scheduled_time)
        return sequence_numbers[0]


def cancel_wakeup(sequence_number: int | None) -> None:
    """Best-effort cancel. The dispatcher's own pending-status check is the
    real guard against a stale message doing anything, so failures here
    (message already fired, already expired, etc.) are swallowed.
    """
    if sequence_number is None:
        return
    try:
        with _client() as client, client.get_queue_sender(_queue_name()) as sender:
            sender.cancel_scheduled_messages(sequence_number)
    except MessageNotFoundError:
        pass


def receive_and_handle(handler, wait_seconds: int = 10) -> dict | None:
    """Receive (peek-lock) a single message if one is available and run
    handler(body_dict) against it, all within one receiver lifetime so the
    lock stays valid for the complete/abandon call.

    Completes the message on success, abandons it (letting Service Bus
    redeliver / eventually dead-letter it) if handler raises. Returns None if
    no message was available -- e.g. another job execution already won the
    race for it, which is expected and not an error.
    """
    with _client() as client, client.get_queue_receiver(_queue_name()) as receiver:
        messages = receiver.receive_messages(max_message_count=1, max_wait_time=wait_seconds)
        if not messages:
            return None
        message = messages[0]
        body = json.loads(str(message))
        try:
            result = handler(body)
        except Exception:
            receiver.abandon_message(message)
            raise
        receiver.complete_message(message)
        return result
