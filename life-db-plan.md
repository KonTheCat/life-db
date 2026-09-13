# personal-db — End-to-End Implementation Plan

> **2026-09-13 update:** the `notification-dispatcher` job described below (Schedule
> trigger, cron poll of `_notifications`) has been replaced by an event-driven design —
> Service Bus scheduled messages + a KEDA `azure-servicebus` scale rule, `Event` trigger
> type, no polling anywhere. See [service-bus-notifications-plan.md](service-bus-notifications-plan.md)
> for the full design and migration record. The architecture/resource sections below are
> left as the historical build-phase record; treat "Schedule trigger, cron" mentions
> throughout as superseded by that doc.

Target stack: **FastMCP** (Python) server on **Azure Container Apps**, **Azure Cosmos DB for NoSQL** (serverless) as the store, **Azure Storage** (blob) for attachments, a **Container Apps Job** on a cron trigger for reminder dispatch, and **Azure CLI scripts** as IaC (no Terraform/Bicep).

FastMCP is at v4.0.3 as of September 2026 (3.x GA'd auth/versioning/OpenTelemetry in Feb 2026; 4.0 shipped a new protocol engine Aug 31, 2026 alongside the MCP 2026-07-28 spec — most 3.x code upgrades without changes). Build against 4.x from the start.

---

## 1. Architecture

```
                          ┌─────────────────────────────┐
  Claude (Desktop/web/    │  Container Apps Environment  │
  Code) ── HTTPS/MCP ───► │  ┌────────────────────────┐  │
  (streamable-http,       │  │ Container App:          │  │
   bearer token)          │  │  mcp-server (FastMCP)    │  │
                          │  │  min replicas 0-1        │  │
                          │  └───────────┬─────────────┘  │
                          │              │                │
                          │  ┌───────────▼─────────────┐  │
                          │  │ Container Apps Job:      │  │
                          │  │  notification-dispatcher │  │
                          │  │  (Schedule trigger, cron)│  │
                          │  └───────────┬─────────────┘  │
                          └──────────────┼────────────────┘
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
        Cosmos DB (NoSQL,       Storage Account (Blob)     Key Vault
        serverless)             — attachments               — secrets
        - _schemas
        - _notifications                                   Entra ID App Reg
        - <dynamic per-collection>                          — Graph delegated
        - vector index per collection                         auth (M365
                                                                calendar/contacts)
```

Both compute pieces (the always-on server and the scheduled job) live in the **same Container Apps Environment**, share the **same container image**, and use the **same user-assigned managed identity** — the job just runs a different entrypoint/command against the image.

---

## 2. Azure resources

| Resource | Purpose | Notes |
|---|---|---|
| Resource Group | container for everything | e.g. `rg-personal-db` |
| Azure Container Registry (Basic) | hold the built image | `az acr build` for CI-less builds |
| Log Analytics Workspace | Container Apps logs | required by the Container Apps env |
| Container Apps Environment | hosts the app + the job | one environment, `Consumption` workload profile |
| Container App: `mcp-server` | the FastMCP server, HTTP ingress | scale 0–1 or 1–1 (see §14) |
| Container Apps Job: `notification-dispatcher` | scans `_notifications`, sends due reminders | trigger type `Schedule`, cron expression |
| Cosmos DB account (NoSQL API, **serverless** capacity mode) | primary data store | serverless has no per-container throughput to manage and no fixed container-count cap (that 25-container ceiling only applies to shared-throughput databases) — good fit for a schema-driven, containers-created-on-demand design |
| Azure OpenAI account (`S0`) + `text-embedding-3-small` deployment | embeddings for semantic recall | provisioned in phase 4 as `lifedb-openai` (added to the resource set; wasn't broken out as its own row in the original plan) |
| Storage Account (StorageV2, Standard LRS) | blob container for attachments | `lifedbstor` already existed in `lifedb` RG, used as-is; private container, access via user-delegation SAS (AAD) |
| Key Vault | secrets: Cosmos key (if not using AAD auth), Graph client secret + refresh token, MCP bearer token, storage connection info | Container App reads via managed identity, not env-baked secrets |
| User-assigned Managed Identity | shared by `mcp-server` and the job | RBAC roles below |
| Entra ID App Registration | Microsoft Graph delegated access (calendar + contacts) | see §7 |

RBAC roles to assign to the managed identity:
- Cosmos DB Built-in Data Contributor (data-plane role, assigned via `az cosmosdb sql role assignment create` — the control-plane `Contributor` role does **not** grant data access)
- **Cosmos DB Operator (ARM/control-plane role)** — needed *in addition* to the data-plane role above. Discovered during phase 3: Cosmos DB's AAD data-plane RBAC explicitly cannot create/delete containers or databases (only item-level CRUD), even with `containers/*` in the data-plane role's dataActions — see [aka.ms/cosmos-native-rbac](https://aka.ms/cosmos-native-rbac). `create_collection`'s dynamic container creation therefore goes through the ARM management SDK (`azure-mgmt-cosmosdb`), which needs this ARM role. Locally this worked for free under subscription Owner; the deployed managed identity will need it assigned explicitly.
- Storage Blob Data Contributor on the storage account
- Key Vault Secrets **Officer** (not just User) on the vault -- the Graph token cache writes its rotated refresh token back to Key Vault on every silent renewal (§7), so read-only access isn't enough; found by testing the deployed server end-to-end
- Cognitive Services OpenAI User on the Azure OpenAI account (embeddings)

---

## 3. Data model (Cosmos DB)

**Database:** `personaldb`

**System containers** (fixed, created at provision time):
- `_schemas` — one document per collection, holds the current schema version + field definitions + which fields are embedded. Partition key `/collectionName`.
- `_notifications` — reminder records, decoupled from source documents per the original design. Partition key `/status` (small, bounded cardinality: `pending` / `sent` / `cancelled` — good for the dispatcher's hot query path) with a composite index on `(status, due_at)` for the "what's due" scan.

**Dynamic collections**: each user-defined collection (tasks, notes, whatever gets added later) is its own Cosmos container, created on demand by the schema tool. Partition key `/id` is the simplest default for a single-user personal system with no natural high-cardinality access pattern — revisit only if a specific collection grows large enough that cross-partition queries become a real cost (unlikely at personal scale).

**Vector search**: use Cosmos DB for NoSQL's native vector index rather than a separate vector store (Azure AI Search, etc.) — one less service, embeddings live next to the data. Concretely:
- Index type: **`quantizedFlat`** or **`diskANN`**, not `flat`. `flat` caps at 505 dimensions, which rules out standard embedding models; `quantizedFlat`/`diskANN` support up to 4096. Be aware both require ~1,000 indexed vectors before the quantization is actually doing anything — below that, Cosmos just full-scans, which is completely fine at personal-database scale, just note it so you're not surprised RU cost doesn't drop until a collection has real volume.
- Vector search isn't supported on shared-throughput databases, which is moot here since the whole account is serverless with per-container (not shared) allocation.
- Store the embedding as a `vector` field on the document itself (per the original design's "every document gets embedded"), plus a lightweight `_search_index` companion container if you want a single cross-collection query surface rather than fanning a query out to every container — recommended, since the whole point of semantic recall is not needing to know which collection to look in. `_search_index` documents: `{id, collection, docId, snippet, vector, updated_at}`.

**Embedding model**: Azure OpenAI `text-embedding-3-small` (1536 dims, or truncate via the API's native dimensionality parameter if you want to trim cost/storage — not required to fit under the vector-index limits since you're on quantizedFlat/diskANN). Keep the embedding call in the write path but genuinely non-blocking (fire-and-forget with a retry/dead-letter, not just wrapped in try/except) per the "permissive failure on secondary effects" principle from the concept doc.

---

## 4. FastMCP server

- Transport: chosen at runtime via an `MCP_TRANSPORT` env var, both paths through the same `server/main.py`:
  - `stdio` (default when unset) — for local development, Claude Desktop launches the server itself as a subprocess per `claude_desktop_config.json`. No network exposure, no auth needed, zero Azure dependency to exercise the whole tool surface.
  - `streamable-http` — for the deployed Container App, so Claude connects over plain HTTPS to the ingress once it exists.
  This means the exact same code and tool implementations get exercised locally in real Claude Desktop conversations from day one, and only the transport flips for production.
- Auth: a static bearer token validated in FastMCP middleware (FastMCP 4's auth primitives support this directly), required only when `MCP_TRANSPORT=streamable-http`. Local `stdio` runs skip it entirely (no listening socket to protect). Store the production token in Key Vault, inject as a Container App secret, put the same value in Claude's remote-MCP connector config once you're testing the deployed server.
- Tool surface, grouped:
  - **Schema tools**: `list_collections`, `get_schema`, `create_collection`, `update_schema` (bump version), `migrate_schema` (preview + apply modes, explicit per the "no silent data loss" principle)
  - **Document tools**: `query_documents` (field-filter object: eq/gt/lt/in/contains, plus a `fields` projection param so responses stay lean), `upsert_document`, `delete_document`, `get_document`
  - **Search tool**: `search` (natural-language query, optional collection filter, returns pointers: collection/id/snippet/score — not full documents)
  - **Notification tools**: `schedule_notification`, `cancel_notification`, `list_notifications`, `send_now`
  - **Calendar tools**: `list_calendars`, `list_events`, `create_event`, `update_event`, `delete_event`, `get_free_busy`
  - **Contact tools**: `search_contacts`, `get_contact`, `create_contact`, `update_contact`, `delete_contact`
  - **Attachment tools**: `upload_attachment`, `list_attachments`, `get_attachment_link` (time-limited SAS), `delete_attachment`
- Validation: every write goes through the schema in `_schemas` before touching Cosmos — strict mode (reject unknown fields), reject missing required fields, reject type mismatches. System fields (`_schemaVersion`, `created_at`, `updated_at`, `attachments`) are stripped from user-supplied payloads and set by the server.

---

## 5. Notification / reminder system

- `_notifications` document shape: `{id, item_ref: {collection, docId} | null, due_at, lead_minutes, message, status, channel, created_at}`. `item_ref` is nullable so ad-hoc/unattached notifications work, matching the concept doc.
- `notification-dispatcher` job: Container Apps Job, **Schedule** trigger type, cron expression e.g. `*/5 * * * *`. Each run: query `_notifications` where `status = 'pending' AND due_at <= now`, dispatch, flip status to `sent` (or `failed` with a retry count — don't let one bad delivery loop forever).
- **Delivery channel: Telegram bot API.** Outbound-only, no webhook, no inbound endpoint on the Container App — a plain `POST https://api.telegram.org/bot<token>/sendMessage` call from the dispatcher job. Setup:
  1. Create a bot via [@BotFather](https://t.me/BotFather) (`/newbot`) → bot token.
  2. Message the bot once, then hit `https://api.telegram.org/bot<token>/getUpdates` to read back your numeric chat ID. One-time, done locally.
  3. Store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in Key Vault, injected into the job the same way as every other secret in §8.
  4. No SDK needed — `httpx`/`requests` is enough for `sendMessage`. Skip `python-telegram-bot`; that library is built for bots that also receive commands, which this doesn't do.
  This is fully decoupled from the Graph integration in §7 — Telegram delivery has zero dependency on the Graph auth flow, so §6 and §7 can be built/tested independently of each other.

---

## 6. File attachments

- One blob container, e.g. `attachments`, blobs keyed `{collection}/{docId}/{attachmentId}-{filename}`.
- Attachment metadata (filename, content type, size, uploaded_at) lives on the parent Cosmos document's `attachments` array (a system field, exempt from schema validation, per the concept doc).
- Downloads: generate a user-delegation SAS with a short expiry (e.g. 15 min) via the managed identity — never return blob content inline, never return an unexpiring URL.

---

## 7. Microsoft Graph integration (calendar + contacts)

This is the fiddly part because it's a **personal** Microsoft account, not a work/school tenant — application (app-only) permissions generally don't work for personal-account Calendars/Contacts; you need **delegated** permissions with a real sign-in.

1. Register an app in Entra ID: **Accounts in any organizational directory and personal Microsoft accounts** (multi-tenant + MSA), as a **public client** (`isFallbackPublicClient: true`, no client secret/certificate). Add delegated scopes: `Calendars.ReadWrite`, `Contacts.ReadWrite`, `offline_access`. Built via `infra/09-entra-app-registration.sh` (app registration is scriptable; consent is not — see step 2).
2. One-time interactive auth: **device code flow** (`server/services/graph_auth_setup.py`), not auth-code + PKCE — no redirect URI or local HTTP listener needed, just a `microsoft.com/devicelogin` code the user enters on any browser (doesn't have to be the machine running the script). Personal-account consent happens inline during this sign-in.
3. MSAL's `SerializableTokenCache`, persisted to a local file (`.graph_token_cache.json`, gitignored), holds the access + refresh tokens and handles rotation transparently on every `acquire_token_silent()` call — no manual refresh-token bookkeeping needed. Locally this file *is* the credential store; once deployed (phase 8), its contents move into Key Vault (or the cache gets re-serialized there) so the Container App can read it via managed identity instead of a local file.
4. No client secret or certificate at all, since this is a public client — one less secret to manage for a single-user personal script.

---

## 8. Security & secrets

- No secrets baked into the image or committed to the repo. Container App secrets reference Key Vault via managed identity (`az containerapp secret set --identity ... --keyvault-url ...` pattern, or mount via the Container Apps Key Vault reference feature).
- MCP bearer token, Cosmos key (if used instead of AAD data-plane auth — prefer AAD/managed identity and skip the key entirely), storage SAS-signing key material, Graph client secret, Graph refresh token — all in Key Vault.
- Prefer **Azure AD RBAC for Cosmos data-plane access** over connection-string keys wherever the SDK path supports it, so there's no long-lived Cosmos key sitting in the vault at all.

---

## 9. IaC — Azure CLI scripts

No Terraform/Bicep — a set of idempotent bash scripts using `az cli`, checked into `/infra`, run in order. Idempotency pattern: check-then-create (`az ... show &>/dev/null || az ... create ...`) so re-running a script after a partial failure doesn't error out on "already exists."

Per §13, only `05-cosmos-account.sh` runs early (phase 2, dev account for local testing); `01`–`04` and `06`–`11` don't run until phase 8 when it's time to actually deploy.

```
infra/
  00-vars.sh                 # shared variables: RG, location, names — sourced by every script
  01-resource-group.sh
  02-container-registry.sh
  03-log-analytics.sh
  04-container-apps-env.sh
  05-cosmos-account.sh       # serverless NoSQL account + database + system containers
  06-storage-account.sh      # storage account + attachments container
  07-key-vault.sh            # vault + initial secret placeholders
  08-managed-identity.sh     # UAMI + RBAC role assignments (Cosmos, Storage, KV)
  09-entra-app-registration.sh  # Graph app reg (manual consent step called out, not fully scriptable)
  10-container-app.sh        # mcp-server, ingress, secrets, identity
  11-container-app-job.sh    # notification-dispatcher, schedule trigger
  deploy.sh                  # az acr build + update revision/job — the thing you re-run on every code change
```

Hand this file structure to Claude Code as-is; it can generate each script's contents from the resource table in §2.

---

## 10. Repo layout

```
personal-db/
  server/
    main.py                # FastMCP app entrypoint (streamable-http)
    tools/
      schema.py
      documents.py
      search.py
      notifications.py
      calendar.py
      contacts.py
      attachments.py
    services/
      cosmos.py             # Cosmos client, container cache, schema validation
      embeddings.py         # Azure OpenAI embedding calls, non-blocking wrapper
      storage.py            # blob upload/SAS
      graph.py              # MSAL + Graph calls, refresh-token persistence
      auth.py               # bearer token middleware
  dispatcher/
    run.py                  # entrypoint for the Container Apps Job
  infra/                    # §9
  tests/
  Dockerfile                # single image, two entrypoints (server vs job) via CMD override
  pyproject.toml            # fastmcp, azure-cosmos, azure-storage-blob, azure-identity, msal, azure-keyvault-secrets
  .env.example
```

---

## 11. Local development

- `uv` for dependency management, `fastmcp dev server/main.py` for quick iteration with the MCP Inspector when you just want to poke a tool without opening Claude Desktop.
- **Claude Desktop as the primary local test harness.** Add an entry to `claude_desktop_config.json` that launches the server over stdio:
  ```json
  {
    "mcpServers": {
      "personal-db-local": {
        "command": "uv",
        "args": ["run", "--directory", "/absolute/path/to/personal-db", "server/main.py"],
        "env": {
          "MCP_TRANSPORT": "stdio",
          "COSMOS_ENDPOINT": "...",
          "COSMOS_KEY": "...",
          "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
          "AZURE_OPENAI_ENDPOINT": "...",
          "AZURE_OPENAI_KEY": "...",
          "TELEGRAM_BOT_TOKEN": "...",
          "TELEGRAM_CHAT_ID": "...",
          "GRAPH_CLIENT_ID": "...",
          "GRAPH_REFRESH_TOKEN": "..."
        }
      }
    }
  }
  ```
  Restart Claude Desktop after edits to pick up config/env changes; the server's stdout/stderr land in Claude Desktop's MCP log files, which is where to look when a tool call misbehaves. This lets essentially every tool (schema, documents, search, notifications-minus-cron, calendar/contacts, attachments) be exercised inside a real Claude conversation before any Container Apps resource exists.
- Point local dev at a **real serverless Cosmos dev account** rather than the Cosmos emulator — the emulator's vector search support lags the cloud service, and this project leans on vector search from day one. A second, cheap serverless account (or a separate database in the same account) for dev is simpler than fighting emulator gaps. This is the one Azure resource worth provisioning early (see §13 phase 2) — everything else in §2 can wait until deploy.
- Blob storage: local dev points straight at the real `lifedbstor` account (already existed in the `lifedb` resource group, alongside Cosmos) via AAD, rather than Azurite — one less moving part, and it means `get_attachment_link` exercises the real production code path (user-delegation SAS) from day one instead of the shared-key fallback. Azurite remains a documented fallback in `.env.example` (set `AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true`) for fully offline work.
- `.env` (loaded by `server/main.py` directly, or mirrored into the `claude_desktop_config.json` `env` block above) for local secrets, never committed; production secrets come from Key Vault only once deployed.
- The `notification-dispatcher` entrypoint (`dispatcher/run.py`) is just a script — run it manually or on a local loop/Task Scheduler during development to test reminder delivery end-to-end (including real Telegram messages) without a Container Apps Job existing yet.
- Graph's one-time interactive auth-code flow (§7 step 2) is inherently local anyway (needs a browser), so calendar/contacts tools are fully testable pre-deploy once the refresh token is in `.env`.

---

## 12. Deploy workflow

- `az acr build` builds and pushes the image straight from source — no separate CI system needed for a personal project.
- `az containerapp update --image ...` rolls a new revision of `mcp-server`.
- `az containerapp job update --image ...` updates the job's image the same way.
- Both driven by the single `infra/deploy.sh`.

---

## 13. Build phases (hand this checklist to Claude Code)

Phases 1–7 are entirely local: stdio transport, Claude Desktop as the test client (§11), a single cloud dependency (a dev Cosmos account). No Container Apps environment, registry, job, Key Vault, or managed identity gets provisioned until phase 8.

1. **Scaffold**: repo layout, `pyproject.toml`, a hello-world FastMCP server with one dummy tool. Verify it two ways: `fastmcp dev server/main.py` (Inspector, fast sanity check) and — the real bar — add it to `claude_desktop_config.json` per §11 and call the dummy tool from an actual Claude Desktop chat.
2. **Dev Cosmos account**: run just `infra/05-cosmos-account.sh` (serverless NoSQL account, `personaldb` database, `_schemas`/`_notifications` system containers) against a throwaway dev account or database. Confirm via `az cosmosdb show` / `az cosmosdb sql database show`. Everything else in `/infra` waits until phase 8.
3. **Schema engine + CRUD**: schema validation logic, `create_collection`/`update_schema`/`migrate_schema`, `query_documents`/`upsert_document`/`delete_document`/`get_document`. Test by driving these tools directly from Claude Desktop — create a collection, insert/query/update/delete documents, confirm validation rejects bad payloads.
4. **Semantic recall**: embedding service (Azure OpenAI or direct OpenAI, callable from a laptop with just an API key — no Azure infra), `_search_index` container with vector index enabled, `search` tool, force-reembed tool. Test with real natural-language queries in Claude Desktop.
5. **Notifications**: `_notifications` container, `schedule_notification`/`cancel_notification`/`list_notifications`, Telegram bot delivery (§5 setup steps 1–2 are local anyway). Run `dispatcher/run.py` manually/on a local loop and confirm a real Telegram message arrives. Defer wrapping it as a Container Apps Job with a Schedule trigger to phase 8.
6. **Graph calendar/contacts**: app registration, one-time auth-code flow (needs a browser — do it locally regardless), MSAL wrapper with refresh-token rotation persisted to `.env` for now, calendar + contact tools tested from Claude Desktop against your real calendar/contacts.
7. **Attachments**: real `lifedbstor` account + `attachments` container, upload/list/SAS-link/delete tools, tested from Claude Desktop.
8. **Harden + ship**: now provision the rest of §2 — `infra/01`–`04`, `06`–`11` (registry, Log Analytics, Container Apps environment, real storage account, Key Vault, managed identity + RBAC, `mcp-server`, `notification-dispatcher` job with its cron Schedule trigger). Move every secret from `.env` into Key Vault, flip `MCP_TRANSPORT` to `streamable-http`, add bearer-token auth, run `infra/deploy.sh`, connect the deployed URL as a remote MCP server in Claude, and smoke-test the full tool surface end to end against production infra — the same test scripts/conversations used in phases 3–7 should now pass unchanged against the deployed server.

---

## 14. Open decisions to confirm before starting

- **`mcp-server` scaling**: min replicas 0 (cheapest, cold start of a few seconds on first tool call after idle) vs min replicas 1 (near-zero latency, small constant cost). For solo interactive use, 0 is probably fine — flag if cold start during a live Claude session bothers you.
- **Region**: not specified — pick one and it goes in `infra/00-vars.sh` once.
- **Embedding provider**: Azure OpenAI assumed (§3) so everything stays in one cloud/billing surface — say if you'd rather call OpenAI directly.
