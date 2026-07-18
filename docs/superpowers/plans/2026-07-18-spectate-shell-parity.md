# Spectate Shell Widget — Dashboard Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the marimo notebook harness widgets to feature parity with the viewer replay dashboard — same grid layout, rounds, playback with jump-to-round/turn, leaderboard, collapsible aggregate stats, player-hands modal, destination tickets — so the dashboard can be retired.

**Architecture:** A single composite anywidget (`SpectateShellWidget`) reproduces the dashboard's `replay-dashboard-grid` layout, embedding the existing route-graph and info-bar JS render modules via a model facade (no changes to the 803-line force-graph file). Python pushes per-step payloads computed by a new `HarnessSeries` (multi-round wrapper over `HarnessGame`); the widget pushes `playback`/`selected_player` back, and marimo's 4-cell spectate pipeline stays intact. Phase B adds stored-match viewing by persisting `mapName`/`seed` in PocketBase and implementing the same series protocol over stored payloads.

**Tech Stack:** Python (anywidget + traitlets, marimo), esbuild-bundled vanilla-JS widgets, unittest via `uv run test`, PocketBase storage behind the FastAPI backend.

## Global Constraints

- Tests run with `uv run test` (unittest discovery over `quality/tests`); single test: `uv run python -m unittest quality.tests.<module> -v` from repo root.
- Widget JS lives in `applications/notebook_harness/widget-src/src/`, bundled to `applications/notebook_harness/static/` by `npm run build` in `widget-src/` (esbuild, ESM). CSS files are hand-written directly in `static/`.
- Widget CSS must be theme-aware via `light-dark()` with light fallbacks (repo convention; see existing `static/route_graph_widget.css`). Canvas/graph outlines contrast with fill, not background.
- The marimo 4-cell contract is load-bearing: controls → game → widgets → view. Widgets are created once per game (cell 3) and mutated from cell 4; a widget's value is only read from a different cell than the one that bound it.
- Existing standalone widgets (`RouteGraphWidget`, `PlayerListWidget`, `InfoBarWidget`) keep working — the shell reuses their JS, it does not replace their Python classes.
- Hand color keys are the serializer's nine labels: black, blue, green, locomotive, orange, purple, red, white, yellow (engine codes B,U,G,L,O,P,R,W,Y).
- Commit after every green test cycle. Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Series Protocol (consumed by the shell, implemented twice)

Both `HarnessSeries` (Task 1–2, in-kernel games) and `StoredMatchSeries` (Task 8, stored payloads) implement:

```
roster() -> List[{"id","name","color"}]
round_count() -> int
turn_count(round_index: int) -> int
rounds_meta() -> List[{"roundNumber": int, "turnCount": int}]
active_player_at(round_index, turn_index) -> str            # playerId whose turn it is
board_at(round_index, turn_index, viewpoint=None) -> (nodes, edges)
market_at(round_index, turn_index, viewpoint=None) -> dict  # InfoBarWidget market payload
leaderboard_at(round_index, turn_index) -> List[{"playerId","name","color","score","remainingTrains","place"}]
stats_at(round_index, turn_index) -> Dict[playerId, {"hand": {color: int}, "hiddenCards": int|None, "score", "remainingTrains", "ticketCount", "routeCount"}]
tickets_at(round_index, turn_index, player_id) -> List[{"from","to","points","status": "open"|"completed"|"cut_off", "trainsShort": int|None}]
aggregates() -> List[{"playerId","name","color","scores": List[int], "averageScore": float, "bestScore": int, "wins": int}]
```

---

# Phase A — widget UI parity with in-kernel games

### Task 1: HarnessSeries — multi-round games

**Files:**
- Modify: `applications/notebook_harness/game_runner.py`
- Test: `quality/tests/test_notebook_harness_series.py` (create)

**Interfaces:**
- Consumes: existing `initialize_game(bots, map_name, round_number, seed)`, `HarnessGame`.
- Produces: `initialize_series(bot_classes: List[type], map_name: str = DEFAULT_MAP_NAME, rounds: int = 1, seed: int | None = None) -> HarnessSeries`; `HarnessSeries` dataclass with `games: List[HarnessGame]`, `play()`, `roster()`, `round_count()`, `turn_count(round_index)`, `rounds_meta()`.

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_notebook_harness_series.py
from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import HarnessSeries, initialize_series


