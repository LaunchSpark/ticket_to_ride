# External Integrations

This folder contains code that is intentionally outside the native project contract.

- `bots/` holds example external bot implementations.
- `clients/` holds reference client code for external integrations.
- `contracts/` holds external-facing contracts and interfaces.
- `tests/` holds external integration tests that are not part of the native `uv run test` path.

Nothing in `src/ticket_to_ride/` should require imports from this tree.

