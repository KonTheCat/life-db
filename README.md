# life-db (personal-db)

A personal MCP server: schema-driven documents, semantic recall, notifications,
and file attachments — for Claude Desktop/Code to use as a single "life
database" over an Azure backend.

## Approach

The core idea: **the AI itself defines the data model.** There's no fixed set of
collections (no hardcoded "tasks" or "notes" table) — the AI calls `create_collection`
with a name and field schema whenever it decides a new kind of thing needs storing,
and the server provisions a real Cosmos container for it on the spot. This makes the
system open-ended (it grows whatever structure the user's life actually needs) but
it also means the AI could easily create `tasks`, then later `todo`, then `todos`,
duplicating the same concept under different names. To prevent that:

- `_schemas` in Cosmos is the **authoritative registry of every collection that
  exists**, keyed by collection name — not just a cache, the actual source of truth
  the server checks before anything is created.
- `create_collection` looks the name up in `_schemas` first and **hard-fails if it's
  already taken**, rather than silently reusing or renaming it.
- `list_collections` and `get_schema` are meant to be called by the AI *before*
  `create_collection`, so it can check "does something like this already exist?"
  and reuse or extend an existing collection instead of creating a near-duplicate.
- `update_schema` / `migrate_schema` exist precisely so an existing collection can
  grow new fields instead of the AI reaching for a fresh collection when the old
  one is "close enough."

In short: collection creation is a deliberate, checked, one-way door (see
`server/tools/schema.py`), not an implicit side effect of storing a document — the
schema registry is what keeps the AI from fragmenting the same data across
lookalike collections over time.

- **FastMCP server** (`server/main.py`) exposes tools over MCP. Transport is picked
  at runtime via `MCP_TRANSPORT`:
  - `stdio` (default) — Claude Desktop/Code launches the server as a subprocess.
    No network exposure, no auth, zero extra setup. This is the normal local mode.
  - `streamable-http` — used in production (Azure Container Apps), guarded by a
    static bearer token. Same code path either way; only the transport flips.
- **Cosmos DB for NoSQL** (serverless) is the store. `_schemas` holds one document
  per user-defined collection (field definitions, version) and doubles as the
  collection registry described above; `_notifications` holds reminder records.
  Every other collection (tasks, notes, whatever the AI defines) is a Cosmos
  container created on demand by the schema tools, validated strictly against its
  schema on every write.
- **Semantic search** uses Cosmos's native vector index — documents get embedded
  (Azure OpenAI `text-embedding-3-small`) on write and are searchable via a
  cross-collection `_search_index` companion container, so recall doesn't require
  knowing which collection something lives in.
- **Notifications** are event-driven: `schedule_notification` writes to
  `_notifications` *and* sends a time-scheduled message to an Azure Service Bus
  queue. A Container Apps Job (`dispatcher/run.py`) scales from zero via KEDA the
  moment a message is due, re-checks the Cosmos record (in case it was cancelled
  since scheduling), and delivers via a Telegram bot. See
  [service-bus-notifications-plan.md](service-bus-notifications-plan.md) for the
  full design — there is no polling/cron anywhere in the current design.
- **Attachments** live in Azure Blob Storage, keyed by
  `{collection}/{docId}/{attachmentId}-{filename}`; metadata sits on the parent
  document. Downloads are always short-lived SAS links, never inline content.
- **Secrets & auth**: prefer Azure AD / managed identity (`DefaultAzureCredential`)
  over static keys everywhere the SDK supports it — Cosmos, Storage, Key Vault,
  OpenAI. Key Vault is only consulted when `MCP_TRANSPORT != stdio`; local `stdio`
  dev reads everything from `.env`.
- **Deployment**: one container image (`Dockerfile`), two entrypoints — the
  `mcp-server` App Service Web App (Always On, no cold start) and the
  event-triggered `notification-dispatcher` Container Apps Job — sharing the
  same image and managed identity. Infra is plain Azure CLI scripts under
  [infra/](infra/) (`00`–`13`, run in order; `infra/deploy.sh` rebuilds the
  image and rolls it out to both), not Terraform/Bicep.

See [life-db-plan.md](life-db-plan.md) for the full original build plan (resource
list, RBAC roles, tool surface) and
[service-bus-notifications-plan.md](service-bus-notifications-plan.md) for the
notification delivery redesign.

### Layout

```
server/
  main.py                 MCP entrypoint, tool registration, transport switch
  services/                Azure/Telegram clients (cosmos, storage,
                            embeddings, keyvault, servicebus, telegram, auth)
  tools/                   MCP tool definitions, grouped by area
                            (schema, documents, search, notifications,
                             attachments, time_tool)
dispatcher/
  run.py                   Notification dispatcher job entrypoint
                            (receives one Service Bus message, delivers, exits)
infra/                     Numbered Azure CLI provisioning scripts + deploy.sh
Dockerfile                 Single image; CMD runs the MCP server, the job
                            overrides the command to run dispatcher/run.py
```

## Local startup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

1. **Install dependencies**

   ```
   uv sync
   ```

2. **Configure environment**

   ```
   cp .env.example .env
   ```

   Fill in the values you need. For plain local `stdio` use against real Azure
   resources you'll need:
   - `az login` (used implicitly via `DefaultAzureCredential` for Cosmos,
     Storage, and Azure OpenAI — no keys needed unless you set `COSMOS_KEY` /
     `AZURE_OPENAI_KEY` explicitly).
   - `COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME` (a dev database, not prod).
   - `AZURE_STORAGE_ACCOUNT_URL`, or set
     `AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true` to run fully
     offline against [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite)
     instead (note: Azurite falls back to shared-key SAS since it doesn't
     support user-delegation SAS).
   - `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` for
     embeddings — optional if you don't need semantic search locally.
   - `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional, only needed to test
     notification delivery.
   - `SERVICE_BUS_NAMESPACE` / `SERVICE_BUS_QUEUE_NAME` — point at the `-dev`
     queue, not prod, for local notification scheduling tests.
   - Leave `MCP_TRANSPORT` unset/`stdio` for local use — no bearer token or
     Key Vault needed.

3. **Run the server directly** (sanity check outside Claude)

   ```
   uv run python server/main.py
   ```

   It will idle waiting for an MCP client on stdio; Ctrl+C to stop.

4. **Point Claude Desktop/Code at it** — add to your MCP client config
   (`claude_desktop_config.json` or equivalent):

   ```json
   {
     "mcpServers": {
       "personal-db": {
         "command": "uv",
         "args": ["run", "--directory", "/absolute/path/to/life-db", "python", "server/main.py"]
       }
     }
   }
   ```

   Claude launches the server itself per conversation; no separate process to
   manage.

5. **Test the notification dispatcher locally** (optional, needs Service Bus
   configured):

   ```
   uv run python dispatcher/run.py
   ```

   Pulls one message off the queue (if any is due) and delivers it; exits
   immediately if the queue is empty ("no message available").

### Tests

```
uv run pytest
```
