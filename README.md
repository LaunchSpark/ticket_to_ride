# Ticket to Ride

## Overview

This repo now manages the native Ticket to Ride engine and backend as a UV-managed project.

- Native Python runtime lives in `services/native-runtime/src/ticket_to_ride/`
- First-party UI surfaces live in `applications/`
- External integrations and bot examples live in `integrations/external/`
- Local state and tooling live in `operations/`
- Native automated tests live in `quality/tests/`

The main native commands are:

- `uv run run`
- `uv run test`

## Setup

1. Install `uv`
2. Run `uv sync --extra notebooks` (bot files under `integrations/external/bots/` are marimo notebooks and `import marimo` unconditionally, so the `notebooks` extra is required even for `uv run test` — plain `uv sync` will fail to load bots)
3. Place the PocketBase binary at `operations/tools/pocketbase/pocketbase.exe`

## Native Layout

```text
ticket_to_ride/
├── pyproject.toml
├── uv.lock
├── services/native-runtime/src/ticket_to_ride/
├── applications/viewer/
├── integrations/external/
├── operations/data/
├── operations/tools/
├── quality/tests/
└── docs/
```

## Native Runtime

- `uv run run` starts the native backend stack
- `uv run test` runs the native automated test suite
- `uv run run` will auto-start PocketBase when the binary is available at `operations/tools/pocketbase/pocketbase.exe`
- `uv run run` seeds a bootstrap replay match with 2 in-process random bots when no matches exist
- With `TICKET_TO_RIDE_ENABLE_BOT_API=1`, `uv run run` instead auto-starts the external bot API (when `BOT_API_BASE_URL` points at a local loopback `http://` service), registers `random_bot`, and creates a 3-round managed `Random Bot vs Random Bot` match with a 1-minute clock when both replay matches and managed matches are empty. Off by default until the bot-api HTTP protocol migrates from the legacy `choose_*` contract to `act()`.

The native runtime must not depend on code under `integrations/external/`.

## External Integrations

Bot code is quarantined under `integrations/external/` so the folder layout clearly distinguishes first-party/native code from outside integrations.

- `integrations/external/bots/` contains example bots
- `integrations/external/clients/` contains external client and bot API reference code
- `integrations/external/contracts/` contains external-facing contracts

These files are kept for reference and integration work, but they are not part of the native package contract.

## Viewer

The first-party web viewer lives in `applications/viewer/`.

## PocketBase

The conventional local install path for PocketBase is `operations/tools/pocketbase/pocketbase.exe`.

If you keep the binary somewhere else, set `POCKETBASE_BINARY` to the full path before running `uv run run`.

For local development, the launcher also ensures a default PocketBase superuser:

- email: `admin@example.com`
- password: `12345678`

PocketBase requires an email-based superuser login and a password of at least 8 characters, so a literal `admin` / `admin` login is not supported by PocketBase itself.

## More Detail

- Repo layout notes: `docs/repository-layout.md`
- External integration notes: `integrations/external/README.md`
