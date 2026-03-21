# Ticket to Ride

## Overview

This repo now manages the native Ticket to Ride engine and backend as a UV-managed project.

- Native Python runtime lives in `src/ticket_to_ride/`
- First-party support apps live in `apps/`
- External integrations and bot examples live in `external/`

The main native commands are:

- `uv run run`
- `uv run test`

## Setup

1. Install `uv`
2. Run `uv sync`
3. Place the PocketBase binary at `tools/pocketbase/pocketbase.exe`

## Native Layout

```text
ticket_to_ride/
├── pyproject.toml
├── uv.lock
├── src/ticket_to_ride/
├── apps/viewer/
├── external/
├── data/
├── tests/
└── documentation/
```

## Native Runtime

- `uv run run` starts the native backend stack
- `uv run test` runs the native automated test suite
- `uv run run` will auto-start PocketBase when the binary is available at `tools/pocketbase/pocketbase.exe`

The native runtime must not depend on code under `external/`.

## External Integrations

Bot code is quarantined under `external/` so the folder layout clearly distinguishes first-party/native code from outside integrations.

- `external/bots/` contains example bots
- `external/clients/` contains external client and bot API reference code
- `external/contracts/` contains external-facing contracts

These files are kept for reference and integration work, but they are not part of the native package contract.

## Viewer

The first-party web viewer lives in `apps/viewer/`.

## PocketBase

The conventional local install path for PocketBase is `tools/pocketbase/pocketbase.exe`.

If you keep the binary somewhere else, set `POCKETBASE_BINARY` to the full path before running `uv run run`.

For local development, the launcher also ensures a default PocketBase superuser:

- email: `admin@example.com`
- password: `12345678`

PocketBase requires an email-based superuser login and a password of at least 8 characters, so a literal `admin` / `admin` login is not supported by PocketBase itself.

## More Detail

- Repo layout notes: `documentation/repo_layout.md`
- External integration notes: `external/README.md`
