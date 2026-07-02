# Marimo Notebook Bot-Authoring & Spectating Migration — Design

**Date:** 2026-07-02
**Status:** Approved

## Goal

Replace the bot-development/debugging workflow with marimo notebooks: a developer opens a
notebook for a specific bot, edits the bot's logic directly in a cell, and watches it play
against other bots on a `wigglystuff.GraphWidget` board, stepping through turns with
`wigglystuff.PlaySlider`. The existing FastAPI + PocketBase + managed-match/bot-sandbox stack
keeps running real matches unchanged; this migration only replaces how a developer authors and
locally test-plays a single bot.

## Phase Boundary

**In scope (this spec, "Phase 1+2"):**
- A shared notebook harness for building/rendering in-process test games
- Converting the two existing bots to canonical marimo notebook files
- A small engine change to support selecting a map (mechanism only, one map for now)
- A minimal launcher page/endpoint added to the existing React viewer

**Out of scope (future specs):**
- Full multi-user launcher (auth, concurrent sessions, remote hosting)
- Retiring `applications/viewer`'s replay-of-real-managed-matches feature
- Network-multiplayer bot execution (bots playing real matches over the network)
- Authoring additional maps beyond the migrated single map

## Current State (context)

- `services/native-runtime/src/ticket_to_ride/engine/` is the in-process game engine:
  `Game`, `Player`, `GameContext`, `MapGraph`/`Route`. `MapGraph` hardcodes
  `operations/data/map.csv` and takes no map selector.
- Bots are `BaseBot` subclasses (`integrations/external/contracts/base_bot.py`) living in
  `integrations/external/bots/*.py` (`example_bot.py`, `random_bot.py`), discovered by
  `BotLoader` (`integrations/external/clients/bot_api/loader.py`) via
  `importlib.import_module` + `inspect.getmembers` for `BaseBot` subclasses.
- Real matches run through `managed_match_runtime` → `BotApiExecutor` → the sandboxed HTTP
  bot-api → `BotLoader`. This path is untouched by this migration.
- `GameLogger` (`services/native-runtime/src/ticket_to_ride/logging/game_logger.py`) persists
  turn-by-turn snapshots to PocketBase over HTTP via `GameLogSerializer`; `Game.next_turn()`
  calls `self.logger.record_turn(round_number, context)` every turn.
- `applications/viewer` is a React app that replays matches from PocketBase over the backend
  HTTP API; `backend/app.py` already exposes `GET /bots` backed by a `BotCatalogClient` that
  queries the bot-api's `/bots` discovery endpoint.
- No marimo/anywidget/wigglystuff exists in the repo today.

## Architecture

### 1. Notebook harness (new)

New module at `applications/notebook-harness/` (first-party UI-adjacent surface, following the
existing `applications/viewer` convention — not part of `services/native-runtime`). Every bot
notebook imports this. Responsibilities:

- `list_maps() -> list[str]`: enumerate available maps.
- `initialize_game(seats: int, bots: list[BaseBot], map_name: str) -> HarnessGame`: builds a
  `GameContext` (with the given map), wraps each bot in an engine `Player`, constructs a `Game`
  using a new `InMemoryGameLogger` in place of the production `GameLogger`.
- `InMemoryGameLogger`: satisfies the same call shape `record_turn(round_number, context)` that
  `Game.next_turn()` already invokes, but appends `GameLogSerializer`-produced snapshots to a
  plain Python list instead of POSTing to PocketBase. No HTTP, no backend dependency — a bot
  notebook runs fully offline.
- `HarnessGame.render() -> GraphWidget`: builds nodes from `map.cities()` and edges from
  `map.routes`, keyed by each route's existing unique `route_id` (parallel/sibling routes
  already have distinct ids, so no extra work is needed there). Edge `width` maps from
  `route.length`; edge `color` maps from `route.color`, or the claiming player's color once
  claimed. The authoritative length/owner data stays in each edge's `data` dict, separate from
  the rendering width/color.
- `HarnessGame.play_slider() -> PlaySlider`: bound to the in-memory snapshot list. Stepping it
  rebuilds node/edge lists for that turn and pushes them via `with graph.hold_sync(): graph.nodes
  = ...; graph.edges = ...`.

### 2. Engine change: selectable map

- `MapGraph.__init__` gains an optional `map_path: Path | None` parameter, defaulting to the
  current single map's new location.
- `GameContext.__init__` gains an optional `map_name: str | None` parameter, resolved to a path
  and passed through to `MapGraph`.
