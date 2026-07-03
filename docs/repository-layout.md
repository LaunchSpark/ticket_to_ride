# Repo Layout

This project is split into architecture-first top-level ownership areas:

- `services/`: first-party runtime services. The native Python runtime lives in `services/native-runtime/src/ticket_to_ride/`.
- `applications/`: first-party UI surfaces. The current viewer lives in `applications/viewer/`. The notebook test harness used by bot notebooks lives in `applications/notebook_harness/` — a pure-Python package (no HTTP/PocketBase dependency) that bot notebooks under `integrations/external/bots/` import to run and render in-process test games.
- `integrations/`: external-facing code and example bot surfaces. The current external tree lives in `integrations/external/`.
- `operations/`: local runtime state and tooling. PocketBase data lives in `operations/data/`; the binary belongs in `operations/tools/pocketbase/pocketbase.exe`.
- `quality/`: automated test suites. Native tests live in `quality/tests/`.
- `docs/`: architecture and repository documentation.

The native `ticket_to_ride` package no longer needs a repo-root shim. With `uv sync` and `uv run`, imports resolve from `services/native-runtime/src/ticket_to_ride/` through the editable project install.

One small repo-root compatibility shim still remains:

- `external/`

That exists only to preserve local import paths while the real external source tree lives under `integrations/external/`.

## Native Runtime

The supported native commands are:

- `uv run run`
- `uv run test`

Both require dependencies installed via `uv sync --extra notebooks`, not plain `uv sync` — see "External Area" below for why.

The native runtime must not depend on anything under `integrations/external/`.

## External Area

The `integrations/external/` tree exists for examples, contracts, and integration reference material:

- `integrations/external/bots/`: example external bots. These are marimo notebook files (see `docs/superpowers/specs/2026-07-02-marimo-notebook-migration-design.md`); each `import marimo` unconditionally at module scope, so anything that imports a bot module — including `BotLoader` and therefore the native test suite — requires the `notebooks` optional dependency group installed.
- `integrations/external/clients/`: external-facing bot client and bot API reference code
- `integrations/external/contracts/`: shared external contracts

These files are intentionally separated from `services/native-runtime/src/ticket_to_ride/` so the repo layout makes the boundary obvious.
