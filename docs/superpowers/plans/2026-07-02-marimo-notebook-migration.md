# Marimo Notebook Bot-Authoring & Spectating Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give bot developers a marimo notebook per bot where they edit the bot's `BaseBot` subclass directly and watch it play in-process games rendered on a `wigglystuff.GraphWidget` board, stepped through with `wigglystuff.PlaySlider` — while the existing FastAPI/PocketBase/managed-match/bot-sandbox stack keeps running real matches unchanged.

**Architecture:** A new pure-Python "notebook harness" package (`applications/notebook_harness/`) builds in-process test games against the existing engine and produces GraphWidget-ready node/edge data from an in-memory turn log (no PocketBase dependency). The two existing bots become canonical marimo notebook files in place, using marimo's documented reusable-cell mechanism so the existing `BotLoader` needs no changes. A minimal addition to the existing React viewer and backend lets a developer click a bot and have a `marimo edit` server spun up for its notebook.

**Tech Stack:** Python 3.12, marimo, anywidget, wigglystuff (GraphWidget, PlaySlider), the existing `ticket_to_ride` engine, FastAPI, React (existing `applications/viewer` hyperscript components).

**Reference spec:** `docs/superpowers/specs/2026-07-02-marimo-notebook-migration-design.md`

---

## Before You Start

Run the existing suite once to get a clean baseline:

```bash
uv run test
```

Expected: all tests pass. If they don't, stop and investigate before starting this plan — you need a green baseline to trust the "run tests, verify pass" steps below.

---

### Task 1: Selectable map support in the engine

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/map.py`
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/game_context.py`
- Move: `operations/data/map.csv` → `operations/data/maps/classic.csv`
- Test: `quality/tests/test_map_selection.py`

Today `MapGraph` hardcodes a single CSV path and takes no map selector. The notebook harness needs to list and pick a map, so this task adds that mechanism (one map registered, no new map content authored).

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_map_selection.py`:

```python
import unittest

from ticket_to_ride.engine.state.map import (
    DEFAULT_MAP_NAME,
    MapGraph,
    available_maps,
    resolve_map_path,
)


