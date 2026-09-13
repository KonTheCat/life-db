# Notification delivery: cron dispatcher → Service Bus scheduled messages

End-to-end plan for replacing the poll-based `notification-dispatcher` Container Apps Job
(cron `*/5 * * * *`, scans `_notifications` for anything due) with an event-driven design:
Service Bus (Basic tier) holds one scheduled message per pending notification, and a
Container Apps Job scales from zero on the queue via KEDA the moment a message becomes
available. Cosmos `_notifications` stays the source of truth for content/state; Service
Bus becomes purely the wake-up timer.

This is a full replacement, not an addition — at the end of this migration there is no
cron trigger and no polling query left anywhere (local or prod).

---

## 1. Why, and the tradeoff going in

**Why:** the cron dispatcher's resolution is bounded by its schedule (currently 5 min),
and it runs — and bills the Cosmos query — every 5 minutes forever regardless of whether
anything is due. A scheduled Service Bus message fires the job only when there's actually
work, with sub-minute latency.

**Tradeoff accepted:** more moving parts. Cosmos and Service Bus must stay in sync —
scheduling a notification means one write to Cosmos *and* one send to Service Bus;
cancelling means a Cosmos update *and* a Service Bus cancel-by-sequence-number. The job
must tolerate the message and the Cosmos record disagreeing (message fires for a
notification that was since cancelled/sent) since KEDA delivery isn't transactional with
Cosmos writes.

**Cost:** Service Bus Basic is pay-per-operation (~$0.05/million operations), no fixed
monthly base charge — consistent with the "no ongoing idle cost" bar from the original
deployment (build phase 8).

---

## 2. Target architecture

```
schedule_notification (MCP tool)
    │
    ├─► Cosmos _notifications: create doc, status=pending, due_at=..., sb_sequence_number=null
    │
    └─► Service Bus queue "notifications": send message
            body = {"notification_id": "<id>"}
            ScheduledEnqueueTimeUtc = due_at
        ◄── returns sequence_number
    └─► Cosmos _notifications: patch doc, sb_sequence_number=<seq>

cancel_notification (MCP tool)
    ├─► Service Bus: cancel_scheduled_messages([sb_sequence_number])  (best-effort)
    └─► Cosmos _notifications: status=cancelled

Container Apps Job: notification-dispatcher
    trigger: Event (KEDA azure-servicebus scaler on queue "notifications")
    on activation: receive 1 message → look up notification_id in Cosmos
                   → if status != pending: complete message, no-op (already
                     cancelled/sent/handled by an earlier attempt)
                   → else: dispatch_one() (existing Telegram-send + Cosmos
                     status transition logic, unchanged)
                   → complete the message on success; abandon (let it retry /
                     dead-letter) on failure
```

Nothing about `dispatch_one`, the Telegram send, or the Cosmos status machine
(`pending → sent|failed|cancelled`) changes. Only *what triggers a dispatch attempt for
one specific notification* changes — from "cron scans for anything due" to "a message for
this exact notification became available."

---

## 3. New Azure resource

Add `infra/12-service-bus.sh` (idempotent, same style as the rest of `infra/`):

- Namespace: `lifedb-bus`, SKU `Basic`, same `lifedb` resource group/region.
- Queue: `notifications`.
  - `--max-delivery-count 5` (mirrors existing `MAX_DELIVERY_ATTEMPTS`, though the Cosmos
    `attempts` counter remains the actual source of truth for the failed/pending decision —
    see §6).
  - `--default-message-time-to-live P14D` — Basic tier's actual ceiling (confirmed at
    implementation time: the platform rejects anything above 14 days, not "generous"/unlimited
    as originally assumed here). A reminder scheduled further than 14 days out would need a
    different mechanism; not a real constraint at personal-reminder scale, just noting the
    correction.
  - No dead-letter-specific config beyond the default DLQ that comes with the queue — a
    message that exhausts delivery count lands in `notifications/$DeadLetterQueue`, which
    is enough for `is_pending` to have already caught real double-delivery, and gives a
    place to inspect anything that genuinely fails hard.
- RBAC: grant the shared managed identity **`Azure Service Bus Data Owner`** on the
  namespace (need both send and receive/manage — Owner is simplest and mirrors the
  Contributor-role pattern used for Storage; can be tightened to separate Sender/Receiver
  roles later if desired, but there's exactly one identity, one queue, no reason to split
  it yet).