class HarnessSeriesTests(unittest.TestCase):
    def test_initialize_series_builds_one_game_per_round_with_derived_seeds(self) -> None:
        series = initialize_series([RandomBot, RandomBot], rounds=2, seed=123)

        self.assertIsInstance(series, HarnessSeries)
        self.assertEqual(series.round_count(), 2)
        self.assertEqual(series.games[0].game.context.seed, 123)
        self.assertEqual(series.games[1].game.context.seed, 124)
        # Fresh bot instances per round, shared roster shape
        self.assertEqual(series.roster(), series.games[1].roster())

    def test_play_records_snapshots_for_every_round(self) -> None:
        series = initialize_series([RandomBot, RandomBot], rounds=2, seed=7)

        series.play()

        self.assertGreater(series.turn_count(0), 0)
        self.assertGreater(series.turn_count(1), 0)
        meta = series.rounds_meta()
        self.assertEqual(meta[0], {"roundNumber": 0, "turnCount": series.turn_count(0)})
        self.assertEqual(meta[1], {"roundNumber": 1, "turnCount": series.turn_count(1)})

    def test_initialize_series_rejects_zero_rounds(self) -> None:
        with self.assertRaises(ValueError):
            initialize_series([RandomBot, RandomBot], rounds=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_series -v`
Expected: FAIL — `ImportError: cannot import name 'HarnessSeries'`

- [ ] **Step 3: Implement in `game_runner.py`**

Add below `HarnessGame` (imports `random` is already available via engine modules — add `import random` at top if absent):

```python
@dataclass
class HarnessSeries:
    """A sequence of rounds: one fully-independent HarnessGame per round,
    same seats and map, seed derived as base_seed + round_index so every
    round is individually reproducible."""

    games: List[HarnessGame]

    def play(self) -> None:
        for game in self.games:
            game.play()

    def roster(self) -> List[Dict[str, str]]:
        return self.games[0].roster()

    def round_count(self) -> int:
        return len(self.games)

    def turn_count(self, round_index: int) -> int:
        return self.games[round_index].snapshot_count()

    def rounds_meta(self) -> List[Dict[str, int]]:
        return [
            {"roundNumber": index, "turnCount": game.snapshot_count()}
            for index, game in enumerate(self.games)
        ]


def initialize_series(
    bot_classes: List[type],
    map_name: str = DEFAULT_MAP_NAME,
    rounds: int = 1,
    seed: 'int | None' = None,
) -> HarnessSeries:
    """Build one unplayed HarnessGame per round from bot *classes* (a fresh
    instance per seat per round, so bot state never leaks across rounds)."""
    if rounds < 1:
        raise ValueError("initialize_series requires at least one round.")
    base_seed = seed if seed is not None else random.randrange(2**32)
    games = [
        initialize_game(
            [bot_class() for bot_class in bot_classes],
            map_name=map_name,
            round_number=round_index,
            seed=base_seed + round_index,
        )
        for round_index in range(rounds)
    ]
    return HarnessSeries(games=games)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_series -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite, then commit**

Run: `uv run test` — expected: all pass.

```bash
git add applications/notebook_harness/game_runner.py quality/tests/test_notebook_harness_series.py
git commit -m "feat(harness): multi-round HarnessSeries with per-round derived seeds"
```

### Task 2: Per-step accessors — leaderboard, stats, tickets, aggregates

**Files:**
- Modify: `applications/notebook_harness/game_runner.py`
- Test: `quality/tests/test_notebook_harness_series.py` (extend)

**Interfaces:**
- Consumes: `HarnessGame._replayed_game(step)`, `InMemoryGameLogger.snapshots` (`{"roundNumber","turnIndex","turnState"}` where `turnState = {"player": {...full hand/tickets...}, "opponents": [...], "gameObjects": ...}`), `PlayerView(player_id, context, players)` with `.score`, `.tickets`, `.ticket_costs()`; `DestinationTicket.city1/.city2/.value/.is_completed`; `Player.get_hand()` (engine letter codes), `Player.trains_remaining`, `Player.get_tickets()`.
- Produces: on `HarnessGame`: `active_player_at(step)`, `leaderboard_at(step)`, `stats_at(step)`, `tickets_at(step, player_id)`; on `HarnessSeries`: protocol methods `active_player_at(r, t)`, `board_at(r, t, viewpoint)`, `market_at(r, t, viewpoint)`, `leaderboard_at(r, t)`, `stats_at(r, t)`, `tickets_at(r, t, player_id)`, `aggregates()`.

- [ ] **Step 1: Write the failing tests** (append to `test_notebook_harness_series.py`)

```python
class SeriesAccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.series = initialize_series([RandomBot, RandomBot], rounds=2, seed=42)
        cls.series.play()

    def test_leaderboard_ranks_players_by_score_with_trains_left(self) -> None:
        last = self.series.turn_count(0) - 1
        board = self.series.leaderboard_at(0, last)

        self.assertEqual(len(board), 2)
        self.assertEqual(board[0]["place"], 1)
        self.assertGreaterEqual(board[0]["score"], board[1]["score"])
        for entry in board:
            self.assertIn("remainingTrains", entry)
            self.assertIn("color", entry)
            self.assertIn("name", entry)

    def test_stats_include_full_hands_for_every_player(self) -> None:
        stats = self.series.stats_at(0, 0)

        self.assertEqual(set(stats), {"bot_0", "bot_1"})
        for record in stats.values():
            self.assertEqual(
                set(record["hand"]),
                {"black", "blue", "green", "locomotive", "orange", "purple", "red", "white", "yellow"},
            )
            self.assertIsNone(record["hiddenCards"])  # omniscient in-kernel view
            for key in ("score", "remainingTrains", "ticketCount", "routeCount"):
                self.assertIn(key, record)

    def test_tickets_carry_status_and_trains_short(self) -> None:
        last = self.series.turn_count(0) - 1
        tickets = self.series.tickets_at(0, last, "bot_0")

        self.assertGreater(len(tickets), 0)
        for ticket in tickets:
            self.assertIn(ticket["status"], {"open", "completed", "cut_off"})
            if ticket["status"] == "completed":
                self.assertEqual(ticket["trainsShort"], 0)
            if ticket["status"] == "cut_off":
                self.assertIsNone(ticket["trainsShort"])

    def test_active_player_matches_snapshot_owner(self) -> None:
        snapshot = self.series.games[0].logger.snapshots[0]
        self.assertEqual(
            self.series.active_player_at(0, 0),
            snapshot["turnState"]["player"]["playerId"],
        )

    def test_aggregates_average_final_scores_and_count_wins(self) -> None:
        aggregates = self.series.aggregates()

        self.assertEqual(len(aggregates), 2)
        self.assertEqual(sum(entry["wins"] for entry in aggregates), 2)
        for entry in aggregates:
            self.assertEqual(len(entry["scores"]), 2)
            self.assertEqual(entry["bestScore"], max(entry["scores"]))
            self.assertAlmostEqual(entry["averageScore"], sum(entry["scores"]) / 2, places=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_series -v`
Expected: FAIL — `AttributeError: 'HarnessSeries' object has no attribute 'leaderboard_at'`

- [ ] **Step 3: Implement accessors**

In `game_runner.py`, add module-level hand mapping and `HarnessGame` methods:

```python
_HAND_LABELS = {
    "B": "black", "U": "blue", "G": "green", "L": "locomotive", "O": "orange",
    "P": "purple", "R": "red", "W": "white", "Y": "yellow",
}


def _hand_counts(hand: Dict[str, int]) -> Dict[str, int]:
    return {label: hand.get(code, 0) for code, label in _HAND_LABELS.items()}
```

On `HarnessGame`:

```python
    def _snapshot_rows(self, step_index: int) -> List[Dict[str, Any]]:
        state = self.logger.snapshots[step_index]["turnState"]
        return [state["player"], *state["opponents"]]

    def active_player_at(self, step_index: int) -> str:
        return self.logger.snapshots[step_index]["turnState"]["player"]["playerId"]

    def leaderboard_at(self, step_index: int) -> List[Dict[str, Any]]:
        meta = {entry["id"]: entry for entry in self.roster()}
        rows = sorted(self._snapshot_rows(step_index), key=lambda row: -row["score"])
        return [
            {
                "playerId": row["playerId"],
                "name": meta[row["playerId"]]["name"],
                "color": meta[row["playerId"]]["color"],
                "score": row["score"],
                "remainingTrains": row["remainingTrains"],
                "place": place,
            }
            for place, row in enumerate(rows, start=1)
        ]

    def stats_at(self, step_index: int) -> Dict[str, Dict[str, Any]]:
        """Omniscient per-player stats at a step: full hands come from the
        replayed game (snapshots only carry the active player's hand)."""
        replayed = self._replayed_game(step_index)
        routes = {row["playerId"]: len(row["claimedRoutes"]) for row in self._snapshot_rows(step_index)}
        scores = {row["playerId"]: row["score"] for row in self._snapshot_rows(step_index)}
        trains = {row["playerId"]: row["remainingTrains"] for row in self._snapshot_rows(step_index)}
        return {
            player.player_id: {
                "hand": _hand_counts(player.get_hand()),
                "hiddenCards": None,
                "score": scores[player.player_id],
                "remainingTrains": trains[player.player_id],
                "ticketCount": len(player.get_tickets()),
                "routeCount": routes.get(player.player_id, 0),
            }
            for player in replayed.players
        }

    def tickets_at(self, step_index: int, player_id: str) -> List[Dict[str, Any]]:
        replayed = self._replayed_game(step_index)
        view = PlayerView(player_id, replayed.context, replayed.players)
        results = []
        for ticket, cost in zip(view.tickets, view.ticket_costs()):
            if ticket.is_completed:
                status, short = "completed", 0
            elif cost is None:
                status, short = "cut_off", None
            else:
                status, short = "open", cost
            results.append(
                {"from": ticket.city1, "to": ticket.city2, "points": ticket.value,
                 "status": status, "trainsShort": short}
            )
        return results
```

On `HarnessSeries` (delegation + aggregates):

```python
    def active_player_at(self, round_index: int, turn_index: int) -> str:
        return self.games[round_index].active_player_at(turn_index)

    def board_at(self, round_index: int, turn_index: int, viewpoint: 'str | None' = None):
        return self.games[round_index].board_at(turn_index, viewpoint)

    def market_at(self, round_index: int, turn_index: int, viewpoint: 'str | None' = None):
        return self.games[round_index].market_at(turn_index, viewpoint)

    def leaderboard_at(self, round_index: int, turn_index: int):
        return self.games[round_index].leaderboard_at(turn_index)

    def stats_at(self, round_index: int, turn_index: int):
        return self.games[round_index].stats_at(turn_index)

    def tickets_at(self, round_index: int, turn_index: int, player_id: str):
        return self.games[round_index].tickets_at(turn_index, player_id)

    def aggregates(self) -> List[Dict[str, Any]]:
        meta = self.roster()
        scores: Dict[str, List[int]] = {entry["id"]: [] for entry in meta}
        wins: Dict[str, int] = {entry["id"]: 0 for entry in meta}
        for game in self.games:
            final = game.leaderboard_at(game.snapshot_count() - 1)
            for row in final:
                scores[row["playerId"]].append(row["score"])
            wins[final[0]["playerId"]] += 1
        return [
            {
                "playerId": entry["id"],
                "name": entry["name"],
                "color": entry["color"],
                "scores": scores[entry["id"]],
                "averageScore": round(sum(scores[entry["id"]]) / len(scores[entry["id"]]), 1),
                "bestScore": max(scores[entry["id"]]),
                "wins": wins[entry["id"]],
            }
            for entry in meta
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_series -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Full suite, commit**

Run: `uv run test` — expected: all pass.

```bash
git add applications/notebook_harness/game_runner.py quality/tests/test_notebook_harness_series.py
git commit -m "feat(harness): per-step leaderboard, stats, tickets, and series aggregates"
```

### Task 3: SpectateShellWidget Python class + payload push

**Files:**
- Create: `applications/notebook_harness/spectate_shell_widget.py`
- Test: `quality/tests/test_notebook_harness_shell.py` (create)

**Interfaces:**
- Consumes: series protocol (Task 2), `build_graph_data(nodes, edges)` from `route_graph_widget.py`.
- Produces: `SpectateShellWidget(anywidget.AnyWidget)` with the traits below; `build_shell(series) -> SpectateShellWidget`; `update_shell(shell, series) -> None` (tolerates both a raw widget and marimo's `mo.ui.anywidget` wrapper, mirroring `spectate._selected_player`'s dict-or-attr reads).

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_notebook_harness_shell.py
from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import initialize_series
from notebook_harness.spectate_shell_widget import SpectateShellWidget, build_shell, update_shell


class ShellWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.series = initialize_series([RandomBot, RandomBot], rounds=2, seed=99)
        cls.series.play()

    def test_build_shell_seeds_static_traits_once(self) -> None:
        shell = build_shell(self.series)

        self.assertIsInstance(shell, SpectateShellWidget)
        self.assertEqual(shell.players, self.series.roster())
        self.assertEqual(shell.rounds_meta, self.series.rounds_meta())
        self.assertEqual(len(shell.aggregates), 2)
        self.assertEqual(shell.playback, {"round": 0, "turn": 0})

    def test_update_shell_pushes_step_payloads(self) -> None:
        shell = build_shell(self.series)
        shell.playback = {"round": 1, "turn": 0}

        update_shell(shell, self.series)

        self.assertEqual(shell.current_player, self.series.active_player_at(1, 0))
        self.assertEqual(shell.leaderboard, self.series.leaderboard_at(1, 0))
        self.assertIn("nodes", shell.board)
        self.assertIn("links", shell.board)
        self.assertEqual(shell.tickets, self.series.tickets_at(1, 0, shell.current_player))

    def test_update_shell_clamps_out_of_range_playback(self) -> None:
        shell = build_shell(self.series)
        shell.playback = {"round": 99, "turn": 99}

        update_shell(shell, self.series)

        self.assertEqual(shell.current_player, self.series.active_player_at(
            self.series.round_count() - 1,
            self.series.turn_count(self.series.round_count() - 1) - 1,
        ))

    def test_selected_player_switches_tickets_and_culled_board(self) -> None:
        shell = build_shell(self.series)
        shell.selected_player = "bot_1"

        update_shell(shell, self.series)

        self.assertEqual(shell.tickets, self.series.tickets_at(0, 0, "bot_1"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_shell -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebook_harness.spectate_shell_widget'`

- [ ] **Step 3: Implement `spectate_shell_widget.py`**

```python
"""Composite spectate dashboard: the viewer replay dashboard's grid layout
rebuilt as one anywidget, embedding the route-graph and info-bar JS renderers.

Trait flow: Python pushes per-step payloads (board/market/leaderboard/stats/
tickets); JS owns playback interaction and writes `playback` and
`selected_player` back, which the spectate view cell reads reactively.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import anywidget
import traitlets

from notebook_harness.route_graph_widget import build_graph_data


class SpectateShellWidget(anywidget.AnyWidget):
    _esm = files("notebook_harness").joinpath("static/spectate_shell_widget.js")
    _css = files("notebook_harness").joinpath("static/spectate_shell_widget.css")

    # Python -> JS payloads
    board = traitlets.Dict().tag(sync=True)
    market = traitlets.Dict().tag(sync=True)
    players = traitlets.List([]).tag(sync=True)
    leaderboard = traitlets.List([]).tag(sync=True)
    stats = traitlets.Dict().tag(sync=True)
    tickets = traitlets.List([]).tag(sync=True)
    aggregates = traitlets.List([]).tag(sync=True)
    rounds_meta = traitlets.List([]).tag(sync=True)
    current_player = traitlets.Unicode("").tag(sync=True)

    # JS -> Python interaction
    playback = traitlets.Dict({"round": 0, "turn": 0}).tag(sync=True)
    selected_player = traitlets.Unicode("").tag(sync=True)

    # playback tuning
    interval_ms = traitlets.Int(300).tag(sync=True)

    # route-graph passthroughs (same names RouteGraphWidget uses; the JS
    # facade maps the graph's `data` trait onto `board`)
    repulsion = traitlets.Int(80).tag(sync=True)
    link_distance_base = traitlets.Float(30).tag(sync=True)
    link_distance_scale = traitlets.Float(15).tag(sync=True)
    node_scale = traitlets.Float(3).tag(sync=True)
    node_size_feature = traitlets.Unicode("").tag(sync=True)
    colour_feature = traitlets.Unicode("").tag(sync=True)
    colour_scale_type = traitlets.Unicode("").tag(sync=True)
    selected_ids = traitlets.List([]).tag(sync=True)
    select_feature = traitlets.Unicode("").tag(sync=True)
    select_feature_value = traitlets.Unicode("").tag(sync=True)
    width = traitlets.Int(800).tag(sync=True)
    height = traitlets.Int(500).tag(sync=True)


def _trait(shell: Any, name: str, default: Any) -> Any:
    """Read a trait off a raw widget or a mo.ui.anywidget wrapper."""
    value = getattr(shell, "value", None)
    if isinstance(value, dict) and name in value:
        return value[name]
    return getattr(shell, name, default)


def build_shell(series: Any) -> SpectateShellWidget:
    """Create the shell once per series, seeding static and step-0 traits."""
    shell = SpectateShellWidget(
        players=series.roster(),
        rounds_meta=series.rounds_meta(),
        aggregates=series.aggregates(),
    )
    update_shell(shell, series)
    return shell


def update_shell(shell: Any, series: Any) -> None:
    """Push the payloads for the shell's current playback step and selection."""
    playback = _trait(shell, "playback", {}) or {}
    round_index = min(max(int(playback.get("round", 0)), 0), series.round_count() - 1)
    turn_index = min(max(int(playback.get("turn", 0)), 0), series.turn_count(round_index) - 1)
    viewpoint = _trait(shell, "selected_player", "") or None

    nodes, edges = series.board_at(round_index, turn_index, viewpoint)
    active = series.active_player_at(round_index, turn_index)

    shell.board = build_graph_data(nodes, edges)
    shell.market = series.market_at(round_index, turn_index, viewpoint)
    shell.leaderboard = series.leaderboard_at(round_index, turn_index)
    shell.stats = series.stats_at(round_index, turn_index)
    shell.tickets = series.tickets_at(round_index, turn_index, viewpoint or active)
    shell.current_player = active
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_shell -v`
Expected: PASS (4 tests). Note: `_esm`/`_css` point at files that don't exist until Task 4 — anywidget resolves them lazily at render, not at construction, so tests pass.

- [ ] **Step 5: Full suite, commit**

```bash
uv run test
git add applications/notebook_harness/spectate_shell_widget.py quality/tests/test_notebook_harness_shell.py
git commit -m "feat(harness): SpectateShellWidget traits and payload push"
```

### Task 4: Shell JS + CSS — dashboard grid, playback, leaderboard, collapsible aggregates

**Files:**
- Create: `applications/notebook_harness/widget-src/src/spectate_shell_widget.js`
- Create: `applications/notebook_harness/static/spectate_shell_widget.css`
- Modify: `applications/notebook_harness/widget-src/package.json` (add entry to build)

**Interfaces:**
- Consumes: shell traits (Task 3); `widget-src/src/route_graph_widget.js` and `info_bar_widget.js` default exports (`{ render({model, el}) }`).
- Produces: bundled `static/spectate_shell_widget.js`; DOM hooks for Task 5: `renderStatsCard(model, playerId) -> HTMLElement` and an exported `openStatsModal(model, el, playerId)` stub called from leaderboard rows (implemented in Task 5).

- [ ] **Step 1: Write the shell JS**

```js
// widget-src/src/spectate_shell_widget.js
// The viewer replay dashboard's grid, rebuilt around the existing route
// graph and info bar renderers. Layout mirrors replay-dashboard-grid:
// hero board + sidebar on top, market / current player / tickets below.
import routeGraph from "./route_graph_widget.js";
import infoBar from "./info_bar_widget.js";
import { openStatsModal } from "./spectate_stats_modal.js";

// Adapts the shell's model for an embedded widget whose render() expects
// its own trait names (the route graph reads `data`; the shell stores the
// same payload under `board`).
function facadeModel(model, mapping) {
    const mapKey = (key) => mapping[key] || key;
    return {
        get: (key) => model.get(mapKey(key)),
        set: (key, value) => model.set(mapKey(key), value),
        save_changes: () => model.save_changes(),
        on: (event, callback) => {
            const [kind, key] = event.split(":");
            model.on(key ? `${kind}:${mapKey(key)}` : event, callback);
        },
    };
}

function elem(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

function playbackOf(model) {
    const value = model.get("playback") || {};
    return { round: value.round || 0, turn: value.turn || 0 };
}

function setPlayback(model, round, turn) {
    model.set("playback", { round, turn });
    model.save_changes();
}

function stepForward(model) {
    const meta = model.get("rounds_meta") || [];
    let { round, turn } = playbackOf(model);
    const turns = meta[round] ? meta[round].turnCount : 0;
    if (turn + 1 < turns) {
        setPlayback(model, round, turn + 1);
        return true;
    }
    if (round + 1 < meta.length) {
        setPlayback(model, round + 1, 0);
        return true;
    }
    return false;
}

function stepBack(model) {
    const meta = model.get("rounds_meta") || [];
    let { round, turn } = playbackOf(model);
    if (turn > 0) setPlayback(model, round, turn - 1);
    else if (round > 0) setPlayback(model, round - 1, meta[round - 1].turnCount - 1);
}

function renderSidebar(model, container, playState) {
    container.replaceChildren();
    const { round, turn } = playbackOf(model);
    const meta = model.get("rounds_meta") || [];

    const header = elem("div", "shell-sidebar-header");
    header.appendChild(elem("p", "shell-eyebrow", `Round ${round + 1} · Turn ${turn + 1}`));
    const controls = elem("div", "shell-playback-controls");
    const prev = elem("button", "shell-playback-button", "⏮");
    prev.addEventListener("click", () => stepBack(model));
    const play = elem("button", "shell-playback-button", playState.playing ? "⏸" : "▶");
    play.addEventListener("click", () => playState.toggle());
    const next = elem("button", "shell-playback-button", "⏭");
    next.addEventListener("click", () => stepForward(model));
    controls.append(prev, play, next);
    header.appendChild(controls);

    const jump = elem("button", "shell-jump-button", "Jump To Round / Turn");
    jump.addEventListener("click", () => {
        const roundPick = window.prompt(`Round (1-${meta.length})`, String(round + 1));
        if (roundPick == null) return;
        const target = Math.min(Math.max(parseInt(roundPick, 10) || 1, 1), meta.length) - 1;
        const turnPick = window.prompt(`Turn (1-${meta[target].turnCount})`, "1");
        if (turnPick == null) return;
        const turnTarget = Math.min(Math.max(parseInt(turnPick, 10) || 1, 1), meta[target].turnCount) - 1;
        setPlayback(model, target, turnTarget);
    });
    header.appendChild(jump);
    container.appendChild(header);

    const board = elem("div", "shell-section");
    board.appendChild(elem("p", "shell-section-heading", "Leaderboard"));
    const selected = model.get("selected_player") || "";
    (model.get("leaderboard") || []).forEach((entry) => {
        const row = elem("div", "shell-leader-row" + (entry.playerId === selected ? " selected" : ""));
        row.style.setProperty("--accent", entry.color);
        row.appendChild(elem("span", "shell-leader-rank", String(entry.place).padStart(2, "0")));
        const copy = elem("div", "shell-leader-copy");
        copy.appendChild(elem("strong", "shell-leader-name", entry.name));
        copy.appendChild(elem("span", "shell-leader-sub", `${entry.remainingTrains} trains left`));
        row.appendChild(copy);
        row.appendChild(elem("span", "shell-leader-score", String(entry.score)));
        const hands = elem("button", "shell-leader-hands", "🂠");
        hands.title = "View hand";
        hands.addEventListener("click", (event) => {
            event.stopPropagation();
            openStatsModal(model, container.closest(".spectate-shell"), entry.playerId);
        });
        row.appendChild(hands);
        // Row click = culling selection (same contract as PlayerListWidget)
        row.addEventListener("click", () => {
            const current = model.get("selected_player") || "";
            model.set("selected_player", current === entry.playerId ? "" : entry.playerId);
            model.save_changes();
        });
        board.appendChild(row);
    });
    container.appendChild(board);

    const details = elem("details", "shell-aggregates");
    details.appendChild(elem("summary", "shell-section-heading", "Aggregate Stats"));
    const maxAverage = Math.max(1, ...(model.get("aggregates") || []).map((a) => a.averageScore));
    (model.get("aggregates") || []).forEach((entry) => {
        const row = elem("div", "shell-metric-row");
        row.style.setProperty("--accent", entry.color);
        row.appendChild(elem("strong", "shell-leader-name", entry.name));
        row.appendChild(
            elem("span", "shell-metric-values",
                `avg ${entry.averageScore} · best ${entry.bestScore} · wins ${entry.wins}`)
        );
        const bar = elem("div", "shell-metric-bar");
        bar.style.width = `${Math.max(8, (entry.averageScore / maxAverage) * 100)}%`;
        row.appendChild(bar);
        details.appendChild(row);
    });
    container.appendChild(details);
}

function renderStatsCard(model, playerId) {
    const stats = (model.get("stats") || {})[playerId];
    const roster = (model.get("players") || []).find((p) => p.id === playerId) || {};
    const card = elem("div", "shell-stats-card");
    card.style.setProperty("--accent", roster.color || "#888");
    card.appendChild(elem("strong", "shell-leader-name", roster.name || playerId));
    if (!stats) return card;
    const chips = elem("div", "shell-chip-row");
    chips.appendChild(elem("span", "shell-chip", `Score ${stats.score}`));
    chips.appendChild(elem("span", "shell-chip", `Trains ${stats.remainingTrains}`));
    chips.appendChild(elem("span", "shell-chip", `Tickets ${stats.ticketCount}`));
    chips.appendChild(elem("span", "shell-chip", `Routes ${stats.routeCount}`));
    if (stats.hiddenCards != null) chips.appendChild(elem("span", "shell-chip", `Hidden ${stats.hiddenCards}`));
    card.appendChild(chips);
    const hand = elem("div", "shell-hand-row");
    Object.entries(stats.hand || {}).forEach(([color, count]) => {
        const cell = elem("span", `shell-hand-cell hand-${color}`);
        cell.appendChild(elem("span", "shell-hand-dot"));
        cell.appendChild(elem("span", "shell-hand-count", String(count)));
        cell.title = color;
        hand.appendChild(cell);
    });
    card.appendChild(hand);
    return card;
}

function renderTickets(model, container) {
    container.replaceChildren();
    container.appendChild(elem("p", "shell-section-heading", "Destination Tickets"));
    (model.get("tickets") || []).forEach((ticket, index) => {
        const row = elem("div", `shell-ticket-row status-${ticket.status}`);
        row.appendChild(elem("span", "shell-ticket-seq", `Ticket ${String(index + 1).padStart(2, "0")}`));
        row.appendChild(elem("strong", "shell-ticket-route", `${ticket.from} → ${ticket.to}`));
        const badge = ticket.status === "completed" ? "DONE"
            : ticket.status === "cut_off" ? "CUT OFF"
            : ticket.trainsShort != null ? `OPEN · ${ticket.trainsShort} to go` : "OPEN";
        row.appendChild(elem("span", "shell-ticket-badge", badge));
        row.appendChild(elem("span", "shell-ticket-points", `${ticket.points} pts`));
        container.appendChild(row);
    });
}

function render({ model, el }) {
    el.classList.add("spectate-shell");
    const grid = elem("div", "spectate-shell-grid");
    const hero = elem("section", "shell-slot-hero");
    const sidebar = elem("section", "shell-slot-sidebar");
    const market = elem("section", "shell-slot-market");
    const current = elem("section", "shell-slot-current");
    const tickets = elem("section", "shell-slot-tickets");
    grid.append(hero, sidebar, market, current, tickets);
    el.appendChild(grid);

    // Embedded renderers: the graph keeps its force-sim state because its
    // render mounts once here and reacts to trait changes itself.
    routeGraph.render({ model: facadeModel(model, { data: "board" }), el: hero });
    infoBar.render({ model: facadeModel(model, {}), el: market });

    let timer = null;
    const playState = {
        get playing() { return timer != null; },
        toggle() {
            if (timer != null) { clearInterval(timer); timer = null; }
            else {
                timer = setInterval(() => {
                    if (!stepForward(model)) { clearInterval(timer); timer = null; drawSidebar(); }
                }, model.get("interval_ms") || 300);
            }
            drawSidebar();
        },
    };

    const drawSidebar = () => renderSidebar(model, sidebar, playState);
    const drawCurrent = () => {
        current.replaceChildren();
        current.appendChild(elem("p", "shell-section-heading", "Current Player"));
        current.appendChild(renderStatsCard(model, model.get("current_player")));
    };
    const drawTickets = () => renderTickets(model, tickets);

    drawSidebar();
    drawCurrent();
    drawTickets();
    ["change:leaderboard", "change:playback", "change:aggregates", "change:selected_player", "change:rounds_meta"]
        .forEach((event) => model.on(event, drawSidebar));
    ["change:stats", "change:current_player"].forEach((event) => model.on(event, drawCurrent));
    model.on("change:tickets", drawTickets);

    return () => { if (timer != null) clearInterval(timer); };
}

export default { render };
export { renderStatsCard };
```

- [ ] **Step 2: Create the modal stub so the bundle builds** (implemented fully in Task 5)

```js
// widget-src/src/spectate_stats_modal.js
import { renderStatsCard } from "./spectate_shell_widget.js";

function openStatsModal(model, shellRoot, playerId) {
    // Task 5 replaces this stub with the real modal.
    console.log("stats modal stub", playerId);
}

export { openStatsModal };
```

- [ ] **Step 3: Add the entry to the esbuild line** in `widget-src/package.json` — append `src/spectate_shell_widget.js` to the existing `build` script's entry list (before the flags):

```
"build": "esbuild src/route_graph_widget.js src/player_list_widget.js src/info_bar_widget.js src/spectate_shell_widget.js --bundle --format=esm --outdir=../static --define:__RG_BUILD__=\"\\\"$(date -u +%Y%m%d-%H%M%SZ)\\\"\""
```

- [ ] **Step 4: Write the CSS** at `static/spectate_shell_widget.css` — port of the dashboard grid, theme-aware:

```css
/* Dashboard-grid port, themed via light-dark() with light fallbacks. */
.spectate-shell {
    --shell-bg: #f4f2ee;
    --shell-panel: #ffffff;
    --shell-text: #1c1a17;
    --shell-muted: #6b675f;
    --shell-border: rgba(0, 0, 0, 0.12);
    --shell-bg: light-dark(#f4f2ee, #17140f);
    --shell-panel: light-dark(#ffffff, #201c15);
    --shell-text: light-dark(#1c1a17, #f0ece4);
    --shell-muted: light-dark(#6b675f, #a39c8f);
    --shell-border: light-dark(rgba(0, 0, 0, 0.12), rgba(255, 255, 255, 0.12));
    color: var(--shell-text);
    background: var(--shell-bg);
    border-radius: 14px;
    padding: 14px;
    font-family: inherit;
}
.spectate-shell-grid {
    display: grid;
    gap: 14px;
    grid-template-columns: minmax(0, 1fr) 320px;
    grid-template-areas:
        "hero sidebar"
        "market sidebar"
        "current tickets";
}
.shell-slot-hero { grid-area: hero; }
.shell-slot-sidebar { grid-area: sidebar; }
.shell-slot-market { grid-area: market; }
.shell-slot-current { grid-area: current; }
.shell-slot-tickets { grid-area: tickets; }
.shell-slot-hero, .shell-slot-sidebar, .shell-slot-market,
.shell-slot-current, .shell-slot-tickets {
    background: var(--shell-panel);
    border: 1px solid var(--shell-border);
    border-radius: 12px;
    padding: 12px;
    min-width: 0;
}
.shell-eyebrow { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--shell-muted); margin: 0 0 8px; }
.shell-section-heading { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--shell-muted); margin: 12px 0 6px; }
.shell-playback-controls { display: flex; gap: 6px; }
.shell-playback-button, .shell-jump-button {
    background: transparent; color: var(--shell-text);
    border: 1px solid var(--shell-border); border-radius: 8px;
    padding: 6px 10px; cursor: pointer;
}
.shell-jump-button { width: 100%; margin-top: 8px; }
.shell-leader-row, .shell-metric-row {
    display: flex; align-items: center; gap: 8px;
    border-left: 3px solid var(--accent, var(--shell-muted));
    background: color-mix(in srgb, var(--shell-panel) 92%, var(--accent, transparent));
    border-radius: 8px; padding: 8px; margin: 6px 0; cursor: pointer;
}
.shell-leader-row.selected { outline: 2px solid var(--accent, var(--shell-text)); }
.shell-leader-rank { color: var(--shell-muted); font-size: 12px; }
.shell-leader-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.shell-leader-sub, .shell-metric-values { color: var(--shell-muted); font-size: 12px; }
.shell-leader-score { font-size: 18px; font-weight: 700; }
.shell-leader-hands { background: transparent; border: none; cursor: pointer; font-size: 16px; color: var(--shell-text); }
.shell-aggregates summary { cursor: pointer; }
.shell-metric-row { flex-direction: column; align-items: flex-start; cursor: default; }
.shell-metric-bar { height: 4px; border-radius: 2px; background: var(--accent, var(--shell-muted)); }
.shell-stats-card { border-left: 3px solid var(--accent); border-radius: 8px; padding: 8px; }
.shell-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.shell-chip { border: 1px solid var(--shell-border); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.shell-hand-row { display: flex; flex-wrap: wrap; gap: 8px; }
.shell-hand-cell { display: inline-flex; align-items: center; gap: 4px; }
.shell-hand-dot { width: 12px; height: 12px; border-radius: 50%; border: 1px solid var(--shell-border); background: var(--hand-color, #888); }
.hand-black .shell-hand-dot { --hand-color: #35322c; }
.hand-blue .shell-hand-dot { --hand-color: #3b6fb3; }
.hand-green .shell-hand-dot { --hand-color: #3f9c58; }
.hand-locomotive .shell-hand-dot { --hand-color: #b58fd6; }
.hand-orange .shell-hand-dot { --hand-color: #e08a3c; }
.hand-purple .shell-hand-dot { --hand-color: #8d5bb8; }
.hand-red .shell-hand-dot { --hand-color: #d05045; }
.hand-white .shell-hand-dot { --hand-color: #f0ede6; }
.hand-yellow .shell-hand-dot { --hand-color: #d8b93e; }
.shell-ticket-row { display: flex; align-items: center; gap: 8px; border: 1px solid var(--shell-border); border-radius: 8px; padding: 8px; margin: 6px 0; }
.shell-ticket-seq { color: var(--shell-muted); font-size: 11px; text-transform: uppercase; }
.shell-ticket-route { flex: 1; min-width: 0; }
.shell-ticket-badge { font-size: 11px; border: 1px solid var(--shell-border); border-radius: 999px; padding: 2px 8px; }
.shell-ticket-row.status-completed .shell-ticket-badge { border-color: #3f9c58; color: #3f9c58; }
.shell-ticket-row.status-cut_off .shell-ticket-badge { border-color: #d05045; color: #d05045; }
.shell-ticket-points { font-weight: 700; }
@media (max-width: 980px) {
    .spectate-shell-grid { grid-template-columns: 1fr; grid-template-areas: "hero" "sidebar" "market" "current" "tickets"; }
}
```

- [ ] **Step 5: Build and verify the bundle**

Run: `cd applications/notebook_harness/widget-src && npm run build`
Expected: exits 0; `ls ../static/spectate_shell_widget.js` exists.

- [ ] **Step 6: Commit**

```bash
git add applications/notebook_harness/widget-src applications/notebook_harness/static/spectate_shell_widget.css applications/notebook_harness/static/spectate_shell_widget.js applications/notebook_harness/static/info_bar_widget.js applications/notebook_harness/static/player_list_widget.js applications/notebook_harness/static/route_graph_widget.js
git commit -m "feat(harness): spectate shell JS/CSS with dashboard grid layout"
```

### Task 5: Player-hands stats modal

**Files:**
- Modify: `applications/notebook_harness/widget-src/src/spectate_stats_modal.js` (replace stub)
- Modify: `applications/notebook_harness/static/spectate_shell_widget.css` (append modal styles)

**Interfaces:**
- Consumes: `renderStatsCard(model, playerId)` from `spectate_shell_widget.js`; `stats` trait (full hands, in-kernel omniscient).
- Produces: `openStatsModal(model, shellRoot, playerId)` — backdrop + dialog appended to `shellRoot`, closed by backdrop click, close button, or Escape.

- [ ] **Step 1: Implement the modal**

```js
// widget-src/src/spectate_stats_modal.js
import { renderStatsCard } from "./spectate_shell_widget.js";

function openStatsModal(model, shellRoot, playerId) {
    if (!shellRoot || shellRoot.querySelector(".shell-stats-backdrop")) return;

    const backdrop = document.createElement("div");
    backdrop.className = "shell-stats-backdrop";
    const dialog = document.createElement("div");
    dialog.className = "shell-stats-modal";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");

    const close = () => {
        backdrop.remove();
        document.removeEventListener("keydown", onKey);
        model.off("change:stats", refresh);
    };
    const onKey = (event) => { if (event.key === "Escape") close(); };

    const header = document.createElement("div");
    header.className = "shell-stats-modal-header";
    const title = document.createElement("p");
    title.className = "shell-eyebrow";
    title.textContent = "Player Stats";
    const closeButton = document.createElement("button");
    closeButton.className = "shell-playback-button";
    closeButton.textContent = "✕";
    closeButton.setAttribute("aria-label", "Close player stats");
    closeButton.addEventListener("click", close);
    header.append(title, closeButton);

    const body = document.createElement("div");
    const refresh = () => body.replaceChildren(renderStatsCard(model, playerId));
    refresh();
    model.on("change:stats", refresh);

    dialog.append(header, body);
    dialog.addEventListener("click", (event) => event.stopPropagation());
    backdrop.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    backdrop.appendChild(dialog);
    shellRoot.appendChild(backdrop);
}

export { openStatsModal };
```

- [ ] **Step 2: Append modal CSS** to `static/spectate_shell_widget.css`:

```css
.shell-stats-backdrop {
    position: absolute; inset: 0; z-index: 10;
    background: rgba(0, 0, 0, 0.45);
    display: flex; align-items: center; justify-content: center;
    border-radius: 14px;
}
.spectate-shell { position: relative; }
.shell-stats-modal {
    background: var(--shell-panel); color: var(--shell-text);
    border: 1px solid var(--shell-border); border-radius: 12px;
    padding: 14px; min-width: 320px; max-width: 90%;
}
.shell-stats-modal-header { display: flex; justify-content: space-between; align-items: center; }
```

- [ ] **Step 3: Rebuild and verify**

Run: `cd applications/notebook_harness/widget-src && npm run build`
Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add applications/notebook_harness/widget-src/src/spectate_stats_modal.js applications/notebook_harness/static
git commit -m "feat(harness): player-hands stats modal in spectate shell"
```

### Task 6: Rewire spectate.py and the bot notebooks

**Files:**
- Modify: `applications/notebook_harness/spectate.py`
- Modify: `integrations/external/bots/random_bot.py:47-78` (spectate cells)
- Modify: `integrations/external/bots/example_bot.py` (same cells)
- Modify: `integrations/external/templates/bots/build_your_bot_here.py` (same cells)
- Test: `quality/tests/test_notebook_harness_spectate.py` (update)

**Interfaces:**
- Consumes: `initialize_series`, `build_shell`, `update_shell`.
- Produces: `spectate_controls(mo, *, bot_name, bot_class, title=None) -> (map_picker, seat_pickers, rounds_picker)`; `play_match(mo, map_picker, seat_pickers, rounds_picker=None) -> HarnessSeries`; `spectate_widgets(mo, harness_series) -> shell` (single `mo.ui.anywidget`); `spectate_view(mo, harness_series, shell) -> None`.

- [ ] **Step 1: Update the failing tests first.** In `test_notebook_harness_spectate.py`, keep the existing FakeMo scaffolding; update assertions to the new contract:
  - `spectate_controls` returns a 3-tuple whose third element is a number picker created via `mo.ui.number(start=1, stop=20, value=1, label="Rounds")` (add a `FakeNumber` fake mirroring `FakeDropdown`).
  - `play_match` with a fake rounds picker of value 2 returns an object with `round_count() == 2` (patch `initialize_series` with a `Mock` and assert it was called with the seated bot classes, map value, and `rounds=2`).
  - `spectate_widgets` returns the single value of `mo.ui.anywidget(...)` (one call, not four).
  - `spectate_view` calls `update_shell(shell, series)` (patch it) and appends the shell once.

Run: `uv run python -m unittest quality.tests.test_notebook_harness_spectate -v`
Expected: FAIL on the new assertions.

- [ ] **Step 2: Rewrite `spectate.py` bodies** (docstring contract stays: 4 cells, widgets created once per game, view mutates):

```python
def spectate_controls(mo: Any, *, bot_name: str, bot_class: type, title: str | None = None):
    from notebook_harness.game_runner import available_bots, list_maps

    maps = list_maps()
    bot_options = {"(empty)": None, **available_bots()}
    bot_options[bot_name] = bot_class

    if title:
        mo.output.append(mo.md(f"# {title} - spectate & debug").left())

    map_picker = mo.ui.dropdown(options=maps, value=maps[0], label="Map")
    rounds_picker = mo.ui.number(start=1, stop=20, value=1, label="Rounds")
    seat_pickers = mo.ui.array(
        [
            mo.ui.dropdown(
                options=bot_options,
                value=bot_name if index < 2 else "(empty)",
                label=f"Seat {index + 1}",
            )
            for index in range(5)
        ]
    )
    mo.output.append(mo.hstack([map_picker, rounds_picker, seat_pickers], align="start", justify="start"))
    return map_picker, seat_pickers, rounds_picker


def play_match(mo: Any, map_picker: Any, seat_pickers: Any, rounds_picker: Any = None):
    from notebook_harness.game_runner import initialize_series

    seated_bot_classes = [bot_class for bot_class in seat_pickers.value if bot_class is not None]
    mo.stop(len(seated_bot_classes) < 2, mo.md("Pick bots for at least two seats to run a game."))

    rounds = int(rounds_picker.value) if rounds_picker is not None else 1
    series = initialize_series(seated_bot_classes, map_name=map_picker.value, rounds=rounds)
    series.play()
    return series


def spectate_widgets(mo: Any, harness_series: Any):
    """Create the shell once per series; playback/selection state lives in
    the widget, so force-sim node positions persist across steps."""
    from notebook_harness.spectate_shell_widget import build_shell

    return mo.ui.anywidget(build_shell(harness_series))


def spectate_view(mo: Any, harness_series: Any, shell: Any) -> None:
    """Push the shell's current playback/selection into fresh payloads and
    display it. Runs reactively whenever the shell's value changes."""
    from notebook_harness.spectate_shell_widget import update_shell

    update_shell(shell, harness_series)
    mo.output.append(shell)
```

Delete `_selected_player`, `_slider_step`, and `_load_widget_classes` (the shell supersedes them); keep the module docstring but update the four-cell description.

- [ ] **Step 3: Update the three notebooks' spectate cells** (`random_bot.py`, `example_bot.py`, `build_your_bot_here.py`) to the new arity — pattern for each:

```python
    map_picker, seat_pickers, rounds_picker = spectate_controls(...)   # cell: controls
    harness_game = play_match(mo, map_picker, seat_pickers, rounds_picker)  # cell: game
    shell = spectate_widgets(mo, harness_game)                          # cell: widgets
    spectate_view(mo, harness_game, shell)                              # cell: view
```

Keep marimo's cell return-tuple syntax matching each notebook's existing style.

- [ ] **Step 4: Run tests**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_spectate -v` then `uv run test`
Expected: PASS.

- [ ] **Step 5: End-to-end verification in the real app** — launch a bot notebook and drive it:

```bash
uv run marimo edit integrations/external/bots/random_bot.py --headless --port 2718 &
```

Then screenshot with headless Chrome (`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --screenshot=/tmp/shell.png ...`) or open interactively. Verify: grid layout renders (hero graph + sidebar + market + current + tickets), rounds picker of 2 produces two rounds in Jump-To, leaderboard click culls the board, 🂠 opens the hands modal, Aggregate Stats collapses/expands.

- [ ] **Step 6: Commit**

```bash
git add applications/notebook_harness/spectate.py integrations/external quality/tests/test_notebook_harness_spectate.py
git commit -m "feat(harness): spectate pipeline drives the shell widget with rounds"
```

---

# Phase B — stored-match replay in the widget

### Task 7: Persist mapName and seed on matches

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/bootstrap_pocketbase.py:37` (matches fields list)
- Modify: `services/native-runtime/src/ticket_to_ride/backend/models.py:20-27` (`MatchCreateRequest`) and the match response models (`MatchResponse`/detail, `models.py:180-220`)
- Modify: `services/native-runtime/src/ticket_to_ride/backend/repository.py:38,189` and `backend/pocketbase.py:78` (`create_match` implementations)
- Modify: `services/native-runtime/src/ticket_to_ride/backend/service.py:96-102` (`create_match`), plus the match-detail assembly (`service.py:~160-180`)
- Modify: `services/native-runtime/src/ticket_to_ride/backend/app.py` (`POST /matches` handler passes the new fields)
- Modify: `services/native-runtime/src/ticket_to_ride/logging/game_logger.py:154-164` (`start_match`)
- Modify: `services/native-runtime/src/ticket_to_ride/runtime/cli.py:557` and `backend/runtime/managed_match_runtime.py:193` (call sites pass map/seed from their `GameContext`)
- Test: `quality/tests/test_logger_integration.py` (extend), `quality/tests/test_managed_match_api.py` (extend)

**Interfaces:**
- Consumes: `GameContext.seed`, `context.get_map().map_name`.
- Produces: `MatchCreateRequest.mapName: Optional[str]`, `.seed: Optional[int]`; both echoed on match detail responses; `GameLogger.start_match(match_name=None, map_name=None, seed=None)`.

- [ ] **Step 1: Write failing tests.** In `test_logger_integration.py`, extend the existing in-memory-backend test to call `logger.start_match("alpha-beta", map_name="classic", seed=1234)` and assert `GET /matches/{id}` payload contains `"mapName": "classic"` and `"seed": 1234`. Add a default-behavior assertion: omitted values yield `None` fields (not KeyError).

Run: `uv run python -m unittest quality.tests.test_logger_integration -v`
Expected: FAIL — unexpected keyword `map_name`.

- [ ] **Step 2: Thread the fields through, bottom-up:**
  - `bootstrap_pocketbase.py`: add to the matches collection field list: `{"name": "mapName", "type": "text", "required": False}` and `{"name": "seed", "type": "number", "required": False}`.
  - `models.py`: `MatchCreateRequest` gains `mapName: Optional[str] = None` and `seed: Optional[int] = None`; match response models gain the same optional fields.
  - `repository.py` (abstract + in-memory) and `pocketbase.py`: `create_match(self, name, players, player_names=None, map_name=None, seed=None)`; in-memory stores `"mapName": map_name, "seed": seed` on the record; PocketBase payload adds the same keys.
  - `service.py`: `create_match` passes through; match-detail assembly copies `mapName`/`seed` from the record with `.get(...)`.
  - `app.py`: `POST /matches` handler forwards `request.mapName`, `request.seed`.
  - `game_logger.py`: `start_match(self, match_name=None, map_name=None, seed=None)` includes `"mapName": map_name, "seed": seed` in the payload when not None.
  - Call sites: `cli.py:557` → `logger.start_match("-".join(...), map_name=context.get_map().map_name, seed=context.seed)`; `managed_match_runtime.py:193` likewise from its context.

- [ ] **Step 3: Run the touched suites, then the full suite**

Run: `uv run python -m unittest quality.tests.test_logger_integration quality.tests.test_managed_match_api -v` then `uv run test`
Expected: PASS. (PocketBase-backed E2E: with `uv run run` up, a new match record in the PocketBase admin UI shows both fields — manual spot check.)

- [ ] **Step 4: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride quality/tests
git commit -m "feat(backend): persist mapName and seed on match records"
```

### Task 8: StoredMatchSeries — series protocol over stored payloads

**Files:**
- Create: `applications/notebook_harness/stored_match.py`
- Test: `quality/tests/test_notebook_harness_stored_match.py` (create)

**Interfaces:**
- Consumes: match detail payload shape (`GET /matches/{id}`): `{"name", "players": [{playerId, name, color}], "mapName", "seed", "rounds": [{"roundNumber", "turns": [turnState, ...]}], "averageScores"}` where each turn is the serializer's `turnState`; `MapGraph`, `contract_map`, `claimed_by_from_snapshot`, `build_nodes`, `build_edges`, `build_culled_nodes`, `build_culled_edges` from `notebook_harness.rendering`; `card_color_hex`.
- Produces: `StoredMatchSeries` implementing the full series protocol; `load_stored_match(match_id: str, api_base: str = "http://127.0.0.1:8000") -> StoredMatchSeries` (urllib fetch); `list_stored_matches(api_base) -> List[dict]`.

Notes that shape the implementation:
- `market_at` is snapshot-only: `{"face_up": turnState["gameObjects"]["decks"]["marketCards"], "deck_count": None, "discard_count": None, "pie": [], "pie_label": "Unavailable for stored matches", "colors": card_color_hex()}` — exactly dashboard-level market fidelity. The JS info bar must tolerate `deck_count: None` (verify; if it renders "null", guard it in JS as part of this task).
- `stats_at`: the active player's row has a full `hand`; opponents have `hand["public"]` + `hand["hidden"]` — map to `{"hand": public_counts, "hiddenCards": hidden}` (this is why the trait carries `hiddenCards`).
- `tickets_at`: only the active player's tickets exist per snapshot (`destinationTickets` with `completed`); for other players return the most recent snapshot where that player was active (walk backwards; empty list if none). `status` is `"completed"`/`"open"`, `trainsShort` always `None`.
- `aggregates`: per-round final scores from each round's last turn, same computation as `HarnessSeries.aggregates`.
- Board: `MapGraph(player_count=len(players), map_name=payload["mapName"] or DEFAULT_MAP_NAME)` built once in `__init__`; culled views via `contract_map(map_graph.routes, map_graph.player_count, claimed_by, viewpoint)`.

- [ ] **Step 1: Write failing tests** using a fixture payload — generate it from a real game so shapes never drift:

```python
# quality/tests/test_notebook_harness_stored_match.py
from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import initialize_series
from notebook_harness.stored_match import StoredMatchSeries


def _payload_from_series(series) -> dict:
    """Build a GET /matches/{id}-shaped payload from played in-kernel games."""
    return {
        "name": "fixture",
        "players": [
            {"playerId": p["id"], "name": p["name"], "color": p["color"]}
            for p in series.roster()
        ],
        "mapName": "classic",
        "seed": series.games[0].game.context.seed,
        "rounds": [
            {
                "roundNumber": index,
                "turns": [s["turnState"] for s in game.logger.snapshots],
            }
            for index, game in enumerate(series.games)
        ],
        "averageScores": [],
    }


class StoredMatchSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        live = initialize_series([RandomBot, RandomBot], rounds=2, seed=11)
        live.play()
        cls.live = live
        cls.stored = StoredMatchSeries(_payload_from_series(live))

    def test_protocol_shape_matches_live_series(self) -> None:
        self.assertEqual(self.stored.roster(), self.live.roster())
        self.assertEqual(self.stored.round_count(), 2)
        self.assertEqual(self.stored.rounds_meta(), self.live.rounds_meta())
        self.assertEqual(self.stored.active_player_at(0, 0), self.live.active_player_at(0, 0))
        self.assertEqual(self.stored.leaderboard_at(0, 3), self.live.leaderboard_at(0, 3))
        self.assertEqual(self.stored.aggregates(), self.live.aggregates())

    def test_board_at_matches_live_series(self) -> None:
        stored_nodes, stored_edges = self.stored.board_at(0, 5)
        live_nodes, live_edges = self.live.board_at(0, 5)
        self.assertEqual(stored_nodes, live_nodes)
        self.assertEqual(stored_edges, live_edges)

    def test_market_is_snapshot_only(self) -> None:
        market = self.stored.market_at(0, 0)
        self.assertEqual(market["pie"], [])
        self.assertIsNone(market["deck_count"])
        self.assertEqual(
            market["face_up"],
            self.live.games[0].logger.snapshots[0]["turnState"]["gameObjects"]["decks"]["marketCards"],
        )

    def test_stats_expose_partial_opponent_hands(self) -> None:
        stats = self.stored.stats_at(0, 0)
        active = self.stored.active_player_at(0, 0)
        other = next(pid for pid in stats if pid != active)
        self.assertIsNone(stats[active]["hiddenCards"])
        self.assertIsInstance(stats[other]["hiddenCards"], int)

    def test_tickets_fall_back_to_latest_owned_snapshot(self) -> None:
        active = self.stored.active_player_at(0, 0)
        tickets = self.stored.tickets_at(0, 0, active)
        self.assertGreater(len(tickets), 0)
        for ticket in tickets:
            self.assertIn(ticket["status"], {"open", "completed"})
            self.assertIsNone(ticket["trainsShort"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_stored_match -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `stored_match.py`** per the notes above. Skeleton:

```python
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.request import Request, urlopen

from ticket_to_ride.board_view import card_color_hex
from ticket_to_ride.engine.state.map import DEFAULT_MAP_NAME, MapGraph, contract_map

from notebook_harness.rendering import (
    build_culled_edges, build_culled_nodes, build_edges, build_nodes,
    claimed_by_from_snapshot,
)

DEFAULT_API_BASE = "http://127.0.0.1:8000"


class StoredMatchSeries:
    """Series-protocol adapter over a stored GET /matches/{id} payload.
    Snapshot-backed: no replay, so market odds and trains-short are
    unavailable — the same fidelity the viewer dashboard had."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self._rounds: List[List[Dict[str, Any]]] = [
            list(round_record.get("turns", [])) for round_record in payload.get("rounds", [])
        ]
        self._map_graph = MapGraph(
            player_count=len(payload["players"]),
            map_name=payload.get("mapName") or DEFAULT_MAP_NAME,
        )
        self._colors = {p["playerId"]: p["color"] for p in payload["players"]}

    def _turn(self, round_index: int, turn_index: int) -> Dict[str, Any]:
        return self._rounds[round_index][turn_index]

    def _rows(self, round_index: int, turn_index: int) -> List[Dict[str, Any]]:
        state = self._turn(round_index, turn_index)
        return [state["player"], *state["opponents"]]

    def roster(self) -> List[Dict[str, str]]:
        return [
            {"id": p["playerId"], "name": p["name"], "color": p["color"]}
            for p in self.payload["players"]
        ]

    def round_count(self) -> int:
        return len(self._rounds)

    def turn_count(self, round_index: int) -> int:
        return len(self._rounds[round_index])

    def rounds_meta(self) -> List[Dict[str, int]]:
        return [
            {"roundNumber": index, "turnCount": len(turns)}
            for index, turns in enumerate(self._rounds)
        ]

    def active_player_at(self, round_index: int, turn_index: int) -> str:
        return self._turn(round_index, turn_index)["player"]["playerId"]

    def board_at(self, round_index: int, turn_index: int, viewpoint: 'str | None' = None) -> Tuple[List, List]:
        claimed_by = claimed_by_from_snapshot(self._turn(round_index, turn_index))
        if viewpoint is not None:
            culled = contract_map(
                self._map_graph.routes, self._map_graph.player_count, claimed_by, viewpoint
            )
            return build_culled_nodes(culled), build_culled_edges(culled)
        return (
            build_nodes(self._map_graph),
            build_edges(self._map_graph, claimed_by, self._colors),
        )

    def market_at(self, round_index: int, turn_index: int, viewpoint: 'str | None' = None) -> Dict[str, Any]:
        decks = self._turn(round_index, turn_index).get("gameObjects", {}).get("decks", {})
        return {
            "face_up": list(decks.get("marketCards", [])),
            "deck_count": None,
            "discard_count": None,
            "pie": [],
            "pie_label": "Unavailable for stored matches",
            "colors": card_color_hex(),
        }

    def leaderboard_at(self, round_index: int, turn_index: int) -> List[Dict[str, Any]]:
        meta = {entry["id"]: entry for entry in self.roster()}
        rows = sorted(self._rows(round_index, turn_index), key=lambda row: -row["score"])
        return [
            {
                "playerId": row["playerId"],
                "name": meta[row["playerId"]]["name"],
                "color": meta[row["playerId"]]["color"],
                "score": row["score"],
                "remainingTrains": row["remainingTrains"],
                "place": place,
            }
            for place, row in enumerate(rows, start=1)
        ]

    def stats_at(self, round_index: int, turn_index: int) -> Dict[str, Dict[str, Any]]:
        state = self._turn(round_index, turn_index)
        stats: Dict[str, Dict[str, Any]] = {}
        active = state["player"]
        stats[active["playerId"]] = {
            "hand": dict(active["hand"]),
            "hiddenCards": None,
            "score": active["score"],
            "remainingTrains": active["remainingTrains"],
            "ticketCount": len(active["destinationTickets"]),
            "routeCount": len(active["claimedRoutes"]),
        }
        for opponent in state["opponents"]:
            stats[opponent["playerId"]] = {
                "hand": dict(opponent["hand"]["public"]),
                "hiddenCards": opponent["hand"]["hidden"],
                "score": opponent["score"],
                "remainingTrains": opponent["remainingTrains"],
                "ticketCount": opponent["destinationTicketCount"],
                "routeCount": len(opponent["claimedRoutes"]),
            }
        return stats

    def tickets_at(self, round_index: int, turn_index: int, player_id: str) -> List[Dict[str, Any]]:
        for turn in reversed(self._rounds[round_index][: turn_index + 1]):
            if turn["player"]["playerId"] == player_id:
                return [
                    {
                        "from": ticket["from"],
                        "to": ticket["to"],
                        "points": ticket["points"],
                        "status": "completed" if ticket["completed"] else "open",
                        "trainsShort": None,
                    }
                    for ticket in turn["player"]["destinationTickets"]
                ]
        return []

    def aggregates(self) -> List[Dict[str, Any]]:
        meta = self.roster()
        scores: Dict[str, List[int]] = {entry["id"]: [] for entry in meta}
        wins: Dict[str, int] = {entry["id"]: 0 for entry in meta}
        for round_index, turns in enumerate(self._rounds):
            if not turns:
                continue
            final = self.leaderboard_at(round_index, len(turns) - 1)
            for row in final:
                scores[row["playerId"]].append(row["score"])
            wins[final[0]["playerId"]] += 1
        return [
            {
                "playerId": entry["id"],
                "name": entry["name"],
                "color": entry["color"],
                "scores": scores[entry["id"]],
                "averageScore": round(sum(scores[entry["id"]]) / max(len(scores[entry["id"]]), 1), 1),
                "bestScore": max(scores[entry["id"]], default=0),
                "wins": wins[entry["id"]],
            }
            for entry in meta
        ]
```

`leaderboard_at`/`stats_at`/`active_player_at` mirror `HarnessGame`'s snapshot-row logic (import nothing from it — rows come straight from the stored turnState). `board_at` uses `claimed_by_from_snapshot(turn_state)` + `build_nodes`/`build_edges` (spectator) or `contract_map` + culled builders (viewpoint). `tickets_at(r, t, player_id)`: scan `self._rounds[r][: t + 1]` backwards for a turn whose `player.playerId == player_id`, map its `destinationTickets`.

Then the fetch helpers:

```python
def _get_json(url: str) -> Any:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def list_stored_matches(api_base: str = DEFAULT_API_BASE) -> List[Dict[str, Any]]:
    return _get_json(f"{api_base.rstrip('/')}/matches")


def load_stored_match(match_id: str, api_base: str = DEFAULT_API_BASE) -> StoredMatchSeries:
    return StoredMatchSeries(_get_json(f"{api_base.rstrip('/')}/matches/{match_id}"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_stored_match -v`
Expected: PASS (5 tests). If `test_board_at_matches_live_series` reveals ordering differences between live and stored edge building, fix `StoredMatchSeries` (not the test) — both must render identically from the same claims.

- [ ] **Step 5: Full suite, commit**

```bash
uv run test
git add applications/notebook_harness/stored_match.py quality/tests/test_notebook_harness_stored_match.py
git commit -m "feat(harness): StoredMatchSeries adapts stored matches to the series protocol"
```

### Task 9: Replay notebook — browse stored matches in the shell

**Files:**
- Create: `applications/notebook_harness/replay.py` (marimo notebook)
- Modify: `applications/notebook_harness/spectate.py` (add `replay_controls` + `load_replay`)
- Test: `quality/tests/test_notebook_harness_spectate.py` (extend)

**Interfaces:**
- Consumes: `list_stored_matches`, `load_stored_match`, `spectate_widgets`, `spectate_view` (already series-protocol-agnostic).
- Produces: `replay_controls(mo, api_base=DEFAULT_API_BASE) -> match_picker` (dropdown of `{name (id-prefix): matchId}`); `load_replay(mo, match_picker, api_base=DEFAULT_API_BASE) -> StoredMatchSeries`.

- [ ] **Step 1: Write failing tests** (extend `test_notebook_harness_spectate.py`): patch `notebook_harness.stored_match.list_stored_matches` to return two fixture rows `[{"matchId": "m1", "name": "Alpha"}, ...]`, assert `replay_controls` builds a dropdown whose options map display names to ids and appends it to output; patch `load_stored_match` and assert `load_replay` calls it with the picker's value and `mo.stop`s when nothing is selected.

Run: `uv run python -m unittest quality.tests.test_notebook_harness_spectate -v` — expected: FAIL.

- [ ] **Step 2: Implement in `spectate.py`:**

```python
def replay_controls(mo: Any, api_base: str | None = None):
    """Dropdown over stored backend matches for the replay notebook."""
    from notebook_harness.stored_match import DEFAULT_API_BASE, list_stored_matches

    base = api_base or DEFAULT_API_BASE
    matches = list_stored_matches(base)
    mo.stop(not matches, mo.md(f"No stored matches at {base}. Run `uv run run` and play one."))
    options = {
        f"{record.get('name') or record['matchId']} ({record['matchId'][:8]})": record["matchId"]
        for record in matches
    }
    first = next(iter(options))
    match_picker = mo.ui.dropdown(options=options, value=first, label="Stored match")
    mo.output.append(match_picker)
    return match_picker


def load_replay(mo: Any, match_picker: Any, api_base: str | None = None):
    from notebook_harness.stored_match import DEFAULT_API_BASE, load_stored_match

    mo.stop(not match_picker.value, mo.md("Pick a stored match to replay."))
    return load_stored_match(match_picker.value, api_base or DEFAULT_API_BASE)
```

- [ ] **Step 3: Create `applications/notebook_harness/replay.py`** — a 4-cell marimo notebook mirroring the bot-notebook structure (copy cell scaffolding from `integrations/external/bots/random_bot.py`): imports → `match_picker = replay_controls(mo)` → `series = load_replay(mo, match_picker)` → `shell = spectate_widgets(mo, series)` → `spectate_view(mo, series, shell)`.

- [ ] **Step 4: Run tests, then verify end-to-end**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_spectate -v` then `uv run test` — expected: PASS.

E2E: with `uv run run` running (backend :8000 has the bootstrap match), `uv run marimo edit applications/notebook_harness/replay.py`, pick the stored match, confirm the shell renders it and playback/jump/leaderboard/tickets work; market shows face-up cards with the "Unavailable for stored matches" pie label.

- [ ] **Step 5: Commit**

```bash
git add applications/notebook_harness/replay.py applications/notebook_harness/spectate.py quality/tests/test_notebook_harness_spectate.py
git commit -m "feat(harness): stored-match replay notebook over the spectate shell"
```

---

## Final verification (after all tasks)

- [ ] `uv run test` — entire suite green.
- [ ] `cd applications/notebook_harness/widget-src && npm run build` — clean build.
- [ ] Manual drive of `random_bot.py` notebook: 2 seats, 3 rounds → grid layout, playback, jump modal, culling, hands modal, collapsible aggregates, tickets with trains-short.
- [ ] Manual drive of `replay.py` against `uv run run` backend.
- [ ] Only after both: the viewer dashboard is officially redundant for replay viewing — retiring it is a separate decision/plan (the `/bots` hub work from earlier discussion).
