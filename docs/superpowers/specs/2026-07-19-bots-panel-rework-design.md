# Bots Panel Rework: Live Discovery, New-Bot Scaffolding, Remote Connections

**Date:** 2026-07-19
**Status:** Approved

## Goal

The viewer's Bots panel should show every locally discoverable bot automatically,
without manual registration. The **+** button becomes a two-way chooser: scaffold a
brand-new bot from a name, or connect to someone else's bot API by URL. Remote bots
are playable in managed matches.

## Current state

- Local bots are marimo notebooks in `integrations/external/bots/*.py`, discovered
  by `BotLoader` (`integrations/external/clients/bot_api/loader.py`).
- `GET /bots` returns rows persisted in the PocketBase `bots` collection;
  `POST /bots` registers one by ID after resolving it against the catalog client
  (`services/native-runtime/src/ticket_to_ride/backend/{app,service,bot_catalog}.py`).
- The panel (`applications/viewer/components/dashboard/BotsDashboard.jsx`) lists
  registered bots and its **Add Bot** modal asks for a bot ID.
- A remote-play protocol already exists: `BotApiExecutor`
  (`backend/runtime/executor.py`) speaks HTTP to the bot API sidecar
  (`/bots`, `/bot-sessions`, per-action endpoints) and already accepts a
  `base_url` argument. It is currently only used when
  `TICKET_TO_RIDE_ENABLE_BOT_API` is set, always against loopback.

## Data model shift

Bots stop being persisted records:

- **Local bots** are rediscovered live on every list call. Nothing is written to
  PocketBase for them.
- **Remote connections** are the only persisted entity: a new PocketBase
  collection `bot_connections` with fields `url` (normalized base URL, unique)
  and `created`. Collections are owned by `ensure_collections` in
  `bootstrap_pocketbase.py`, per existing convention.
- The old `bots` collection and the register-by-ID flow (`POST /bots`) are
  retired. Repository `list_bots`/`upsert_bot` methods and the PocketBase
  `bots` collection read path are removed from the serving path.

## Backend design

### `GET /bots` — live merged view

Response shape:

```json
{
  "bots": [ { "botId": "...", "name": "...", "version": "...", "description": "...",
              "author": "...", "tags": [], "source": "local" | "remote",
              "connectionId": null | "...", "baseUrl": null | "http://..." } ],
  "connections": [ { "connectionId": "...", "url": "http://...",
                     "status": "online" | "offline", "error": null | "...",
                     "botCount": 0 } ]
}
```

- **Local:** construct a fresh `BotLoader` per request (no caching across
  requests) and map descriptors to bot entries with `source: "local"`. The
  `local_api` source pretense from v1 is dropped.
- **Remote:** for each stored connection, `GET {url}/bots` with a ~3 s timeout.
  Connections are fetched **concurrently** (thread pool) so one dead host does
  not stall the panel. Bots from a connection get `source: "remote"`,
  `connectionId`, and `baseUrl`. An unreachable connection still appears in
  `connections` with `status: "offline"` and its error string; it contributes
  no bots.

Known limitation (accepted): `BotLoader` imports bot modules through Python's
module cache, so edits to an existing bot's `BOT_META` are not reflected until
backend restart. New files appear immediately.

### Connections API

- `POST /bot-connections` with `{ "url": "http://friend-host:8001" }`
  - Validate scheme is http/https; normalize by stripping the trailing slash.
  - Ping `GET {url}/bots` and require a valid catalog response (JSON array of
    schemaVersion-1 metadata) before persisting — a URL that does not speak the
    protocol is rejected with 400 and the underlying error.
  - Duplicate normalized URL → 400 "already connected".
  - The loopback-only restriction in `LocalApiBotCatalogClient` does **not**
    apply to connections; that check remains only on the legacy env-configured
    sidecar path.
  - Returns the stored connection plus its discovered bots.
- `DELETE /bot-connections/{id}` — removes the connection (404 if unknown).

### `POST /bots/new` — scaffold a bot

Request `{ "name": "My Cool Bot" }`:

1. Slugify the name to a bot ID (`my_cool_bot`): lowercase, alphanumerics and
   underscores, collapse runs, must be non-empty and a valid Python module stem.
2. Reject collisions (400) with existing local bot IDs or existing files in
   `integrations/external/bots/`.
3. Write `integrations/external/bots/<slug>.py` from a template modeled on
   `random_bot.py`: marimo notebook with `BOT_META` filled from the request
   (version `0.1.0`, empty tags, description placeholder), a minimal
   `ActionBot` subclass that picks a random legal action, and the spectate
   cells wired via `notebook_harness.spectate`.
4. Launch the notebook through the existing `NotebookLauncher` and return
   `{ "botId": "...", "url": "..." }` so the frontend can `window.open` it.

The new bot is picked up by the next `GET /bots` via live discovery.

### Remote bots in managed matches

- Seat resolution: when a managed match starts, resolve each seat's
  `primaryBotId` against the merged catalog:
  - local bot → `InProcessBotExecutor(bot_id)` (unchanged default);
  - remote bot → `BotApiExecutor(bot_id, base_url=connection.url)`.
- Collision rules: a local bot ID shadows a remote one; across connections the
  first (oldest) connection wins, with a log warning.
- If a remote bot is offline at match start, executor startup fails and the
  existing `fallbackBotId` mechanism substitutes it, as today.
- `TICKET_TO_RIDE_ENABLE_BOT_API` keeps its current meaning for local
  execution and is orthogonal to remote connections.

## Frontend design (`BotsDashboard.jsx`)

- On load, fetch the merged list. Render **Local Bots** as one group, then one
  group per connection headed by its URL and an online/offline status pill.
  Search filters across all groups as today.
- Local cards keep **Open Notebook**. Remote cards show connection info and no
  notebook button.
- Each connection group header has a remove (✕) button with an inline confirm,
  calling `DELETE /bot-connections/{id}` and refreshing the list.
- The **+** button opens a chooser modal with two options:
  - **New Bot** → name field → `POST /bots/new` → open returned notebook URL in
    a new tab → refresh list.
  - **Add Connection** → URL field → `POST /bot-connections` → refresh list.
  - Validation and transport errors render inline in the modal, using the
    existing `bots-add-modal` styling and interaction patterns (Escape to
    close, backdrop click, disabled while saving).
- `services/bot-registry.jsx` swaps `registerBot` for `createBot(apiBase, name)`,
  `addConnection(apiBase, url)`, `removeConnection(apiBase, id)`, and the new
  `listBots` response shape.

## Rejected alternatives

- **Sync-all-to-PocketBase:** persisting every discovered bot keeps stale rows
  and contradicts the requirement that local bots be rediscovered live.
- **Browser-side remote fetch:** having the viewer fetch remote catalogs
  directly hits CORS and doesn't help the backend, which needs connection URLs
  anyway to run matches.

## Testing

- Slugify + scaffold: unit tests writing into a temp bots dir (valid name,
  collision, bad characters, empty).
- Connections: endpoint tests with a mocked remote catalog (happy path, bad
  URL scheme, non-catalog response, duplicate URL, delete).
- Merged listing: local-only, local + online connection, offline connection
  (returns stub with error, no bots), collision shadowing.
- Seat resolution: remote bot maps to `BotApiExecutor` with the connection's
  base URL; offline remote falls back via `fallbackBotId`.
- Suites live in `quality/tests` and `integrations/external/tests`, matching
  existing layout.
