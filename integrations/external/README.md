# External Integrations

This folder contains code that is intentionally outside the native project contract.

- `bots/` holds example external bot implementations.
- `templates/bots/` holds the starter bot notebook with spectate UI via `notebook_harness.spectate`; it is not discovered at runtime and is the copy source for creating new bots.
- `clients/` holds reference client code for external integrations.
- `contracts/` holds external-facing contracts and interfaces.
- `tests/` holds external integration tests that are not part of the native `uv run test` path.

Nothing in `services/native-runtime/src/ticket_to_ride/` should require imports from this tree.

## External Bot Plugins

Runtime-discoverable bots live in `integrations/external/bots/` and must be import-side-effect-free.

Each bot module must define:

- `BOT_META` with `schema_version`, `id`, `name`, `version`, and `description`
- exactly one concrete `BaseBot` subclass
- `META = BOT_META` on that class

`id` is the stable machine identifier used by APIs and native registration. `name` is display-only.

## Startup Integration

By default, `uv run run` discovers repository bots and executes their
`act(view, legal_actions)` method in-process, so the Bots page works without a
second service. When `TICKET_TO_RIDE_ENABLE_BOT_API=1` is set, startup instead
uses the external bot API at `BOT_API_BASE_URL`; that opt-in transport retains
the legacy `choose_*` protocol for compatibility.