class MapSelectionTests(unittest.TestCase):
    def test_available_maps_includes_the_default_map(self) -> None:
        self.assertIn(DEFAULT_MAP_NAME, available_maps())

    def test_resolve_map_path_rejects_unknown_map_names(self) -> None:
        with self.assertRaises(ValueError):
            resolve_map_path("not-a-real-map")

    def test_map_graph_defaults_to_the_classic_map(self) -> None:
        game_map = MapGraph(player_count=2)

        self.assertEqual(game_map.map_name, DEFAULT_MAP_NAME)
        self.assertTrue(len(game_map.routes) > 0)

    def test_map_graph_accepts_an_explicit_map_name(self) -> None:
        game_map = MapGraph(player_count=2, map_name=DEFAULT_MAP_NAME)

        self.assertEqual(game_map.map_name, DEFAULT_MAP_NAME)
        self.assertTrue(len(game_map.routes) > 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_map_selection -v`
Expected: FAIL/ERROR — `available_maps`, `resolve_map_path`, and `DEFAULT_MAP_NAME` don't exist yet.

- [ ] **Step 3: Implement the map-selection mechanism**

In `services/native-runtime/src/ticket_to_ride/engine/state/map.py`, replace the current `MAP_CSV_PATH` constant and `MapGraph.__init__`/`_load_routes_from_csv` call with:

```python
import csv
from collections import Counter
from pathlib import Path
from typing import List, Dict, Optional, Set


MAPS_DIR = Path(__file__).resolve().parents[6] / "operations" / "data" / "maps"
DEFAULT_MAP_NAME = "classic"


def available_maps() -> List[str]:
    """Return the names of every map CSV available under the maps directory."""
    return sorted(path.stem for path in MAPS_DIR.glob("*.csv"))


def resolve_map_path(map_name: Optional[str]) -> Path:
    """Resolve a map name to its CSV path, defaulting to the classic map."""
    resolved_name = map_name or DEFAULT_MAP_NAME
    map_path = MAPS_DIR / f"{resolved_name}.csv"
    if not map_path.exists():
        raise ValueError(f"Unknown map '{resolved_name}'. Available maps: {available_maps()}")
    return map_path

# ... Route class is unchanged ...

class MapGraph:
    def __init__(self, player_count: int = 4, map_name: Optional[str] = None):
        """Load the map and prepare tracking of routes and paths."""
        self.player_count = player_count
        self.map_name = map_name or DEFAULT_MAP_NAME
        self.longest_path_holder: str = ""
        self.longest_paths: Dict[str,int] = {}
        self.routes: List[Route] = []
        self._load_routes_from_csv(resolve_map_path(map_name))

        #paths hold dicts that associate player_ids with a list comprised of tuples containing (sets of connected cities, longest path length)
        self.paths: 'Dict[str,List[tuple[set[str],int]]]' = {}
        self.longest_paths: Dict[str,int]
        self.longest_path_holder: str

        self._adj: Dict[str, List[Route]] = {}
        self._build_adjacency()
```

Leave `Route`, `_load_routes_from_csv`, `_build_adjacency`, and every other method on `MapGraph` untouched — only the constructor signature and the module-level constants change.

- [ ] **Step 4: Move the map CSV into the new maps directory**

```bash
mkdir -p operations/data/maps
git mv operations/data/map.csv operations/data/maps/classic.csv
```

- [ ] **Step 5: Run the new test and the full suite to verify everything passes**

Run: `uv run python -m unittest quality.tests.test_map_selection -v`
Expected: PASS (4 tests)

Run: `uv run test`
Expected: all tests still pass — `test_map_rules.py` and everything else that calls `MapGraph(player_count=N)` without a `map_name` keeps working via the default.

- [ ] **Step 6: Thread `map_name` through `GameContext`**

In `services/native-runtime/src/ticket_to_ride/engine/state/game_context.py`, change the constructor:

```python
from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.decks import TrainCardDeck, TicketDeck

from collections import Counter
from typing import Dict, List, Optional



class GameContext:
    def __init__(self, player_ids, map_name: Optional[str] = None):
        """Holds shared state used throughout the gameplay loop."""
        print("Initializing GameContext...")
        self.map_graph = MapGraph(player_count=len(player_ids), map_name=map_name)
        self.train_deck = TrainCardDeck()
        self.ticket_deck = TicketDeck()
        self.turn_num = 0
        # initialize score dictionary for all players
        # each player starts with a score of 0
        self.scores = {p: 0 for p in player_ids}
```

Add this test to `quality/tests/test_map_selection.py` (append inside the existing class, above `if __name__ == "__main__":`):

```python
    def test_game_context_passes_map_name_through_to_the_map_graph(self) -> None:
        from ticket_to_ride.engine.state.game_context import GameContext

        context = GameContext(["bot_1", "bot_2"], map_name=DEFAULT_MAP_NAME)

        self.assertEqual(context.get_map().map_name, DEFAULT_MAP_NAME)
```

- [ ] **Step 7: Run the full suite again**

Run: `uv run test`
Expected: all tests pass, including the new `test_game_context_passes_map_name_through_to_the_map_graph`.

- [ ] **Step 8: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/state/map.py \
        services/native-runtime/src/ticket_to_ride/engine/state/game_context.py \
        operations/data/maps/classic.csv \
        quality/tests/test_map_selection.py
git commit -m "$(cat <<'EOF'
Add selectable-map mechanism to the engine

MapGraph and GameContext now accept an optional map_name, resolved
against a maps/ directory instead of a single hardcoded CSV path.
Only the existing map is migrated; no new maps are authored.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add marimo/anywidget/wigglystuff as an optional dependency group

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the optional dependency group**

In `pyproject.toml`, add a new table after `[project]`'s `dependencies` list:

```toml
[project.optional-dependencies]
notebooks = [
  "marimo>=0.9",
  "anywidget>=0.9",
  "wigglystuff>=0.1",
]
```

- [ ] **Step 2: Install the group and verify the packages resolve**

Run: `uv sync --extra notebooks`
Expected: completes without error; `marimo`, `anywidget`, and `wigglystuff` appear in `uv.lock`.

- [ ] **Step 3: Verify the marimo CLI entry points you'll rely on later actually exist in the installed version**

Run:
```bash
uv run --extra notebooks marimo --help
uv run --extra notebooks python -m marimo edit --help
```
Expected: both print usage text without error, and the `edit --help` output includes `--port` and (most likely) a `--headless` flag. **Write down the exact flag names you see** — Task 9 assumes `--port` and `--headless`; if this installed version differs, adjust Task 9's `default_spawner` accordingly when you get there.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
Add marimo/anywidget/wigglystuff as an optional notebooks extra

Kept out of core dependencies so the production backend/PocketBase
deployment doesn't need to pull in notebook tooling.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Validate marimo's reusable-cell import mechanism against this repo's loader pattern

**Files:**
- Create: `quality/tests/fixtures/__init__.py`
- Create: `quality/tests/fixtures/marimo_reuse_fixture.py`
- Test: `quality/tests/test_marimo_notebook_reuse.py`

This is the load-bearing technical assumption behind the whole migration: a marimo notebook file can expose a plain top-level class (via `@app.class_definition`) that a normal `importlib.import_module` + `inspect.getmembers` call — exactly what `BotLoader._extract_bot_class` does — can find, while a *different*, non-reusable cell in the same file never executes on import. Validate it now, before Tasks 7–8 build bot notebooks on top of it.

- [ ] **Step 1: Create the fixtures package**

Create `quality/tests/fixtures/__init__.py` (empty file).

- [ ] **Step 2: Write the marimo notebook fixture**

Create `quality/tests/fixtures/marimo_reuse_fixture.py`:

```python
import marimo

__generated_with = "0.9.14"
app = marimo.App()

with app.setup:
    REUSABLE_PROBE_VALUE = 42


@app.class_definition
class ReusableProbe:
    """A pure class meant to be imported like a normal module attribute."""

    def __init__(self) -> None:
        self.value = REUSABLE_PROBE_VALUE


@app.cell
def _():
    # A regular, non-reusable cell. If marimo ever executed this on a plain
    # Python import, this test would fail loudly instead of silently passing.
    raise RuntimeError("This debug cell must never run on import.")
    return


if __name__ == "__main__":
    app.run()
```

**Before trusting this file:** run `uv run --extra notebooks python -c "import marimo; app = marimo.App(); print(hasattr(app, 'setup')); print(hasattr(app, 'class_definition'))"`. Both should print `True`. If either prints `False`, run `uv run --extra notebooks python -c "import marimo; help(marimo.App)"` to find the correct attribute/decorator names for the installed version and rewrite the fixture using those names before continuing.

- [ ] **Step 3: Write the test**

Create `quality/tests/test_marimo_notebook_reuse.py`:

```python
from __future__ import annotations

import importlib
import unittest


class MarimoNotebookReuseTests(unittest.TestCase):
    def test_reusable_class_is_importable_without_running_other_cells(self) -> None:
        module = importlib.import_module("quality.tests.fixtures.marimo_reuse_fixture")

        probe_class = getattr(module, "ReusableProbe", None)
        self.assertIsNotNone(probe_class, "ReusableProbe was not exposed as a top-level module attribute.")

        probe = probe_class()
        self.assertEqual(probe.value, 42)

    def test_reusable_class_module_matches_the_notebook_module(self) -> None:
        # This is exactly the check BotLoader._extract_bot_class performs:
        # obj.__module__ == module.__name__
        module = importlib.import_module("quality.tests.fixtures.marimo_reuse_fixture")
        probe_class = module.ReusableProbe

        self.assertEqual(probe_class.__module__, module.__name__)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the test**

Run: `uv run --extra notebooks python -m unittest quality.tests.test_marimo_notebook_reuse -v`
Expected: PASS (2 tests). If `test_reusable_class_is_importable_without_running_other_cells` fails with the `RuntimeError` from the debug cell, marimo's import behavior differs from what's documented — stop and re-read `https://docs.marimo.io/guides/reusing_functions/` before proceeding to Task 7.

- [ ] **Step 5: Commit**

```bash
git add quality/tests/fixtures/__init__.py \
        quality/tests/fixtures/marimo_reuse_fixture.py \
        quality/tests/test_marimo_notebook_reuse.py
git commit -m "$(cat <<'EOF'
Validate marimo's reusable-cell import mechanism

Confirms a marimo notebook's @app.class_definition cell is importable
via plain importlib the same way BotLoader imports bot modules, while
a regular cell in the same file never executes on import. This is the
assumption the bot-notebook conversion in later tasks depends on.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Harness — in-memory turn logger

**Files:**
- Create: `applications/__init__.py`
- Create: `applications/notebook_harness/__init__.py`
- Create: `applications/notebook_harness/in_memory_logger.py`
- Test: `quality/tests/test_notebook_harness_in_memory_logger.py`

`Game.next_turn()` calls `self.logger.record_turn(round_number, context)` every turn. The production `GameLogger` posts that to PocketBase over HTTP. For notebook test games, we want the same call shape but recorded in memory — no backend dependency.

- [ ] **Step 1: Create the package scaffolding**

Create `applications/__init__.py` (empty file — makes `applications` a regular package so `applications.notebook_harness` imports cleanly).

Create `applications/notebook_harness/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test**

Create `quality/tests/test_notebook_harness_in_memory_logger.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.runtime.cli import BootstrapRandomBot

from applications.notebook_harness.in_memory_logger import InMemoryGameLogger


class InMemoryGameLoggerTests(unittest.TestCase):
    def test_record_turn_appends_a_snapshot_with_the_serialized_turn_state(self) -> None:
        players = [
            Player("bot_0", BootstrapRandomBot(), "random_1", "red"),
            Player("bot_1", BootstrapRandomBot(), "random_2", "blue"),
        ]
        logger = InMemoryGameLogger(players)
        context = GameContext([player.player_id for player in players])

        # Build a real PlayerContext the same way Game.next_turn() does.
        from ticket_to_ride.engine.state.player_context import PlayerContext

        players[0].set_context(PlayerContext(players[0].player_id, context, players), True)
        players[1].set_context(PlayerContext(players[1].player_id, context, players), True)

        snapshot = logger.record_turn(0, players[0].context)

        self.assertEqual(len(logger.snapshots), 1)
        self.assertEqual(snapshot["roundNumber"], 0)
        self.assertEqual(snapshot["turnIndex"], 0)
        self.assertEqual(snapshot["turnState"]["player"]["playerId"], "bot_0")
        self.assertEqual(len(snapshot["turnState"]["opponents"]), 1)
        self.assertEqual(snapshot["turnState"]["opponents"][0]["playerId"], "bot_1")

    def test_record_turn_increments_turn_index_across_calls(self) -> None:
        players = [
            Player("bot_0", BootstrapRandomBot(), "random_1", "red"),
            Player("bot_1", BootstrapRandomBot(), "random_2", "blue"),
        ]
        logger = InMemoryGameLogger(players)
        context = GameContext([player.player_id for player in players])

        from ticket_to_ride.engine.state.player_context import PlayerContext

        players[0].set_context(PlayerContext(players[0].player_id, context, players), True)

        logger.record_turn(0, players[0].context)
        second_snapshot = logger.record_turn(0, players[0].context)

        self.assertEqual(second_snapshot["turnIndex"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_in_memory_logger -v`
Expected: FAIL/ERROR — `applications.notebook_harness.in_memory_logger` doesn't exist yet.

- [ ] **Step 4: Implement `InMemoryGameLogger`**

Create `applications/notebook_harness/in_memory_logger.py`:

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.player_context import PlayerContext
from ticket_to_ride.logging.game_logger import GameLogSerializer


class InMemoryGameLogger:
    """Records turn snapshots in memory instead of posting them to PocketBase.

    Satisfies the same `record_turn(round_number, context)` call that
    `Game.next_turn()` already makes on its logger, so it's a drop-in
    replacement for `GameLogger` with no engine changes required.
    """

    def __init__(self, players: List[Player], serializer: Optional[GameLogSerializer] = None) -> None:
        self.player_list = players
        self.serializer = serializer or GameLogSerializer()
        self.snapshots: List[Dict[str, Any]] = []

    def set_player_list(self, players: List[Player]) -> None:
        self.player_list = players

    def record_turn(self, round_number: int, context: PlayerContext) -> Dict[str, Any]:
        snapshot = {
            "roundNumber": round_number,
            "turnIndex": len(self.snapshots),
            "turnState": self.serializer.serialize_turn_state(self.player_list, context),
        }
        self.snapshots.append(snapshot)
        return snapshot
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_in_memory_logger -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add applications/__init__.py \
        applications/notebook_harness/__init__.py \
        applications/notebook_harness/in_memory_logger.py \
        quality/tests/test_notebook_harness_in_memory_logger.py
git commit -m "$(cat <<'EOF'
Add InMemoryGameLogger for offline notebook test games

Reuses GameLogSerializer's turn-state shape but appends to a plain
list instead of POSTing to PocketBase, so a bot notebook can run a
full test game without the backend or PocketBase running.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Harness — board rendering (node/edge builders)

**Files:**
- Create: `applications/notebook_harness/rendering.py`
- Test: `quality/tests/test_notebook_harness_rendering.py`

`GameLogSerializer.serialize_turn_state` already records, per turn, the active player's `claimedRoutes` *and* every opponent's `claimedRoutes` — together that's every claimed route on the board at that point in the game. This task builds pure functions that turn a `MapGraph` plus one recorded snapshot into GraphWidget-shaped `nodes`/`edges` lists (per the verified schema: node `{id, name, size, color, data}`, edge `{id, source, target, name, width, color, data}`).

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_notebook_harness_rendering.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.engine.state.map import MapGraph

from applications.notebook_harness.rendering import (
    build_edges,
    build_nodes,
    claimed_by_from_snapshot,
)


def make_turn_state(player_id, player_claimed, opponents):
    return {
        "player": {
            "playerId": player_id,
            "claimedRoutes": [{"routeId": route_id, "routeLabel": route_id} for route_id in player_claimed],
        },
        "opponents": [
            {
                "playerId": opponent_id,
                "claimedRoutes": [{"routeId": route_id, "routeLabel": route_id} for route_id in claimed],
            }
            for opponent_id, claimed in opponents
        ],
    }


class RenderingTests(unittest.TestCase):
    def test_build_nodes_returns_one_node_per_city(self) -> None:
        game_map = MapGraph(player_count=2)

        nodes = build_nodes(game_map)

        node_ids = {node["id"] for node in nodes}
        self.assertEqual(node_ids, game_map.cities())
        self.assertTrue(all(node["name"] == node["id"] for node in nodes))

    def test_claimed_by_from_snapshot_merges_player_and_opponent_claims(self) -> None:
        turn_state = make_turn_state(
            "bot_0",
            ["Seattle-Portland-1"],
            [("bot_1", ["Boston-Montreal-1"])],
        )

        claimed_by = claimed_by_from_snapshot(turn_state)

        self.assertEqual(
            claimed_by,
            {"Seattle-Portland-1": "bot_0", "Boston-Montreal-1": "bot_1"},
        )

    def test_build_edges_colors_claimed_routes_with_the_owning_players_color_and_others_by_route_color(self) -> None:
        game_map = MapGraph(player_count=2)
        claimed_route = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-1")
        unclaimed_route = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-2")

        edges = build_edges(
            game_map,
            claimed_by={"Seattle-Portland-1": "bot_0"},
            player_colors={"bot_0": "red"},
        )

        edges_by_id = {edge["id"]: edge for edge in edges}
        claimed_edge = edges_by_id["Seattle-Portland-1"]
        unclaimed_edge = edges_by_id["Seattle-Portland-2"]

        self.assertEqual(claimed_edge["source"], claimed_route.city1)
        self.assertEqual(claimed_edge["target"], claimed_route.city2)
        self.assertEqual(claimed_edge["width"], claimed_route.length)
        self.assertEqual(claimed_edge["color"], "red")
        self.assertEqual(claimed_edge["data"]["claimedBy"], "bot_0")

        self.assertNotEqual(unclaimed_edge["color"], "red")
        self.assertIsNone(unclaimed_edge["data"]["claimedBy"])
        self.assertEqual(unclaimed_edge["width"], unclaimed_route.length)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_rendering -v`
Expected: FAIL/ERROR — `applications.notebook_harness.rendering` doesn't exist yet.

- [ ] **Step 3: Implement the rendering module**

Create `applications/notebook_harness/rendering.py`:

```python
from __future__ import annotations

from typing import Any, Dict, List

from ticket_to_ride.engine.state.map import MapGraph, Route

# Route.color letter codes -> a readable CSS color for unclaimed edges.
_ROUTE_COLOR_HEX: Dict[str, str] = {
    "R": "#d62728",
    "B": "#1f1f1f",
    "U": "#1f77b4",
    "G": "#2ca02c",
    "O": "#ff7f0e",
    "P": "#9467bd",
    "W": "#dddddd",
    "Y": "#f1c40f",
    "X": "#999999",
}


def build_nodes(map_graph: MapGraph) -> List[Dict[str, Any]]:
    """Build GraphWidget node dicts, one per city on the map."""
    return [{"id": city, "name": city} for city in sorted(map_graph.cities())]


def claimed_by_from_snapshot(turn_state: Dict[str, Any]) -> Dict[str, str]:
    """Map route_id -> owning player_id for every route claimed as of this snapshot.

    `turn_state` is one entry's `["turnState"]` from InMemoryGameLogger.snapshots.
    The active player's own claimedRoutes plus every opponent's claimedRoutes
    together cover every player, so this is the complete board state at that turn.
    """
    claimed_by: Dict[str, str] = {}

    player_entry = turn_state["player"]
    for claimed_route in player_entry["claimedRoutes"]:
        claimed_by[claimed_route["routeId"]] = player_entry["playerId"]

    for opponent in turn_state["opponents"]:
        for claimed_route in opponent["claimedRoutes"]:
            claimed_by[claimed_route["routeId"]] = opponent["playerId"]

    return claimed_by


def _edge_color(route: Route, owner: 'str | None', player_colors: Dict[str, str]) -> str:
    if owner is not None:
        return player_colors.get(owner, _ROUTE_COLOR_HEX.get(route.color, "#999999"))
    return _ROUTE_COLOR_HEX.get(route.color, "#999999")


def build_edges(
    map_graph: MapGraph,
    claimed_by: Dict[str, str],
    player_colors: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Build GraphWidget edge dicts, one per route, colored by claim state.

    The authoritative length/base-color/owner live in each edge's `data` dict,
    separate from the rendering `width`/`color` fields.
    """
    edges: List[Dict[str, Any]] = []
    for route in map_graph.routes:
        owner = claimed_by.get(route.route_id)
        edges.append(
            {
                "id": route.route_id,
                "source": route.city1,
                "target": route.city2,
                "width": route.length,
                "color": _edge_color(route, owner, player_colors),
                "data": {
                    "length": route.length,
                    "color": route.color,
                    "claimedBy": owner,
                },
            }
        )
    return edges
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_rendering -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add applications/notebook_harness/rendering.py \
        quality/tests/test_notebook_harness_rendering.py
git commit -m "$(cat <<'EOF'
Add pure node/edge builders for GraphWidget rendering

Turns a MapGraph plus one recorded turn snapshot into GraphWidget's
documented node/edge schema, keeping true route length/owner in each
edge's data dict separate from the rendering width/color.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Harness — game runner (`initialize_game`, `list_maps`, `HarnessGame`)

**Files:**
- Create: `applications/notebook_harness/game_runner.py`
- Test: `quality/tests/test_notebook_harness_game_runner.py`

This ties Tasks 1, 4, and 5 together into the one entry point a bot notebook calls: hand it a list of bot instances, get back something you can `.play()` and then step through with `.board_at(step_index)`.

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_notebook_harness_game_runner.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.runtime.cli import BootstrapRandomBot

from applications.notebook_harness.game_runner import initialize_game, list_maps


class GameRunnerTests(unittest.TestCase):
    def test_list_maps_includes_the_classic_map(self) -> None:
        self.assertIn("classic", list_maps())

    def test_initialize_game_builds_one_player_per_bot(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])

        self.assertEqual(len(harness_game.players), 2)
        self.assertEqual(harness_game.players[0].player_id, "bot_0")
        self.assertEqual(harness_game.players[1].player_id, "bot_1")
        self.assertEqual(harness_game.players[0].color, "red")
        self.assertEqual(harness_game.players[1].color, "blue")

    def test_playing_a_game_records_snapshots_and_board_at_returns_nodes_and_edges(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])

        harness_game.play()

        self.assertGreater(harness_game.snapshot_count(), 0)

        nodes, edges = harness_game.board_at(0)
        self.assertTrue(len(nodes) > 0)
        self.assertTrue(len(edges) > 0)

        # Every claimed-by value in the first snapshot must be one of the two players.
        player_ids = {player.player_id for player in harness_game.players}
        for edge in edges:
            owner = edge["data"]["claimedBy"]
            if owner is not None:
                self.assertIn(owner, player_ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_game_runner -v`
Expected: FAIL/ERROR — `applications.notebook_harness.game_runner` doesn't exist yet.

- [ ] **Step 3: Implement `game_runner.py`**

Create `applications/notebook_harness/game_runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import DEFAULT_MAP_NAME, available_maps

from applications.notebook_harness.in_memory_logger import InMemoryGameLogger
from applications.notebook_harness.rendering import build_edges, build_nodes, claimed_by_from_snapshot

_SEAT_COLORS = ["red", "blue", "green", "yellow", "black"]


def list_maps() -> List[str]:
    """Return the names of every map a notebook can play on."""
    return available_maps()


@dataclass
class HarnessGame:
    game: Game
    players: List[Player]
    logger: InMemoryGameLogger

    def play(self) -> None:
        """Run the game to completion, recording one snapshot per turn."""
        self.game.play()

    def snapshot_count(self) -> int:
        return len(self.logger.snapshots)

    def board_at(self, step_index: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Return (nodes, edges) for the board as of the given recorded turn."""
        snapshot = self.logger.snapshots[step_index]
        map_graph = self.game.context.get_map()
        player_colors = {player.player_id: player.color for player in self.players}
        claimed_by = claimed_by_from_snapshot(snapshot["turnState"])

        return build_nodes(map_graph), build_edges(map_graph, claimed_by, player_colors)


def initialize_game(bots: List[Any], map_name: str = DEFAULT_MAP_NAME, round_number: int = 0) -> HarnessGame:
    """Build a HarnessGame seating one Player per bot instance, in order.

    `bots` are BaseBot instances (or anything implementing the same
    choose_*/select_* interface, like BootstrapRandomBot). The Nth bot
    becomes player "bot_N" with a distinct default color.
    """
    if not bots:
        raise ValueError("initialize_game requires at least one bot.")
    if len(bots) > len(_SEAT_COLORS):
        raise ValueError(f"initialize_game supports at most {len(_SEAT_COLORS)} seats.")

    player_ids = [f"bot_{index}" for index in range(len(bots))]
    players = [
        Player(
            player_ids[index],
            bots[index],
            getattr(bots[index], "name", None) or player_ids[index],
            _SEAT_COLORS[index],
        )
        for index in range(len(bots))
    ]

    context = GameContext(player_ids, map_name=map_name)
    logger = InMemoryGameLogger(players)
    game = Game(context, players, logger, round_number)

    return HarnessGame(game=game, players=players, logger=logger)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_game_runner -v`
Expected: PASS (3 tests). This actually plays a full 2-bot random-vs-random game in-process, so it may take a few seconds — that's expected.

- [ ] **Step 5: Run the full suite**

Run: `uv run test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add applications/notebook_harness/game_runner.py \
        quality/tests/test_notebook_harness_game_runner.py
git commit -m "$(cat <<'EOF'
Add notebook harness game runner

initialize_game(bots) is the one entry point a bot notebook needs:
seats bots as Players on a chosen map, wires an InMemoryGameLogger,
and HarnessGame.board_at(step_index) returns render-ready nodes/edges
for any recorded turn.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Convert `random_bot.py` to a canonical marimo notebook

**Files:**
- Modify (rewrite in marimo format): `integrations/external/bots/random_bot.py`

The file keeps its path and its `RandomBot` class body verbatim — only the marimo wrapper and a set of interactive cells for spectating/testing are added. `BotLoader` needs no changes.

- [ ] **Step 1: Rewrite `random_bot.py` in marimo notebook format**

Replace the full contents of `integrations/external/bots/random_bot.py` with:

```python
import marimo

__generated_with = "0.9.14"
app = marimo.App(width="medium")

with app.setup:
    import random
    from typing import List

    from external.contracts.base_bot import BaseBot
    from ticket_to_ride.engine.state.map import Route
    from ticket_to_ride.engine.state.decks import DestinationTicket

    BOT_META = {
        "schema_version": 1,
        "id": "random_bot",
        "name": "Random Bot",
        "version": "1.0.0",
        "description": "Baseline bot that selects randomly from legal options.",
        "author": "Lucas Starkey",
        "tags": ["baseline", "random"],
    }


@app.class_definition
class RandomBot(BaseBot):
    """Baseline bot that makes random choices.

    Helpful functions and attributes
    -------------------------------
    ``self.player`` is assigned by the game engine and exposes many helpers for
    making decisions. Some commonly used ones are listed below.

    ``self.player.get_affordable_routes()`` -> ``List[tuple[Route, int]]``
        Returns the routes you can currently afford and the locomotives required.

    ``self.player.get_tickets()`` -> ``List[DestinationTicket]``
        Your destination tickets. Each ticket has ``city1``, ``city2``,
        ``value`` and ``is_completed`` attributes.

    ``self.player.get_hand()`` -> ``Counter[str]``
        Current train cards in hand, keyed by color letter.

    ``self.player.trains_remaining``
        How many trains you still have available.

    ``self.player.context`` -> :class:`PlayerContext`
        Snapshot of public game state each turn.
    """

    META = BOT_META

    # used to determine weather to
    # 1 = Draw
    # 2 = Claim
    # 3 = draw a destination ticket
    def choose_turn_action(self):
        """Decide which action to take this turn."""
        affordable_routes = self.player.get_affordable_routes() if self.player else None
        if not len([t for t in self.player.get_tickets() if not t.is_completed]):
            return 3
        elif affordable_routes:
            return 2
        else:
            return 1

    # choose what cards to draw
    def choose_draw_train_action(self) -> int:
        """Choose which face-up index to draw or ``-1`` for the deck."""
        return random.randrange(-1, 5)

    # choose what routes to claim
    def choose_route_to_claim(self, claimable_routes: 'List[tuple[Route,int]]') -> 'tuple[Route,int]':
        """Select a route and number of locomotives to spend."""
        return claimable_routes[random.randrange(0, len(claimable_routes))]

    # choose what color to spend on a gray route
    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        """Pick a color to spend on gray routes."""
        return None

    # choose which destination tickets to keep
    def select_ticket_offer(self, offer) -> List[DestinationTicket]:
        """Choose which destination tickets to keep."""
        return [offer[0], offer[1]]

    def path_finder(self, city1, city2):
        """Placeholder for path-finding logic."""
        return None


@app.cell
def _():
    import marimo as mo

    from applications.notebook_harness.game_runner import initialize_game, list_maps

    mo.md("# Random Bot — spectate & debug").left()
    return initialize_game, list_maps, mo


@app.cell
def _(list_maps, mo):
    map_picker = mo.ui.dropdown(options=list_maps(), value=list_maps()[0], label="Map")
    map_picker
    return (map_picker,)


@app.cell
def _(initialize_game, map_picker):
    # Runs the freshly-edited RandomBot against a second copy of itself.
    harness_game = initialize_game([RandomBot(), RandomBot()], map_name=map_picker.value)
    harness_game.play()
    return (harness_game,)


@app.cell
def _(harness_game, mo):
    from wigglystuff import PlaySlider

    step_slider = mo.ui.anywidget(
        PlaySlider(min_value=0, max_value=harness_game.snapshot_count() - 1, step=1, interval_ms=300)
    )
    step_slider
    return (step_slider,)


@app.cell
def _(harness_game, mo, step_slider):
    from wigglystuff import GraphWidget

    nodes, edges = harness_game.board_at(int(step_slider.value or 0))
    graph = mo.ui.anywidget(GraphWidget(nodes=nodes, edges=edges))
    graph
    return


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 2: Verify `BotLoader` still discovers the bot correctly**

Run:
```bash
uv run python -c "
from external.clients.bot_api.loader import BotLoader
loader = BotLoader()
descriptors = loader.load_bots()
print(descriptors['random_bot'].bot_class.__name__)
print(descriptors['random_bot'].metadata.name)
"
```
Expected output:
```
RandomBot
Random Bot
```
If this raises `BotLoaderError`, re-check that the `RandomBot` cell contains *only* the class definition (per marimo's "single function or class per reusable cell" rule) and that `BOT_META`/imports live in the `app.setup` block.

- [ ] **Step 3: Run the full native test suite (does not require `--extra notebooks`)**

Run: `uv run test`
Expected: all tests pass, including anything that already exercised `random_bot` (e.g. `test_random_bot_match_performance.py`, which uses `BootstrapRandomBot` directly and is unaffected, but confirm nothing else imports `random_bot.py` in a way that breaks).

- [ ] **Step 4: Manually verify the interactive half in `marimo edit`**

Run: `uv run --extra notebooks marimo edit integrations/external/bots/random_bot.py`
Expected: the notebook opens in a browser tab, runs a full random-vs-random game, and shows a graph with a working play slider that recolors edges as you drag it. Stop the server (Ctrl+C) when done.

- [ ] **Step 5: Commit**

```bash
git add integrations/external/bots/random_bot.py
git commit -m "$(cat <<'EOF'
Convert random_bot.py into a canonical marimo notebook

RandomBot's class body is unchanged and still discoverable by
BotLoader via plain importlib. New interactive cells below it use the
notebook harness to run and spectate a test game while editing.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Convert `example_bot.py` to a canonical marimo notebook

**Files:**
- Modify (rewrite in marimo format): `integrations/external/bots/example_bot.py`

- [ ] **Step 1: Read the current file**

Run: `cat integrations/external/bots/example_bot.py` and note its `BOT_META`, class name, and method bodies — port them into the marimo structure exactly as Task 7 did for `random_bot.py`, following the same three-part shape:
1. `with app.setup:` block — imports plus `BOT_META`
2. `@app.class_definition` cell — the bot class, methods unchanged
3. Regular (non-reusable) cells below — `mo.md` header, map picker, `initialize_game([ExampleBotClassName(), ExampleBotClassName()])`, `PlaySlider`, `GraphWidget`, matching Task 7's cells verbatim except for the class name and any bot-specific header text.

- [ ] **Step 2: Verify `BotLoader` still discovers the bot correctly**

Run:
```bash
uv run python -c "
from external.clients.bot_api.loader import BotLoader
loader = BotLoader()
descriptors = loader.load_bots()
for bot_id, descriptor in descriptors.items():
    print(bot_id, descriptor.bot_class.__name__)
"
```
Expected: both `random_bot` and `example_bot` (or whatever its `BOT_META['id']` is) print with their correct class names, and the call doesn't raise `BotLoaderError` about duplicate module paths or missing `BaseBot` subclasses.

- [ ] **Step 3: Run the full native test suite**

Run: `uv run test`
Expected: all tests pass.

- [ ] **Step 4: Manually verify in `marimo edit`**

Run: `uv run --extra notebooks marimo edit integrations/external/bots/example_bot.py`
Expected: same as Task 7 Step 4 — notebook opens, game runs, slider/graph work. Stop the server when done.

- [ ] **Step 5: Commit**

```bash
git add integrations/external/bots/example_bot.py
git commit -m "$(cat <<'EOF'
Convert example_bot.py into a canonical marimo notebook

Same conversion pattern as random_bot.py: class body unchanged and
still discoverable by BotLoader, new interactive cells for spectating.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Notebook launcher process manager (backend)

**Files:**
- Create: `services/native-runtime/src/ticket_to_ride/backend/notebook_launcher.py`
- Test: `quality/tests/test_notebook_launcher.py`

A small, pure-Python, subprocess-spawning-behind-an-interface class: given a bot id and notebook path, spin up (or reuse) a `marimo edit` server and return its URL. Kept fully unit-testable via dependency-injected spawner/port-allocator, no real subprocess in tests.

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_notebook_launcher.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.backend.notebook_launcher import NotebookLauncher


class FakeProcess:
    def __init__(self) -> None:
        self.exit_code: 'int | None' = None

    def poll(self) -> 'int | None':
        return self.exit_code


class NotebookLauncherTests(unittest.TestCase):
    def test_launch_spawns_a_process_and_returns_its_url(self) -> None:
        spawn_calls = []

        def fake_spawner(notebook_path: str, port: int) -> FakeProcess:
            spawn_calls.append((notebook_path, port))
            return FakeProcess()

        launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: 12345)

        url = launcher.launch("random_bot", "/repo/integrations/external/bots/random_bot.py")

        self.assertEqual(url, "http://127.0.0.1:12345")
        self.assertEqual(spawn_calls, [("/repo/integrations/external/bots/random_bot.py", 12345)])

    def test_launch_reuses_a_still_running_session_for_the_same_bot(self) -> None:
        spawn_calls = []
        ports = iter([12345, 54321])

        def fake_spawner(notebook_path: str, port: int) -> FakeProcess:
            spawn_calls.append((notebook_path, port))
            return FakeProcess()

        launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: next(ports))

        first_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")
        second_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(spawn_calls), 1)

    def test_launch_spawns_a_new_session_when_the_previous_process_exited(self) -> None:
        processes = [FakeProcess(), FakeProcess()]
        ports = iter([12345, 54321])

        def fake_spawner(notebook_path: str, port: int) -> FakeProcess:
            return processes.pop(0)

        launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: next(ports))

        first_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")
        launcher._sessions["random_bot"].process.exit_code = 0  # simulate the marimo server having exited
        second_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")

        self.assertNotEqual(first_url, second_url)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_notebook_launcher -v`
Expected: FAIL/ERROR — `ticket_to_ride.backend.notebook_launcher` doesn't exist yet.

- [ ] **Step 3: Implement `NotebookLauncher`**

Create `services/native-runtime/src/ticket_to_ride/backend/notebook_launcher.py`:

```python
from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol


class ProcessSpawner(Protocol):
    def __call__(self, notebook_path: str, port: int) -> "subprocess.Popen[bytes]": ...


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def default_spawner(notebook_path: str, port: int) -> "subprocess.Popen[bytes]":
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "marimo",
            "edit",
            notebook_path,
            "--port",
            str(port),
            "--headless",
        ],
        cwd=str(_repo_root()),
    )


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class NotebookSession:
    bot_id: str
    port: int
    process: "subprocess.Popen[bytes]"

    def is_running(self) -> bool:
        return self.process.poll() is None


class NotebookLauncher:
    """Spawns (or reuses) one `marimo edit` server per bot notebook."""

    def __init__(
        self,
        spawner: Optional[ProcessSpawner] = None,
        port_allocator: Optional[Callable[[], int]] = None,
        host: str = "127.0.0.1",
    ) -> None:
        self._spawner = spawner or default_spawner
        self._port_allocator = port_allocator or _find_free_port
        self._host = host
        self._sessions: Dict[str, NotebookSession] = {}

    def launch(self, bot_id: str, notebook_path: str) -> str:
        existing = self._sessions.get(bot_id)
        if existing is not None and existing.is_running():
            return self._url_for(existing.port)

        port = self._port_allocator()
        process = self._spawner(notebook_path, port)
        self._sessions[bot_id] = NotebookSession(bot_id=bot_id, port=port, process=process)
        return self._url_for(port)

    def _url_for(self, port: int) -> str:
        return f"http://{self._host}:{port}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run python -m unittest quality.tests.test_notebook_launcher -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/backend/notebook_launcher.py \
        quality/tests/test_notebook_launcher.py
git commit -m "$(cat <<'EOF'
Add NotebookLauncher process manager

Spawns a marimo edit server per bot notebook and reuses it while
still running. Spawner/port-allocator are injectable so this is fully
unit-tested without spawning real subprocesses.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Expose each bot's notebook path through the bot-api discovery endpoint

**Files:**
- Modify: `integrations/external/clients/bot_api/models.py`
- Modify: `integrations/external/clients/bot_api/service.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/bot_catalog.py`
- Test: `quality/tests/test_bot_api_module_path.py`
- Test: `quality/tests/test_bot_catalog_module_path.py`

The native backend must never import `integrations/external/` Python code directly (see `docs/repository-layout.md`). `BotLoader` already knows each bot's file path (`BotDescriptor.module_path`) but the bot-api's `GET /bots` response doesn't expose it. This task threads it through the existing HTTP boundary instead of reaching across it.

- [ ] **Step 1: Write the failing bot-api test**

Create `quality/tests/test_bot_api_module_path.py`:

```python
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from external.clients.bot_api.app import create_app


class BotApiModulePathTests(unittest.TestCase):
    def test_get_bots_includes_a_module_path_for_each_bot(self) -> None:
        client = TestClient(create_app())

        response = client.get("/bots")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(len(payload) > 0)
        for bot in payload:
            self.assertIn("modulePath", bot)
            self.assertTrue(bot["modulePath"].endswith(f"{bot['botId']}.py"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_bot_api_module_path -v`
Expected: FAIL — `modulePath` missing from the response.

- [ ] **Step 3: Add `modulePath` to `BotMetadata` and populate it in `list_bots`**

In `integrations/external/clients/bot_api/models.py`, add the field to `BotMetadata`:

```python
class BotMetadata(BaseModel):
    schemaVersion: Literal[1]
    botId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    author: str = ""
    tags: List[str] = Field(default_factory=list)
    modulePath: str = ""

    @classmethod
    def from_module_meta(cls, meta: Dict[str, Any]) -> "BotMetadata":
        if not isinstance(meta, dict):
            raise ValueError("BOT_META must be a dictionary.")

        try:
            return cls.model_validate(
                {
                    "schemaVersion": meta.get("schema_version"),
                    "botId": meta.get("id"),
                    "name": meta.get("name"),
                    "version": meta.get("version"),
                    "description": meta.get("description"),
                    "author": meta.get("author") or "",
                    "tags": meta.get("tags") or [],
                }
            )
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field_path = ".".join(str(part) for part in first_error.get("loc", ()))
            raise ValueError(f"Invalid BOT_META field '{field_path}': {first_error.get('msg', 'invalid value')}.") from exc
```

In `integrations/external/clients/bot_api/service.py`, change `BotSessionManager.list_bots` to attach each descriptor's module path:

```python
    def list_bots(self) -> List[BotMetadata]:
        metadata_with_paths = [
            descriptor.metadata.model_copy(update={"modulePath": descriptor.module_path})
            for descriptor in self.descriptors.values()
        ]
        return BotLoader.sort_metadata(metadata_with_paths)
```

- [ ] **Step 4: Run the bot-api test again**

Run: `uv run python -m unittest quality.tests.test_bot_api_module_path -v`
Expected: PASS

- [ ] **Step 5: Write the failing native-side catalog test**

Create `quality/tests/test_bot_catalog_module_path.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import patch

from ticket_to_ride.backend.bot_catalog import LocalApiBotCatalogClient


class BotCatalogModulePathTests(unittest.TestCase):
    def test_list_bots_carries_module_path_through_to_the_catalog_record(self) -> None:
        payload = [
            {
                "schemaVersion": 1,
                "botId": "random_bot",
                "name": "Random Bot",
                "version": "1.0.0",
                "description": "desc",
                "author": "a",
                "tags": [],
                "modulePath": "/repo/integrations/external/bots/random_bot.py",
            }
        ]

        client = LocalApiBotCatalogClient(base_url="http://127.0.0.1:8001")

        with patch.object(LocalApiBotCatalogClient, "_request_json", return_value=payload):
            records = client.list_bots()

        self.assertEqual(records[0].module_path, "/repo/integrations/external/bots/random_bot.py")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_bot_catalog_module_path -v`
Expected: FAIL — `BotCatalogRecord` has no `module_path` field yet, and `_parse_bot_record` doesn't read it.

- [ ] **Step 7: Thread `module_path` through `BotCatalogRecord`**

In `services/native-runtime/src/ticket_to_ride/backend/bot_catalog.py`, add the field to the dataclass:

```python
@dataclass(frozen=True)
class BotCatalogRecord:
    schema_version: int
    bot_id: str
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    source_kind: str
    source_base_url: str
    discovery_path: str
    module_path: str
```

And in `_parse_bot_record`, read it from the payload and pass it through:

```python
    def _parse_bot_record(self, payload: Any) -> BotCatalogRecord:
        if not isinstance(payload, dict):
            raise BotCatalogError("Bot catalog entries must be JSON objects.")

        schema_version = payload.get("schemaVersion")
        bot_id = payload.get("botId")
        name = payload.get("name")
        version = payload.get("version")
        description = payload.get("description")
        author = payload.get("author") or ""
        tags = payload.get("tags") or []
        module_path = payload.get("modulePath") or ""

        if schema_version != 1:
            raise BotCatalogError("Bot catalog entries must declare schemaVersion 1.")
        if not isinstance(bot_id, str) or not bot_id.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty botId.")
        if not isinstance(name, str) or not name.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty name.")
        if not isinstance(version, str) or not version.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty version.")
        if not isinstance(description, str) or not description.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty description.")
        if not isinstance(author, str):
            raise BotCatalogError("Bot catalog entry author must be a string.")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise BotCatalogError("Bot catalog entry tags must be a list of strings.")

        return BotCatalogRecord(
            schema_version=1,
            bot_id=bot_id.strip(),
            name=name.strip(),
            version=version.strip(),
            description=description.strip(),
            author=author.strip(),
            tags=[tag.strip() for tag in tags if tag.strip()],
            source_kind=LOCAL_API_SOURCE_KIND,
            source_base_url=self.base_url,
            discovery_path=self.discovery_path,
            module_path=str(module_path).strip(),
        )
```

- [ ] **Step 8: Run both new tests and the full suite**

Run: `uv run python -m unittest quality.tests.test_bot_catalog_module_path -v`
Expected: PASS

Run: `uv run test`
Expected: all tests pass — check specifically that nothing else constructs a `BotCatalogRecord` positionally without the new field (search: `grep -rn "BotCatalogRecord(" quality/ services/`); if any call site does, add `module_path=` there too.

- [ ] **Step 9: Commit**

```bash
git add integrations/external/clients/bot_api/models.py \
        integrations/external/clients/bot_api/service.py \
        services/native-runtime/src/ticket_to_ride/backend/bot_catalog.py \
        quality/tests/test_bot_api_module_path.py \
        quality/tests/test_bot_catalog_module_path.py
git commit -m "$(cat <<'EOF'
Expose each bot's notebook path through the bot-api discovery endpoint

The native backend needs a bot's file path to launch its notebook but
must never import integrations/external directly. modulePath now
flows through the existing HTTP discovery boundary instead.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `POST /notebooks/{bot_id}/launch` endpoint

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/models.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/service.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/app.py`
- Test: `quality/tests/test_notebook_launch_api.py`

- [ ] **Step 1: Write the failing API test**

Create `quality/tests/test_notebook_launch_api.py`:

```python
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.bot_catalog import BotCatalogRecord
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def build_catalog_record(bot_id: str, module_path: str) -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name="Random Bot",
        version="1.0.0",
        description="desc",
        author="a",
        tags=[],
        source_kind="local_api",
        source_base_url="http://127.0.0.1:8001",
        discovery_path="/bots",
        module_path=module_path,
    )


class StaticCatalogClient:
    def __init__(self, records: list[BotCatalogRecord]) -> None:
        self.records = records

    def list_bots(self) -> list[BotCatalogRecord]:
        return list(self.records)

    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        for record in self.records:
            if record.bot_id == bot_id:
                return record
        raise KeyError(bot_id)


class NotebookLaunchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()
        self.spawn_calls = []

        def fake_spawner(notebook_path: str, port: int):
            self.spawn_calls.append((notebook_path, port))

            class FakeProcess:
                def poll(self_inner):
                    return None

            return FakeProcess()

        self.notebook_launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: 12345)

    def test_launch_returns_a_url_for_a_known_bot(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient(
                    [build_catalog_record("random_bot", "/repo/integrations/external/bots/random_bot.py")]
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        response = client.post("/notebooks/random_bot/launch")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"botId": "random_bot", "url": "http://127.0.0.1:12345"})
        self.assertEqual(self.spawn_calls, [("/repo/integrations/external/bots/random_bot.py", 12345)])

    def test_launch_returns_not_found_for_an_unknown_bot(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient([]),
                notebook_launcher=self.notebook_launcher,
            )
        )

        response = client.post("/notebooks/unknown_bot/launch")

        self.assertEqual(response.status_code, 404)

    def test_launching_the_same_bot_twice_reuses_the_session(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient(
                    [build_catalog_record("random_bot", "/repo/integrations/external/bots/random_bot.py")]
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        first_response = client.post("/notebooks/random_bot/launch")
        second_response = client.post("/notebooks/random_bot/launch")

        self.assertEqual(first_response.json(), second_response.json())
        self.assertEqual(len(self.spawn_calls), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_notebook_launch_api -v`
Expected: FAIL — `create_app` doesn't accept `notebook_launcher` yet, and the endpoint doesn't exist.

- [ ] **Step 3: Add the response model**

In `services/native-runtime/src/ticket_to_ride/backend/models.py`, add:

```python
class NotebookLaunchResponse(BaseModel):
    botId: str
    url: str
```

- [ ] **Step 4: Add the service function**

In `services/native-runtime/src/ticket_to_ride/backend/service.py`, add (near `register_bot`):

```python
def launch_notebook(
    catalog_client: BotCatalogClient,
    notebook_launcher: "NotebookLauncher",
    bot_id: str,
) -> NotebookLaunchResponse:
    requested_bot_id = bot_id.strip()
    if not requested_bot_id:
        raise ValueError("Bot ID is required.")

    try:
        catalog_record = catalog_client.resolve_bot(requested_bot_id)
    except KeyError as exc:
        raise BotNotFoundError(f"Unknown bot '{requested_bot_id}'.") from exc

    url = notebook_launcher.launch(catalog_record.bot_id, catalog_record.module_path)
    return NotebookLaunchResponse(botId=catalog_record.bot_id, url=url)
```

Add the corresponding imports at the top of `service.py`: `from ticket_to_ride.backend.models import ..., NotebookLaunchResponse` (extend the existing `from ticket_to_ride.backend.models import (...)` block) and `from ticket_to_ride.backend.notebook_launcher import NotebookLauncher` guarded under `TYPE_CHECKING` if `service.py` doesn't already import concrete backend classes — check the existing import style in the file and match it (it already imports `BotCatalogClient` directly at module scope, so import `NotebookLauncher` the same way, not under `TYPE_CHECKING`).

- [ ] **Step 5: Wire the endpoint into `app.py`**

In `services/native-runtime/src/ticket_to_ride/backend/app.py`:

Add `NotebookLauncher` to imports and add a constructor parameter, `app.state` entry, dependency getter, and the endpoint itself:

```python
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
```

```python
def create_app(
    repository: Optional[MatchRepository] = None,
    bot_catalog_client: Optional[BotCatalogClient] = None,
    runtime_manager: Optional[ManagedMatchRuntimeManager] = None,
    notebook_launcher: Optional[NotebookLauncher] = None,
) -> FastAPI:
    app = FastAPI(title="Ticket to Ride Match Logger", version="1.0.0")
    app.state.match_repository = repository or build_repository_from_env()
    app.state.bot_catalog_client = bot_catalog_client or build_bot_catalog_client_from_env()
    app.state.runtime_manager = runtime_manager
    app.state.notebook_launcher = notebook_launcher or NotebookLauncher()
    # ... existing CORS/middleware/exception-handler code unchanged ...
```

Add the dependency getter next to `get_bot_catalog_client`:

```python
    def get_notebook_launcher() -> NotebookLauncher:
        return app.state.notebook_launcher
```

Add the endpoint next to the existing `/bots` endpoints:

```python
    @app.post("/notebooks/{bot_id}/launch", response_model=NotebookLaunchResponse)
    def post_launch_notebook(
        bot_id: str,
        bot_catalog_client: BotCatalogClient = Depends(get_bot_catalog_client),
        notebook_launcher: NotebookLauncher = Depends(get_notebook_launcher),
    ) -> NotebookLaunchResponse:
        try:
            return launch_notebook(bot_catalog_client, notebook_launcher, bot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Add `NotebookLaunchResponse` to the existing `from ticket_to_ride.backend.models import (...)` block, and `launch_notebook` to the existing `from ticket_to_ride.backend.service import (...)` block.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run python -m unittest quality.tests.test_notebook_launch_api -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run the full suite**

Run: `uv run test`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/backend/models.py \
        services/native-runtime/src/ticket_to_ride/backend/service.py \
        services/native-runtime/src/ticket_to_ride/backend/app.py \
        quality/tests/test_notebook_launch_api.py
git commit -m "$(cat <<'EOF'
Add POST /notebooks/{bot_id}/launch endpoint

Resolves a bot's notebook path through the existing bot catalog
client and hands it to NotebookLauncher, returning a reachable URL
for the frontend to open.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Frontend — "Open Notebook" button on the bots dashboard

**Files:**
- Modify: `applications/viewer/components/services/bot-registry.jsx`
- Modify: `applications/viewer/components/dashboard/BotsDashboard.jsx`

- [ ] **Step 1: Add the `launchNotebook` service function**

In `applications/viewer/components/services/bot-registry.jsx`, add a new function and export it:

```javascript
async function launchNotebook(apiBase, botId) {
  const response = await fetch(`${apiBase}/notebooks/${encodeURIComponent(botId)}/launch`, {
    method: "POST",
  });

  if (!response.ok) {
    return readResponseError(response, `Notebook launch failed with status ${response.status}`);
  }

  return response.json();
}

export {
  launchNotebook,
  listBots,
  registerBot,
};
```

(Replace the existing `export { listBots, registerBot };` block at the bottom of the file with the block above.)

- [ ] **Step 2: Add the button and click handler to `BotsDashboard.jsx`**

In `applications/viewer/components/dashboard/BotsDashboard.jsx`:

Update the import line to include `launchNotebook`:

```javascript
import { launchNotebook, listBots, registerBot } from "../services/bot-registry.jsx";
```

Add launch state and a handler inside the `BotsDashboard` function, right after the `handleRegisteredBot` function:

```javascript
  const [launchState, setLaunchState] = useState({});

  async function handleOpenNotebook(bot) {
    setLaunchState((current) => ({ ...current, [bot.botId]: "opening" }));
    try {
      const result = await launchNotebook(props.apiBase, bot.botId);
      window.open(result.url, "_blank", "noopener");
      setLaunchState((current) => ({ ...current, [bot.botId]: "idle" }));
    } catch (error) {
      setLaunchState((current) => ({ ...current, [bot.botId]: "error" }));
    }
  }
```

Add the button inside each bot card's `matches-modal-card-meta` block — replace the `filteredBots.map((bot) => ...)` block with:

```javascript
                  : filteredBots.map((bot) =>
                      h(
                        "article",
                        { key: bot.botId, className: "bots-card" },
                        h(
                          "div",
                          { className: "bots-card-top" },
                          h(
                            "div",
                            { className: "bots-card-copy" },
                            h("h3", null, bot.name),
                            h("p", { className: "bots-card-path" }, bot.sourceLabel)
                          ),
                          h("span", { className: "matches-modal-status" }, "Local API")
                        ),
                        h(
                          "div",
                          { className: "matches-modal-card-meta" },
                          h("span", { className: "matches-modal-meta-pill" }, bot.botId),
                          h("span", { className: "matches-modal-meta-pill" }, bot.version),
                          h("span", { className: "matches-modal-meta-pill" }, bot.sourceKind),
                          bot.createdLabel
                            ? h("span", { className: "matches-modal-meta-pill" }, `Registered ${bot.createdLabel}`)
                            : null
                        ),
                        h(
                          "div",
                          { className: "bots-card-actions" },
                          h(
                            "button",
                            {
                              className: "matches-modal-link",
                              type: "button",
                              disabled: launchState[bot.botId] === "opening",
                              onClick: () => handleOpenNotebook(bot),
                            },
                            launchState[bot.botId] === "opening" ? "Opening..." : "Open Notebook"
                          ),
                          launchState[bot.botId] === "error"
                            ? h("span", { className: "bots-add-error" }, "Unable to open the notebook.")
                            : null
                        )
                      )
                    )
```

No CSS is being introduced here beyond the existing `matches-modal-link`/`bots-add-error` classes already used elsewhere in this file, plus a `bots-card-actions` wrapper — add a minimal rule for it to `applications/viewer/components/viewer-shell.css`:

```css
.bots-card-actions {
  margin-top: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
```

- [ ] **Step 3: Manually verify in the browser**

Run (from repo root): `uv run run`
This starts PocketBase, the backend, and the viewer, and opens the viewer in a browser. Navigate to the Bots page, click "Open Notebook" on a registered bot, and confirm a new tab opens pointed at a `marimo edit` server for that bot's notebook. (Register a bot first via the existing "Add Bot" flow if none are registered yet — built-in test bot id is `random_bot`.)

- [ ] **Step 4: Commit**

```bash
git add applications/viewer/components/services/bot-registry.jsx \
        applications/viewer/components/dashboard/BotsDashboard.jsx \
        applications/viewer/components/viewer-shell.css
git commit -m "$(cat <<'EOF'
Add "Open Notebook" button to the bots dashboard

Clicking a registered bot now calls POST /notebooks/{botId}/launch
and opens the returned marimo edit URL in a new tab.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Update architecture docs

**Files:**
- Modify: `docs/repository-layout.md`
- Modify: `docs/architecture/system-overview.md`

- [ ] **Step 1: Add the harness to the repository layout doc**

In `docs/repository-layout.md`, extend the `applications/` bullet:

```markdown
- `applications/`: first-party UI surfaces. The current viewer lives in `applications/viewer/`. The notebook test harness used by bot notebooks lives in `applications/notebook_harness/` — a pure-Python package (no HTTP/PocketBase dependency) that bot notebooks under `integrations/external/bots/` import to run and render in-process test games.
```

- [ ] **Step 2: Add the harness and launcher to the system overview doc**

In `docs/architecture/system-overview.md`, add a new bullet under "Who Owns What", after the `applications/viewer` bullet:

```markdown
- `applications/notebook_harness`
  - pure-Python test harness for bot notebooks: builds in-process games, renders GraphWidget-ready board state from an in-memory turn log
  - no dependency on the backend, PocketBase, or HTTP — bot notebooks run fully offline
- `services/native-runtime/src/ticket_to_ride/backend/notebook_launcher.py`
  - spawns/reuses one `marimo edit` server per bot notebook, launched from the viewer's Bots page via `POST /notebooks/{bot_id}/launch`
```

Also add a line to the "Network Boundaries" section:

```markdown
- Frontend -> main backend API `/notebooks/{bot_id}/launch` -> local `marimo edit` subprocess: process spawn, not HTTP
```

- [ ] **Step 3: Commit**

```bash
git add docs/repository-layout.md docs/architecture/system-overview.md
git commit -m "$(cat <<'EOF'
Document the notebook harness and launcher in architecture docs

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: End-to-end manual verification

**Files:** none — this is a verification pass, not a code change.

- [ ] **Step 1: Run the full automated suite one more time**

Run: `uv run test`
Expected: all tests pass.

- [ ] **Step 2: Verify each bot notebook runs standalone, offline**

For each of `integrations/external/bots/random_bot.py` and `integrations/external/bots/example_bot.py`:

Run: `uv run --extra notebooks marimo edit <path>` with no backend or PocketBase running.
Expected: the notebook opens, a full game plays out, the map picker lists `classic`, the play slider steps through turns, and the graph recolors edges as claimed. No network errors in the browser console related to a missing backend.

- [ ] **Step 3: Verify the launcher end-to-end with the full stack running**

Run: `uv run run` (starts PocketBase, backend, and viewer).
In the browser: go to the Bots page, register `random_bot` if not already registered, click "Open Notebook", confirm a new tab opens with a working `marimo edit` session for `random_bot.py`. Click it again and confirm the second click reuses the same tab's server rather than spawning a duplicate (check the backend process list, e.g. `ps aux | grep marimo`, shows only one `marimo edit` process for `random_bot.py`).

- [ ] **Step 4: Confirm `BotLoader` and the sandboxed bot-api path are unaffected**

Run: `uv run python -c "
from external.clients.bot_api.service import BotSessionManager
manager = BotSessionManager()
print(manager.list_bots())
"`
Expected: prints metadata for both bots without error, confirming the real managed-match/bot-sandbox path (which this migration does not touch) still loads bots correctly from their now-marimo-formatted files.

- [ ] **Step 5: Report results**

No commit for this task. If every check above passes, the migration is done for this scope; if anything fails, capture the exact command and output before fixing it — don't mark this task's steps complete until each one has been actually run and observed to pass, per this project's verification-before-completion norm.

---

## Summary of What This Plan Does Not Cover

Per the design spec's phase boundary, these are explicitly out of scope and left for future specs:

- Full multi-user launcher (auth, concurrent sessions, remote hosting)
- Retiring `applications/viewer`'s replay-of-real-managed-matches feature
- Network-multiplayer bot execution
- Authoring additional maps beyond the migrated `classic` map