Update `infra/00-vars.sh`:
```bash
export SERVICE_BUS_NAMESPACE="lifedb-bus"
export SERVICE_BUS_QUEUE="notifications"
```

No Key Vault secret needed — Service Bus auth goes through the same
`DefaultAzureCredential` / managed identity path as everything else (AAD-first, per the
project's existing convention), not a connection string.

---

## 4. Code changes

### 4.1 `server/services/servicebus.py` (new)

Thin wrapper, mirrors the shape of `services/telegram.py` / `services/cosmos.py`:
- `_client()` — `ServiceBusClient(fully_qualified_namespace, credential=DefaultAzureCredential())`, lru-cached.
- `schedule_wakeup(notification_id: str, due_at: str) -> int` — sends one message with
  `ScheduledEnqueueTimeUtc` parsed from `due_at`, body `{"notification_id": notification_id}`,
  returns the sequence number.
- `cancel_wakeup(sequence_number: int) -> None` — calls `cancel_scheduled_messages`;
  swallows "already gone" errors (message may have already fired or expired) since
  cancellation is best-effort — the job's own pending-check in §2 is the real guard against
  a stale message doing anything.
- `receive_and_handle(handler, wait_seconds=10) -> dict | None` — peek-lock receive of a
  single message, calls `handler(body_dict)` while the lock is held, completes on success /
  abandons on exception, returns `None` if nothing was available (another execution already
  won the race). Used by the job entrypoint directly, both locally and deployed — see §5.2,
  this ended up being simpler than trying to have KEDA hand the payload to the container.

### 4.2 `server/services/notifications.py`

- `create_notification`: after `create_item`, call `servicebus_service.schedule_wakeup(id, due_at)`
  and patch the doc with the returned `sb_sequence_number`. If the Service Bus send fails,
  delete the just-created Cosmos doc and re-raise — don't leave an orphaned notification
  that nothing will ever wake up for.
- `cancel`: call `servicebus_service.cancel_wakeup(doc["sb_sequence_number"])` before
  `_move_to_status(doc, "cancelled", ...)` (best-effort — log and continue on failure,
  since the pending-check in the job entrypoint is the backstop).
- `dispatch_due()` (the cron full-table scan) is deleted — nothing calls it once the cron
  trigger is gone. `dispatch_one` is kept as-is; it's reused by both the new job entrypoint
  and `send_now`.
- New `handle_wakeup(notification_id: str) -> dict`: fetch by id, if `status != "pending"`
  return a no-op result (`{"id": ..., "status": doc["status"], "action": "skipped"}`),
  else call `dispatch_one(doc)`. This is the function the new dispatcher entrypoint calls.

### 4.3 `server/tools/notifications.py`

No signature changes to any tool — `schedule_notification`, `cancel_notification`,
`list_notifications`, `send_now` all keep working exactly as documented. Only their
docstring for `schedule_notification` changes: "fires once due_at has passed and the
dispatcher next runs (every few minutes)" → "fires within roughly a minute of due_at."

### 4.4 `dispatcher/run.py`

Replace the "scan everything due" body with "receive and handle one message, if any":

```python
def main() -> None:
    result = servicebus_service.receive_and_handle(
        lambda body: notifications_service.handle_wakeup(body["notification_id"])
    )
    if result is None:
        print("no message available (lost the race to another execution) -- exiting cleanly")
        return
    print(f"{result['id']}: {result['status']}")
```

Container Apps' event-driven job scaling only controls *how many executions start*, not
payload delivery — there's no env var the platform hands you with the message body. So the
container does the receive itself, same code path locally and deployed. This resolves the
open question in the original draft of §5.2/§8 without needing a spike: it works because
the job's only responsibility per execution is "receive one message, handle it, exit" —
KEDA's job is just deciding when and how many executions to start.

---

## 5. Container Apps Job: Schedule → Event trigger

### 5.1 Job definition changes (`infra/11-container-app-job.sh`)

- `--trigger-type Event` instead of `Schedule`; drop `--cron-expression`.
- Add a scale rule bound to the Service Bus queue:
  ```bash
  az containerapp job update \
    --name "$CONTAINER_APP_JOB" --resource-group "$RESOURCE_GROUP" \
    --scale-rule-name sb-notifications \
    --scale-rule-type azure-servicebus \
    --scale-rule-metadata "namespace=$SERVICE_BUS_NAMESPACE" "queueName=$SERVICE_BUS_QUEUE" "messageCount=1" \
    --scale-rule-identity "$IDENTITY_ID" \
    --min-executions 0 --max-executions 5 \
    --polling-interval 30
  ```
  (`messageCount=1` → one job execution per message, i.e. per notification; `polling-interval 30`
  is KEDA's queue-depth check cadence — the actual bound on "how fast can this possibly fire.")
- Keep `--replica-timeout`, `--replica-retry-limit`, `--cpu/--memory` as-is.

### 5.2 The receive step — the part that needs a spike

Container Apps' event-driven jobs scale *execution count* off queue depth; they don't
inject the message body into the container automatically. The container itself must
receive the message once it starts. So `dispatcher/run.py` (§4.4) actually needs to *do
the receive*, not read `NOTIFICATION_ID` from the environment:

```python
def main() -> None:
    msg = servicebus_service.receive_one(wait_seconds=10)
    if msg is None:
        print("no message available (lost the race to another execution) — exiting cleanly")
        return
    body = json.loads(str(msg))
    try:
        result = notifications_service.handle_wakeup(body["notification_id"])
        print(f"{result['id']}: {result['status']}")
        servicebus_receiver.complete_message(msg)
    except Exception:
        servicebus_receiver.abandon_message(msg)
        raise
```

This is more correct than an env-var handoff (Container Apps Jobs' KEDA integration is
documented for *scaling*, not for payload delivery) and it's also self-correcting: if two
executions start for one message (shouldn't happen with `messageCount=1`/`max-executions`
tight, but Basic tier queues are at-least-once), the loser just finds nothing to receive
and exits. **Flag this as the one section of this plan to re-verify against current Azure
docs/behavior at implementation time** — Container Apps' event-driven job semantics have
had platform changes over the past year and it's worth confirming `min-executions 0` +
`azure-servicebus` scale rule + explicit receive-in-container is still the recommended
shape before building against it.

### 5.3 Managed identity

`servicebus_service` uses `DefaultAzureCredential`, so the identity's data-plane RBAC
(§3) covers both the app's send-on-schedule path and the job's receive path — no extra
role needed beyond the one namespace-level assignment.

---

## 6. Retry semantics — what changes, what doesn't

Today: `dispatch_one` increments `attempts` in Cosmos and gives up at
`MAX_DELIVERY_ATTEMPTS = 5`, moving to `failed`; a `pending` doc with `attempts < 5` just
sits there until the next 5-minute cron pass retries it.

With Service Bus: there is no "next pass" for a message that's been completed. So a
transient Telegram failure needs the job to explicitly re-schedule a retry rather than
relying on cron to eventually revisit it:

- `dispatch_one`, on a retryable failure with `attempts < MAX_DELIVERY_ATTEMPTS`: after
  incrementing `attempts` in Cosmos (unchanged), also call
  `servicebus_service.schedule_wakeup(id, due_at=<now + backoff>)` and store the new
  `sb_sequence_number` — a short fixed backoff (e.g. 2 minutes) is enough; this system has
  no volume that would justify exponential backoff.
- On success or on hitting `MAX_DELIVERY_ATTEMPTS`, no new message is scheduled — the
  chain terminates there, same as today's `sent`/`failed` end states.
- The queue's own `max-delivery-count` (§3) becomes a second, independent safety net (a
  message that somehow gets abandoned/crashes repeatedly still eventually dead-letters)
  but the *primary* retry loop is the explicit reschedule above, not Service Bus redelivery.

---

## 7. Local dev / testing

Consistent with the project's established pattern of testing against real (cheap) Azure
resources rather than emulators (Azurite was dropped for the same reason in an earlier
phase): use the real `lifedb-bus` Basic namespace directly from local runs too, no Service
Bus emulator.

- `.env` gains `SERVICE_BUS_NAMESPACE=lifedb-bus.servicebus.windows.net` (or reuse the
  vars-file name and derive the FQDN in code).
- Local manual test loop: `uv run python dispatcher/run.py` now blocks briefly waiting to
  receive one message instead of scanning Cosmos — schedule a notification a few seconds in
  the future via the MCP tool, then run the dispatcher script by hand and confirm it
  receives, delivers via Telegram, and updates Cosmos.
- The local Windows Scheduled Task (`infra/setup-local-dispatcher-task.ps1`, already
  unregistered per the prior phase) is **not** re-registered — there's nothing left to poll
  locally either. Delete or clearly mark these two scripts as obsolete once this migration
  ships (see §9).

---

## 8. Open questions to resolve before/during implementation

1. **Container Apps event-driven job + Service Bus scale rule exact behavior** (§5.2) —
   confirm current docs for whether `min-executions 0`/`azure-servicebus` scale rules still
   require the container to do its own receive, and what `polling-interval` actually bounds
   in practice today.
2. **Basic tier queue limits** — confirm current max scheduled-message TTL and any cap on
   the number of outstanding scheduled (not-yet-enqueued) messages; personal-scale volume
   makes this unlikely to matter, but worth a one-line confirmation against current docs
   rather than the plan's recollection.
3. Whether `Azure Service Bus Data Owner` is actually the right granularity, or whether
   splitting Sender (app) / Receiver (job) roles is worth the extra RBAC line — default to
   Owner for v1, revisit only if it matters.

---

## 9. Dev/prod separation

**Service Bus:** Basic tier has no topics/subscriptions (Standard+ only), and pub/sub
isn't the right shape here anyway — one producer, one consumer. Mirror the existing
Cosmos `personaldb` / `personaldb-dev` split with **two queues in the same namespace**:
`notifications` (prod) and `notifications-dev` (local testing). Add
`SERVICE_BUS_QUEUE_DEV="notifications-dev"` to `infra/00-vars.sh`, create both queues in
`infra/12-service-bus.sh`, and have `servicebus.py` pick the queue name the same way
`cosmos.py` already picks `COSMOS_DATABASE` vs `COSMOS_DEV_DATABASE` (env-driven, based on
whether the process is running against dev or prod config). The Container Apps Job's scale
rule (§5.1) points at the prod queue only — local dev never runs the deployed job, it runs
`dispatcher/run.py` by hand against the dev queue.

**Storage:** existing gap, not introduced by this migration — [storage.py](server/services/storage.py)
hardcodes `CONTAINER_NAME = "attachments"` with no dev/prod distinction, so local testing
and prod currently share the same blob container on `lifedbstor`. Worth fixing
independently of the Service Bus work (same pattern as the other two: a second container,
`attachments-dev`, selected the same way `COSMOS_DATABASE`/`COSMOS_DEV_DATABASE` is today).
Not required for this plan to ship, but flagged here since it's the same class of gap and
came up in the same conversation — do it as a small standalone change rather than bundling
it into the Service Bus cutover.

---

## 10. Migration / cutover steps

1. Provision `infra/12-service-bus.sh`, run it, add RBAC (§3).
2. Land the code changes (§4) behind no feature flag — this is a full replacement, and
   there's no meaningful "both paths active" state worth supporting given single-user
   scale and the willingness to just redeploy if something's wrong.
3. Update `infra/11-container-app-job.sh` to the Event trigger + scale rule (§5).
4. Any notifications already `pending` at cutover time predate Service Bus and have no
   `sb_sequence_number` — one-time backfill script: for each `pending` doc missing
   `sb_sequence_number`, call `schedule_wakeup` and patch it in, same as `create_notification`
   does going forward. Run this once, by hand, right after deploying the new code.
5. `az deploy.sh` equivalent rollout (rebuild image, update both the app and the job, per
   existing `infra/deploy.sh`).
6. Verify end-to-end: schedule a real notification a minute out, confirm Telegram delivery,
   confirm the job execution shows in `az containerapp job execution list`, confirm no cron
   trigger remains (`az containerapp job show` → trigger type `Event`).
7. Update `life-db-plan.md`'s architecture diagram and resource table to reflect Service
   Bus replacing the cron dispatcher (this file can then be folded into it or kept
   standalone as a dated addendum — your call at that point).
8. Delete `dispatch_due` and any now-dead cron-era code; mark
   `infra/run-dispatcher-local.ps1` / `infra/setup-local-dispatcher-task.ps1` as obsolete or
   remove them.
