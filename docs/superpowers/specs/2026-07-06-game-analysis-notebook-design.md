# Game Analysis Notebook — Design

**Date:** 2026-07-06
**Status:** Approved

## Problem

There is no way to study match results. The notebooks can spectate a single live game,
but nothing charts how player scores evolve over a game, and nothing aggregates across
stored matches to answer strategy questions like "which routes do winners claim?"
Stored matches also record neither the RNG seed nor the map they were played on, so
results can't be reproduced and multi-map analysis is impossible.

## Goals

1. A first-party **game analysis notebook** that combines:
   - the standard live spectate harness (pick bots, run a game, board + slider);
   - a **points line chart** — score on Y, turn on X, one line per player — for the
     live game and for any selected stored match;
   - a **route-claim heatmap** — a second `RouteGraphWidget` instance coloring each
     route by how often match winners (vs losers) claimed it, aggregated across
     stored matches.
2. **Schema extension:** matches persist the `seed` and `map_name` they were played
   with, threaded from `GameContext` through the logger, API, and both repositories.

Stored matches are read through the backend API (`GET /matches`,
`GET /matches/{id}`) — the same repository-agnostic path the viewer uses.

## Existing structure this builds on

- `turn_state` (GameLogSerializer) already records, per turn, the active player's and
  every opponent's `score` and cumulative `claimedRoutes` — both charts are
  reconstructible from stored turns without replaying games.
- `GameContext` already exposes `seed` and `map_graph.map_name`; the engine-level
  `GameRecord` already persists both. Only the match-log path (logger → API →
  repositories → PocketBase) drops them.
- `RouteGraphWidget` already has generic analysis traits (`colour_feature`,
  `colour_scale_type`, `node_size_feature`, `selected_ids`) — the heatmap needs no
  JS changes.
- `bootstrap_pocketbase.collection_is_valid` diffs fields and
  `reset_project_collections` recreates mismatched collections, so the schema change
  deploys itself in dev. **Note:** that reset drops previously stored matches once.
- `notebook_harness.spectate` provides the 4-cell live harness; the analysis notebook
  reuses it.

## Design

### 1. Schema: seed and map on matches

- `matches` collection gains two optional fields:
  `{"name": "seed", "type": "number", "required": False}` and
  `{"name": "map_name", "type": "text", "required": False}`.
- `GameLogger.start_match(match_name=None, seed=None, map_name=None)` includes
  `"seed"` and `"mapName"` in the `POST /matches` payload when provided.
- Backend: the match-create request model, `create_match` service, and both
  repositories (`InMemoryMatchRepository`, `PocketBaseMatchRepository` incl.
  normalization) accept and return the two optional fields. Match summaries and
  details expose `seed` and `mapName` (null when absent).
- Producers pass them from the game they run (`context.seed`,
  `context.map_graph.map_name`): the CLI bootstrap seed loop, the managed-match
  round runtime, and the replay transport.
- Backward compatibility: records without the fields read back as `seed=None`,
  `mapName=None`; analysis treats a missing map as `"classic"`.

### 2. Analysis module — `applications/notebook_harness/analysis.py`

Pure, headless-testable functions; no marimo imports:

- `fetch_match_summaries(transport) -> list[dict]` — `GET /matches`.
- `fetch_match_detail(transport, match_id) -> dict` — `GET /matches/{match_id}`.
- `score_rows(turn_states) -> list[dict]` — flattens a sequence of `turnState`
  dicts into `{"turn": int, "player_id": str, "name": str, "score": int}` rows,
  one per player per turn (active player's `score` plus each opponent's). Works
  identically on a stored match's turns and on the live harness game's
  `InMemoryGameLogger` snapshots, which share the `turnState` shape. Player
  display names come from the match's player list; fall back to `player_id`.
- `match_winners(match_detail) -> set[str]` — player ids with the highest final
  score (last turn's scores); ties mean multiple winners.
- `route_claim_stats(match_details) -> dict[str, dict]` — per `route_id`:
  `{"winner_claims": int, "loser_claims": int, "winner_share": float}`. For each
  match, the final turn state's cumulative `claimedRoutes` per player determine
  who claimed what; claims by a match winner count as winner claims.
  `winner_share = winner_claims / (winner_claims + loser_claims)`. Callers pass
  only matches from one map — the function does not mix maps itself.
- `heatmap_edges(map_name, stats) -> (nodes, edges)` — builds the selected map's
  board via the harness map loader, attaching `winner_share`, `winner_claims`,
  and `loser_claims` under each edge's `data` so `RouteGraphWidget` can color by
  `colour_feature="winner_share"` (diverging scale: red = loser-route, green =
  winner-route). Routes never claimed in the corpus carry no `winner_share`.

### 3. Notebook — `applications/notebooks/game_analysis.py`

A marimo notebook, top to bottom:

**Live section** — the standard 4 spectate cells reused from
`notebook_harness.spectate`. Small extension: `spectate_controls` accepts
`bot_class=None`, in which case no live class is injected and the first two seats
default to the first two discovered bots. Below the harness, a points chart cell:
altair line chart of `score_rows(live snapshots)`, one line per player in their
seat color, with a vertical rule mark tracking the step slider (same
slider-following pattern as the market bar).

**Corpus section** —
- a transport cell building `JsonHttpTransport` against the backend
  (`LOGGER_API_BASE_URL`, default `http://127.0.0.1:8000`), with `mo.stop` and a
  friendly message when the API is unreachable so the rest of the notebook (and
  headless exports) degrade gracefully;
- a map filter dropdown (from `list_maps()`) and a match table
  (`mo.ui.table` over `fetch_match_summaries`, filtered to the selected map,
  treating stored `mapName=None` as `"classic"`);
- a stored-match picker whose selection feeds the same altair points chart;
- the route-claim heatmap: a second `RouteGraphWidget` fed by
  `heatmap_edges(selected map, route_claim_stats(selected matches))`, with edge
  selection (`selected_ids`) surfacing exact winner/loser claim counts in a
  small readout.

Charting uses **altair** (marimo's native reactive charting); `altair` is added to
the `notebooks` extra in `pyproject.toml`. Chart styling follows the dataviz skill
at implementation time.

### 4. Testing

Headless, mirroring the spectate suite's style:

- `score_rows`: fixture turn states → per-player rows; opponents included; name
  fallback.
- `match_winners`: clear winner; tied winners.
- `route_claim_stats`: aggregation across multiple fixture matches; winner vs
  loser counting; share computation; empty corpus.
- `heatmap_edges`: edges carry the stats under `data`; unclaimed routes have no
  `winner_share`.
- Schema: logger payload includes seed/mapName; create-match round-trips through
  both repositories; PocketBase payload/normalization; summaries expose the
  fields; legacy records read back with nulls.
- Producers: CLI seed loop and round runtime pass seed/map (assert on the
  transport payload).
- Notebook: `marimo export html` executes all cells cleanly with no backend
  running (corpus cells stop gracefully).

### Error handling

- Backend unreachable → `mo.stop` with guidance ("start the stack with `uv run
  run`"), not a traceback.
- Matches with zero turns are skipped by `score_rows`/`match_winners` consumers.
- Unknown `map_name` on a stored match → fall back to `"classic"` for the
  heatmap and label the fallback in the map filter.

## Out of scope

- Persisting live harness games to PocketBase from the notebook (corpus comes from
  the CLI bootstrap and managed matches).
- Backend analytics endpoints — aggregation stays in the notebook layer.
- New widget JS; `RouteGraphWidget`'s existing traits suffice.
- Website/viewer changes.
