# Repo Layout

This project is split into three top-level ownership areas:

- `src/ticket_to_ride/`: native first-party Python package. This is the UV-managed runtime and includes the game engine, backend APIs, logging, and runtime entrypoints.
- `apps/`: first-party support apps owned by this repo. The current viewer lives in `apps/viewer/`.
- `tools/`: local first-party runtime helpers that are not Python packages. PocketBase should live at `tools/pocketbase/pocketbase.exe`.
- `external/`: quarantined integration surfaces that are not part of the native runtime contract. Bot examples, bot API reference code, and external client helpers live here.

## Native Runtime

The supported native commands are:

- `uv run run`
- `uv run test`

The native runtime must not depend on anything under `external/`.

## External Area

The `external/` tree exists for examples, contracts, and integration reference material:

- `external/bots/`: example external bots
- `external/clients/`: external-facing bot client and bot API reference code
- `external/contracts/`: shared external contracts

These files are intentionally separated from `src/ticket_to_ride/` so the repo layout makes the boundary obvious.