- `operations/data/map.csv` moves to `operations/data/maps/classic.csv`. `Destination_tickets.csv`
  stays at its current path (ticket deck is not map-specific in the current engine).
- No new maps are authored in this migration — only the mechanism, so `list_maps()` has a real
  directory to scan.

### 3. Bot notebooks (replace bot files in place)

`integrations/external/bots/example_bot.py` and `random_bot.py` become marimo notebook files at
the same paths (same filenames, same import path the loader already uses). Marimo notebooks are
plain Python files; a cell containing *only* a single class definition is compiled to
`@app.class_definition`, making it a genuine top-level, importable module attribute — confirmed
against marimo's docs on reusing functions and classes
(https://docs.marimo.io/guides/reusing_functions/). Regular cells (widgets, harness calls,
`GraphWidget`/`PlaySlider` wiring) are never executed by a plain import — they only run when the
file is opened in `marimo edit`/`marimo run`. This means one notebook file serves two audiences
without any cross-notebook cell-importing mechanism:

- `app.setup` block: imports (`BaseBot`, `MapGraph`, `Route`, `DestinationTicket`, the harness)
  and the `BOT_META` constant.
- One reusable cell: the bot class itself (e.g. `RandomBot(BaseBot)`), internals unchanged from
  today — all its methods, including private helpers, live inside this one class definition.
  Additional cells may hold standalone helper *functions* (not methods) if a bot wants to factor
  those out; each such helper needs its own single-function cell, since reusable cells may
  reference other top-level reusable symbols.
- Remaining (non-reusable) cells: calls into the harness to run a test game with this bot,
  `GraphWidget` and `PlaySlider` wiring for interactive stepping while editing.

`BotLoader` requires **no changes** — it already does `importlib.import_module` +
`inspect.getmembers` for `BaseBot` subclasses, which continues to work unmodified against the
notebook-formatted files. `BaseBot` itself is unchanged: a shared library/mixin each bot notebook
imports via its `app.setup` block.

### 4. Minimal launcher

A new page in the existing React viewer (`applications/viewer`) lists bots by reusing the
existing `GET /bots` catalog data already surfaced by `backend/app.py`. Clicking a bot calls a
new `POST /notebooks/{bot_id}/launch` endpoint that:

- Resolves the bot's file path via `BotLoader` (in-process import, not through the HTTP
  bot-api sandbox — this endpoint only needs the file path).
- Spawns (or reuses, if a live process is already tracked for that `bot_id`) a
  `marimo edit <path> --port <port>` subprocess.
- Returns the URL for the frontend to open in a new tab.

Process tracking is a simple in-memory `{bot_id: (Popen, port)}` map on the backend. No auth, no
multi-user concerns — this targets a single developer on a local machine, matching the existing
`applications/viewer` operator-tool posture.

## Dependencies

`marimo`, `anywidget`, `wigglystuff` are added to the root `pyproject.toml` as an optional
extras group:

```toml
[project.optional-dependencies]
notebooks = ["marimo>=0.9", "anywidget>=0.9", "wigglystuff>=0.1"]
```

Not added to core `dependencies` — the production backend/PocketBase deployment should not need
to pull in notebook tooling.

## Testing Strategy

- Unit tests under `quality/tests/` for the harness's pure-Python surface: `initialize_game`,
  `InMemoryGameLogger.record_turn` (snapshot shape matches `GameLogSerializer` output),
  `list_maps`, and the `MapGraph`/edge-list construction used by `HarnessGame.render()`.
- A regression test for the new `MapGraph`/`GameContext` `map_path`/`map_name` parameter
  (defaults to today's single map; explicit path loads a specific map file).
- Marimo/GraphWidget rendering itself is not practically unit-testable. Verification is manual:
  open each migrated bot notebook in `marimo edit` and confirm it runs, renders the board, and
  the `PlaySlider` steps through a full game.
- A smoke test for the launcher endpoint: `POST /notebooks/{bot_id}/launch` returns a reachable
  URL for a known bot id, and a second call for the same bot id reuses the existing process
  rather than spawning a duplicate.

## Open Risks

- Marimo's reusable-cell import mechanism (the core assumption enabling "notebook is canonical
  and the existing loader needs no changes") is confirmed against current marimo documentation
  but has not yet been exercised against this repo's actual `BaseBot`/`BotLoader` code. The first
  implementation task should include a smoke test that imports a converted bot notebook the same
  way `BotLoader` does, before the rest of the migration builds on top of it.
