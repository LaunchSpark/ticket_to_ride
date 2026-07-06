# Engine Action-Model Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the engine from the choose_*/fault-flag bot protocol to a state/action model — seeded RNG, data-only views, `act(view, legal_actions)` with a legacy adapter, and action logging with deterministic replay — in four independently shippable phases.

**Architecture:** Each phase lands on its own and keeps the full test suite green. Phase 1 threads one seeded `random.Random` through the decks. Phase 2 makes `PlayerView` pure data + pure queries and gives `Player` a private `GameContext` channel for mutations. Phase 3 introduces `Action` dataclasses, `legal_*` menu functions, and rewrites `Player.take_turn` to drive `act()`; every existing choose_*-style bot keeps working through an auto-applied `LegacyBotAdapter`. Phase 4 records every chosen action and replays a `(seed, actions)` record into an identical game.

**Tech Stack:** Python 3.14, stdlib only (`dataclasses`, `random`, `itertools`), `unittest` (run via `uv run python -m unittest`).

**Conventions used throughout:**
- Run a single test file: `uv run python -m unittest quality.tests.<module> -v` (from the repo root).
- Run everything: `uv run python -m unittest discover -s quality/tests`
- Engine source root: `services/native-runtime/src/ticket_to_ride/`
- All 126 existing tests must pass at the end of every task. New tests add to that count.

**Explicitly out of scope (YAGNI):** migrating the sandboxed bot HTTP protocol (`integrations/external/clients/bot_api`, `clients/python/api_interface.py`) to actions — those bots keep speaking choose_* and work through the adapter; converting `BootstrapRandomBot` in `runtime/cli.py` (adapter covers it); serializing actions into the PocketBase logger.

---

## File map

| File | Role in this plan |
|---|---|
| `services/native-runtime/src/ticket_to_ride/engine/state/decks.py` | Phase 1: accept an injected `random.Random` |
| `services/native-runtime/src/ticket_to_ride/engine/state/game_context.py` | Phase 1: `seed` param + `rng`; Phase 4: `action_log` |
| `applications/notebook_harness/game_runner.py` | Phase 1: `seed` passthrough |
| `services/native-runtime/src/ticket_to_ride/engine/state/views.py` | Phase 2: data-only `PlayerView` + pure queries; Phase 3: `decision`/`ticket_offer` fields |
| `services/native-runtime/src/ticket_to_ride/engine/player.py` | Phase 2: `attach()`, internals off the view; Phase 3: `take_turn` drives `act()` |
| `services/native-runtime/src/ticket_to_ride/engine/game.py` | Phase 2: attach players; Phase 3: `take_turn()` call |
| `services/native-runtime/src/ticket_to_ride/logging/game_logger.py` | Phase 2: serializer reads `view.routes`/`view.claimed_by` instead of `view.map` |
| `services/native-runtime/src/ticket_to_ride/engine/actions.py` | Phase 3 (new): action types + legal-menu functions |
| `services/native-runtime/src/ticket_to_ride/engine/legacy_adapter.py` | Phase 3 (new): `LegacyBotAdapter` |
| `services/native-runtime/src/ticket_to_ride/engine/state/map.py` | Phase 3: `route_by_id()` |
| `integrations/external/contracts/base_bot.py` | Phase 3: `ActionBot` contract |
| `integrations/external/bots/random_bot.py` | Phase 2: view reads; Phase 3: `act()` one-liner |
| `integrations/external/bots/example_bot.py` | Phase 2: view reads; Phase 3: `act()` edge, delete `_queued_draw` |
| `services/native-runtime/src/ticket_to_ride/engine/replay.py` | Phase 4 (new): `GameRecord`, `ScriptedBot`, `replay_game` |
| `quality/tests/test_engine_determinism.py` | Phase 1 (new) |
| `quality/tests/test_player_view.py` | Phase 2 (new) |
| `quality/tests/test_engine_actions.py` | Phase 3 (new) |
| `quality/tests/test_legacy_adapter.py` | Phase 3 (new) |
| `quality/tests/test_replay.py` | Phase 4 (new) |

---

## Phase 1 — Seeded RNG per game

### Task 1: Inject a seeded RNG into decks and GameContext

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/decks.py:26-42` (TrainCardDeck.__init__), `:88-95` (_reshuffle_discard), `:131-137` (TicketDeck.__init__)
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/game_context.py:12-21`
- Test: `quality/tests/test_engine_determinism.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_engine_determinism.py
import random
import unittest

from ticket_to_ride.engine.state.decks import TicketDeck, TrainCardDeck
from ticket_to_ride.engine.state.game_context import GameContext


class SeededDecksTests(unittest.TestCase):
    def test_same_seed_same_train_deck_order(self):
        a = TrainCardDeck(rng=random.Random(7))
        b = TrainCardDeck(rng=random.Random(7))
        self.assertEqual(a.get_face_up(), b.get_face_up())
        self.assertEqual(
            [a.draw_face_down() for _ in range(20)],
            [b.draw_face_down() for _ in range(20)],
        )

    def test_reshuffle_uses_injected_rng(self):
        a = TrainCardDeck(rng=random.Random(3))
        b = TrainCardDeck(rng=random.Random(3))
        for deck in (a, b):
            deck.discard([deck.draw_face_down() for _ in range(10)])
            deck._reshuffle_discard()
        self.assertEqual(
            [a.draw_face_down() for _ in range(10)],
            [b.draw_face_down() for _ in range(10)],
        )

    def test_same_seed_same_ticket_order(self):
        a = TicketDeck(rng=random.Random(7))
        b = TicketDeck(rng=random.Random(7))
        self.assertEqual(
            [(t.city1, t.city2) for t in a.deal_unique(5)],
            [(t.city1, t.city2) for t in b.deal_unique(5)],
        )


class SeededContextTests(unittest.TestCase):
    def test_context_seed_controls_decks(self):
        a = GameContext(["p1", "p2"], seed=99)
        b = GameContext(["p1", "p2"], seed=99)
        self.assertEqual(a.seed, 99)
        self.assertEqual(a.get_train_deck().get_face_up(), b.get_train_deck().get_face_up())
        self.assertEqual(
            [(t.city1, t.city2) for t in a.get_ticket_deck().deal_unique(3)],
            [(t.city1, t.city2) for t in b.get_ticket_deck().deal_unique(3)],
        )

    def test_unseeded_context_records_generated_seed(self):
        context = GameContext(["p1"])
        self.assertIsInstance(context.seed, int)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m unittest quality.tests.test_engine_determinism -v`
Expected: FAIL/ERROR — `TrainCardDeck.__init__() got an unexpected keyword argument 'rng'`

- [ ] **Step 3: Implement**

In `decks.py`, change `TrainCardDeck.__init__` to accept the rng and use it everywhere the module-level `random` was used (two `shuffle` sites):

```python
class TrainCardDeck:
    ...
    def __init__(self, rng: 'random.Random | None' = None):
        """Create and shuffle the deck used during the gameplay loop."""
        self._rng = rng or random.Random()
        self._deck: List[str] = []
        self._discard_pile: List[str] = []
        self._face_up: List[str] = []

        # Build deck using abbreviations
        for abbrev, count in self.COLOR_COUNTS.items():
            self._deck.extend([abbrev] * count)

        self._rng.shuffle(self._deck)
        self._refill_face_up_slot()

        # Mulligan rule enforcement
        while self._too_many_locomotives():
            self._mulligan_face_up()
```

and in `_reshuffle_discard` replace `random.shuffle(self._deck)` with `self._rng.shuffle(self._deck)`.

In `TicketDeck.__init__` add the parameter and replace the hardcoded `random.Random()`:

```python
    def __init__(self, csv_path: str | Path = TICKETS_CSV_PATH, rng: 'random.Random | None' = None):
        """Load destination tickets and prepare the draw stack."""
        self._master: List[DestinationTicket] = self._load_tickets_from_csv(csv_path)
        self._stack: Deque[DestinationTicket] = deque(self._master)
        self._rng = rng or random.Random()
        self._shuffle_stack()
```

In `game_context.py`:

```python
import logging
import random

from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.decks import TrainCardDeck, TicketDeck

from collections import Counter
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class GameContext:
    def __init__(self, player_ids, map_name: Optional[str] = None, seed: Optional[int] = None):
        """Holds shared state used throughout the gameplay loop.

        All engine randomness (deck shuffles, market refills, ticket deals)
        flows from `self.rng`, so a (seed, action sequence) pair replays to
        an identical game.
        """
        logger.info("Initializing GameContext...")
        self.seed = seed if seed is not None else random.randrange(2**32)
        self.rng = random.Random(self.seed)
        self.map_graph = MapGraph(player_count=len(player_ids), map_name=map_name)
        self.train_deck = TrainCardDeck(rng=self.rng)
        self.ticket_deck = TicketDeck(rng=self.rng)
        self.turn_num = 0
        # initialize score dictionary for all players
        # each player starts with a score of 0
        self.scores = {p: 0 for p in player_ids}
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m unittest quality.tests.test_engine_determinism -v` — expected PASS.
Run: `uv run python -m unittest discover -s quality/tests` — expected `OK` (126 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add quality/tests/test_engine_determinism.py services/native-runtime/src/ticket_to_ride/engine/state/decks.py services/native-runtime/src/ticket_to_ride/engine/state/game_context.py
git commit -m "feat(engine): seeded RNG threaded through GameContext and decks"
```

### Task 2: Seed passthrough for notebooks

**Files:**
- Modify: `applications/notebook_harness/game_runner.py:89-116` (initialize_game)
- Test: `quality/tests/test_engine_determinism.py` (extend)

- [ ] **Step 1: Write the failing test** (append to `test_engine_determinism.py`)

```python
class HarnessSeedTests(unittest.TestCase):
    def test_initialize_game_forwards_seed(self):
        from notebook_harness.game_runner import initialize_game

        class StubBot:
            def set_player(self, player):
                self.player = player

        a = initialize_game([StubBot(), StubBot()], seed=1234)
        b = initialize_game([StubBot(), StubBot()], seed=1234)
        self.assertEqual(a.game.context.seed, 1234)
        self.assertEqual(
            a.game.context.get_train_deck().get_face_up(),
            b.game.context.get_train_deck().get_face_up(),
        )
```

(`notebook_harness` imports directly in the test environment — see the top of `quality/tests/test_notebook_harness_game_runner.py`.)

- [ ] **Step 2: Run to verify failure** — `initialize_game() got an unexpected keyword argument 'seed'`

- [ ] **Step 3: Implement** — change the signature and the `GameContext` call in `initialize_game`:

```python
def initialize_game(
    bots: List[Any],
    map_name: str = DEFAULT_MAP_NAME,
    round_number: int = 0,
    seed: 'int | None' = None,
) -> HarnessGame:
    ...
    context = GameContext(player_ids, map_name=map_name, seed=seed)
```

(docstring: add `seed: pass an int to make the whole game reproducible; leave None for a random one — the generated value is on game.context.seed`.)

- [ ] **Step 4: Run tests** — determinism module PASS, full suite `OK`.

- [ ] **Step 5: Commit**

```bash
git add applications/notebook_harness/game_runner.py quality/tests/test_engine_determinism.py
git commit -m "feat(harness): initialize_game accepts a seed"
```

---

## Phase 2 — Data-only PlayerView

### Task 3: Rewrite PlayerView as data + pure queries

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/views.py` (PlayerView class only; OpponentInfo and the Global views stay)
- Test: `quality/tests/test_player_view.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_player_view.py
import unittest

from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _make_players(context):
    players = [Player(f"p{i}", _StubInterface(), f"p{i}", "red") for i in range(2)]
    for player in players:
        player.attach(context, players)
    return players


class PlayerViewTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=5)
        self.players = _make_players(self.context)

    def test_view_has_no_live_handles(self):
        view = PlayerView("p0", self.context, self.players)
        for forbidden in ("map", "train_deck", "ticket_deck"):
            self.assertFalse(hasattr(view, forbidden), forbidden)

    def test_scalars_and_copies(self):
        view = PlayerView("p0", self.context, self.players)
        self.assertEqual(view.player_id, "p0")
        self.assertEqual(view.trains_remaining, 45)
        self.assertEqual(view.train_cards_in_deck, len(self.context.get_train_deck()))
        self.assertEqual(view.tickets_in_deck, len(self.context.get_ticket_deck()))
        self.assertEqual(len(view.face_up_cards), 5)
        # hand is a copy: mutating it must not touch the player
        view.hand["R"] += 99
        self.assertNotEqual(view.hand["R"], self.players[0].get_hand().get("R", 0) + 0)

    def test_claimed_by_and_culled_map(self):
        map_graph = self.context.get_map()
        route = next(r for r in map_graph.routes if map_graph.is_route_claimable(r, "p0"))
        map_graph.claim_route(route, "p0")
        view = PlayerView("p0", self.context, self.players)
        self.assertEqual(view.claimed_by[route.route_id], "p0")
        self.assertTrue(view.is_connected(route.city1, route.city2))
        self.assertEqual(view.connection_cost(route.city1, route.city2), 0)
        self.assertIs(view.route_by_id(route.route_id), route)

    def test_affordable_routes_matches_player(self):
        player = self.players[0]
        player.get_hand().update(["R"] * 6 + ["L"] * 2)
        view = PlayerView("p0", self.context, self.players)
        from_view = {(r.route_id, n) for r, n in view.affordable_routes()}
        from_player = {(r.route_id, n) for r, n in player.get_affordable_routes()}
        self.assertEqual(from_view, from_player)


if __name__ == "__main__":
    unittest.main()
```

Note: `test_affordable_routes_matches_player` reaches into `player.get_hand()` to seed cards — that's the existing public accessor returning the live Counter.

- [ ] **Step 2: Run to verify failure** — `AttributeError: 'Player' object has no attribute 'attach'` (Task 4 adds it) and view attribute failures. This test goes green only after Task 4; that's fine — Tasks 3 and 4 commit together as one branch of work, but write the view first.

- [ ] **Step 3: Implement the new PlayerView** (replace the whole class in `views.py`; keep `OpponentInfo`, `GlobalPublicView`, `GlobalPrivateView`, and the `PlayerContext = PlayerView` alias; add imports `from ticket_to_ride.engine.state.map import MapGraph, Route, contract_map, _route_claimable_by` and `from typing import List, Optional, Tuple`):

```python
class PlayerView:
    """One seat's view of the game: plain data plus pure queries.

    Everything here is either a scalar, a copy, or a pure function of the
    captured claim state — there is nothing a bot can call to mutate the
    game. The engine builds a fresh view for every decision it asks a bot
    to make, so the data is always current as of that decision.

    `decision` says which decision this view was built for ("turn",
    "draw_second", or "keep_tickets"); `ticket_offer` carries the offered
    DestinationTickets during a "keep_tickets" decision.
    """

    def __init__(self, player_id: str, context, players: List,
                 decision: str = "turn",
                 ticket_offer: 'Optional[List]' = None):
        player = next(p for p in players if p.player_id == player_id)
        map_graph = context.get_map()
        train_deck = context.get_train_deck()

        self.player_id: str = player_id
        self.decision: str = decision
        self.ticket_offer = ticket_offer
        self.map_name: str = map_graph.map_name
        self.player_count: int = map_graph.player_count
        self.turn_number: int = context.turn_num
        self.score: int = context.get_score(player_id)
        self.face_up_cards: List[str] = train_deck.get_face_up()
        self.train_cards_in_deck: int = len(train_deck)
        self.tickets_in_deck: int = len(context.get_ticket_deck())
        self.hand: 'Counter[str]' = Counter(player.get_hand())
        self.trains_remaining: int = player.trains_remaining
        self.tickets: List = list(player.get_tickets())
        self.routes: List[Route] = list(map_graph.routes)
        self.claimed_by: 'dict[str, str]' = {
            route.route_id: route.claimed_by
            for route in self.routes if route.claimed_by is not None
        }

        self.opponents = [
            OpponentInfo(
                player_id=p.player_id,
                exposed_hand=Counter(p.get_exposed()),
                num_cards_in_hand=p.get_card_count(),
                remaining_trains=p.trains_remaining,
                score=context.get_score(p.player_id),
                destination_ticket_count=len(p.get_tickets()),
            ) for p in players if p.player_id != player_id
        ]

    def route_by_id(self, route_id: str) -> Route:
        index = getattr(self, "_routes_by_id", None)
        if index is None:
            index = {route.route_id: route for route in self.routes}
            self._routes_by_id = index
        return index[route_id]

    def culled_map(self):
        """This player's contracted board (see contract_map), from the
        claims as captured in this view."""
        return contract_map(self.routes, self.player_count, self.claimed_by, self.player_id)

    def is_connected(self, city1: str, city2: str) -> bool:
        return self.culled_map().connected(city1, city2)

    def connection_cost(self, city1: str, city2: str) -> 'int | None':
        return self.culled_map().cheapest_connection(city1, city2)

    def affordable_routes(self) -> 'List[Tuple[Route, int]]':
        """(route, locomotives) pairs this player could claim right now —
        the same algorithm as Player.get_affordable_routes, computed purely
        from this view's data."""
        if not self.hand.total():
            return []
        locomotives = self.hand.get("L", 0)
        colors = Counter({c: n for c, n in self.hand.items() if c != "L" and n > 0})
        most_common = max(colors.values(), default=0)

        siblings_by_key: 'dict[tuple, List[Route]]' = {}
        for route in self.routes:
            siblings_by_key.setdefault(route.sibling_group_key(), []).append(route)
        claim_of = lambda route: self.claimed_by.get(route.route_id)

        affordable = []
        for route in self.routes:
            siblings = [s for s in siblings_by_key[route.sibling_group_key()] if s is not route]
            if not _route_claimable_by(route, siblings, claim_of, self.player_id, self.player_count):
                continue
            if route.length > self.trains_remaining:
                continue
            for n in range(locomotives + 1):
                needed = route.length - n
                if colors.get(route.color, 0) >= needed or (route.color == "X" and most_common >= needed):
                    affordable.append((route, n))
                    break
        return affordable
```

Note: `OpponentInfo.exposed_hand` becomes a *copy* here (it was a live reference). The serializer reads it per turn, so nothing changes for logging.

- [ ] **Step 4: Do not run yet** — Player still reads `self.context.train_deck`; proceed straight to Task 4 (same commit).

### Task 4: Player mutates through an attached GameContext; view users updated

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/player.py`
- Modify: `services/native-runtime/src/ticket_to_ride/engine/game.py:41-43` (attach in `__init__`)
- Modify: `services/native-runtime/src/ticket_to_ride/logging/game_logger.py:69-114` (serializer)
- Modify tests: `quality/tests/test_logger_serializer.py`, `test_managed_match_api.py`, `test_runtime_executor.py`, `test_runtime_replay_transport.py`, `test_notebook_harness_in_memory_logger.py`, `test_example_bot.py`

- [ ] **Step 1: Add attach + reroute Player internals**

In `player.py`, add after `__init__`'s last line (`self.my_longest_path_length: int = 0`):

```python
        self._game = None      # GameContext; set by attach()
        self._players = []     # full seat list; set by attach()

    def attach(self, game_context, players: 'List[Player]') -> None:
        """Bind the live GameContext (the engine's mutation channel) and the
        seat list. Views handed to bots never carry these."""
        self._game = game_context
        self._players = list(players)

    @property
    def game_context(self):
        """The live GameContext. Engine-internal: bots get PlayerViews."""
        return self._game
```

Then replace every view-based engine access:

| Old | New |
|---|---|
| `self.context.train_deck` (take_turn deck check ×3, `__draw_train_cards`, `_spend_cards`) | `self._game.get_train_deck()` |
| `self.context.ticket_deck` (take_turn ticket check, `__draw_destination_tickets`) | `self._game.get_ticket_deck()` |
| `self.context.map` (`__claim_route`, `update_longest_path` ×3, `get_culled_map`, `get_affordable_routes`) | `self._game.get_map()` |

`get_culled_map` stays **live** (it must see mid-turn claims for `check_ticket_completion`); its docstring gains: "Live — reflects claims made this turn. Bots should prefer `view.culled_map()`."

- [ ] **Step 2: Game attaches players**

In `game.py` `__init__`, after `self.players = players`:

```python
        for p in players:
            p.attach(context, players)
```

- [ ] **Step 3: Serializer reads routes/claimed_by**

In `game_logger.py`, add to `GameLogSerializer`:

```python
    @staticmethod
    def _routes_claimed_by(view, player_id: str) -> List[Any]:
        return [route for route in view.routes if view.claimed_by.get(route.route_id) == player_id]
```

and replace the two `context.map.get_claimed_routes(...)` calls in `serialize_turn_state`:

```python
            "claimedRoutes": self.serialize_claimed_routes(self._routes_claimed_by(context, player.player_id)),
```
```python
                "claimedRoutes": self.serialize_claimed_routes(self._routes_claimed_by(context, opponent.player_id)),
```

- [ ] **Step 4: Update the serializer test fixture**

In `quality/tests/test_logger_serializer.py`: delete the `FakeMap` class and the `fake_map = FakeMap({...})` block; replace the `context = SimpleNamespace(...)` with:

```python
        routes = [
            FakeRoute("Seattle-Portland-1", "Seattle-Portland-X"),
            FakeRoute("Helena-Denver-1", "Helena-Denver-G"),
        ]
        context = SimpleNamespace(
            player_id="bot_1",
            score=12,
            routes=routes,
            claimed_by={"Seattle-Portland-1": "bot_1", "Helena-Denver-1": "bot_2"},
            face_up_cards=["R", "G", "L", "U", "W"],
            opponents=[
                SimpleNamespace(
                    player_id="bot_2",
                    score=8,
                    remaining_trains=39,
                    destination_ticket_count=3,
                    num_cards_in_hand=6,
                    exposed_hand=Counter({"B": 1, "Y": 2}),
                )
            ],
        )
```

Assertions stay unchanged.

- [ ] **Step 5: Update tests that hand-wire players**

Every `player.set_context(PlayerView(...))` call site needs an `attach` first. Exact edits:

- `test_managed_match_api.py:68` → before the loop body's `set_context`, insert `player.attach(self.base_context, self.players)`
- `test_runtime_executor.py:20` and `test_runtime_replay_transport.py:20` → insert `player.attach(context, players)` on the line above
- `test_notebook_harness_in_memory_logger.py:22,23,42` → insert `players[i].attach(context, players)` above each (or one loop: `for p in players: p.attach(context, players)`)
- `test_example_bot.py:36` → insert `player.attach(game.context, game.players)` above

- [ ] **Step 6: Run everything**

Run: `uv run python -m unittest quality.tests.test_player_view -v` — expected PASS (Task 3's tests go green now).
Run: `uv run python -m unittest discover -s quality/tests` — expected `OK`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(engine): PlayerView is data-only; Player mutates via attached GameContext"
```

### Task 5: Bots read only the view

**Files:**
- Modify: `integrations/external/bots/example_bot.py`, `integrations/external/bots/random_bot.py`

- [ ] **Step 1: Add the `_view` seam to both bots**

In each bot class add (this property is Phase 3's migration seam — `act()` will overwrite it with a per-decision view):

```python
    @property
    def _view(self):
        """The engine-built PlayerView for the current decision."""
        return self.player.context
```

- [ ] **Step 2: ExampleBot — replace Player reads with view reads**

| Location | Old | New |
|---|---|---|
| `_culled` (line 63) | `self.player.get_culled_map()` | `self._view.culled_map()` |
| `_unscored_tickets` (197) | `self.player.get_tickets()` | `self._view.tickets` |
| `_card_needs` (252) | `self.player.get_hand()` | `self._view.hand` |
| `choose_turn_action` (294) | `len(self.player.context.ticket_deck)` | `self._view.tickets_in_deck` |
| `choose_turn_action` (297, 299) | `self.player.get_affordable_routes()` | `self._view.affordable_routes()` |
| `choose_color_to_spend` (325) | `self.player.get_hand()` | `self._view.hand` |
| `_plan_draws` (347) | `self.player.context.face_up_cards` | `self._view.face_up_cards` |
| `select_ticket_offer` (392) | `self.player.trains_remaining` | `self._view.trains_remaining` |
| `select_ticket_offer` (395) | `self.player.get_tickets()` | `self._view.tickets` |

- [ ] **Step 3: RandomBot — same treatment**

```python
    def choose_turn_action(self):
        """Decide which action to take this turn."""
        if not [t for t in self._view.tickets if not t.is_completed]:
            return 3
        if self._view.affordable_routes():
            return 2
        return 1
```

Update the class docstring's "Helpful functions" section to point at `self._view` (`.affordable_routes()`, `.tickets`, `.hand`, `.trains_remaining`, `.culled_map()`).

- [ ] **Step 4: Run everything**

Run: `uv run python -m unittest discover -s quality/tests` — expected `OK` (test_example_bot runs a full game).

- [ ] **Step 5: Commit**

```bash
git add integrations/external/bots/example_bot.py integrations/external/bots/random_bot.py
git commit -m "refactor(bots): read game state exclusively through PlayerView"
```

---

## Phase 3 — Actions, legal menus, act(), legacy adapter

### Task 6: Action types and legal-menu functions

**Files:**
- Create: `services/native-runtime/src/ticket_to_ride/engine/actions.py`
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/map.py` (`route_by_id`)
- Test: `quality/tests/test_engine_actions.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_engine_actions.py
import unittest

from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets, Pass,
    legal_claim_actions, legal_keep_actions, legal_second_draw_actions, legal_turn_actions,
)
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _game_and_player():
    context = GameContext(["p0", "p1"], seed=11)
    players = [Player(f"p{i}", _StubInterface(), f"p{i}", "red") for i in range(2)]
    for p in players:
        p.attach(context, players)
    return context, players[0]


class LegalMenuTests(unittest.TestCase):
    def test_turn_menu_has_draws_and_tickets(self):
        context, player = _game_and_player()
        legal = legal_turn_actions(player)
        self.assertIn(DrawBlind(), legal)
        self.assertIn(DrawTickets(), legal)
        face_ups = [a for a in legal if isinstance(a, DrawFaceUp)]
        self.assertEqual(len(face_ups), 5)
        for action in face_ups:
            self.assertEqual(context.get_train_deck().get_face_up()[action.index], action.card)

    def test_no_cards_means_no_claims(self):
        _, player = _game_and_player()
        self.assertEqual(legal_claim_actions(player), [])

    def test_claims_enumerate_colors_and_locomotives(self):
        _, player = _game_and_player()
        player.get_hand().update(["R"] * 4 + ["L"] * 1)
        claims = legal_claim_actions(player)
        self.assertTrue(claims)
        for action in claims:
            self.assertIsInstance(action, ClaimRoute)
            self.assertIn(action.color, {"R", "L"})
        # both locomotive spends are enumerated for routes the hand affords
        self.assertEqual({a.locomotives for a in claims}, {0, 1})
        # a route claimable with 0 locomotives is also claimable with 1
        zero_loco = {a.route_id for a in claims if a.locomotives == 0}
        one_loco = {a.route_id for a in claims if a.locomotives == 1}
        self.assertTrue(zero_loco <= one_loco)

    def test_second_draw_excludes_locomotives(self):
        context, player = _game_and_player()
        legal = legal_second_draw_actions(player)
        for action in legal:
            if isinstance(action, DrawFaceUp):
                self.assertNotEqual(action.card, "L")

    def test_keep_menu_sizes(self):
        self.assertEqual(len(legal_keep_actions(3, 1)), 7)   # all non-empty subsets
        self.assertEqual(len(legal_keep_actions(3, 2)), 4)   # size >= 2
        self.assertEqual(len(legal_keep_actions(1, 2)), 1)   # floor clamps to offer size

    def test_route_by_id(self):
        context, _ = _game_and_player()
        route = context.get_map().routes[0]
        self.assertIs(context.get_map().route_by_id(route.route_id), route)

    def test_empty_menu_is_pass(self):
        context, player = _game_and_player()
        deck = context.get_train_deck()
        while len(deck):
            deck.draw_face_down()
        ticket_deck = context.get_ticket_deck()
        while len(ticket_deck) >= 3:
            ticket_deck.deal_unique(3)
        legal = legal_turn_actions(player)
        self.assertEqual(legal, [Pass()])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ticket_to_ride.engine.actions`

- [ ] **Step 3: Implement `actions.py`**

```python
"""Action types and legal-move enumeration.

A turn is one action from legal_turn_actions plus its follow-ups (a second
card pick, or a ticket-keep choice). Bots implement
`act(view, legal_actions) -> action`; anything outside the menu is replaced
with the menu's first entry, so illegal play is impossible by construction.
"""
from dataclasses import dataclass
from itertools import combinations
from typing import List, Tuple


@dataclass(frozen=True)
class Action:
    pass


@dataclass(frozen=True)
class Pass(Action):
    """Nothing legal to do this turn."""


@dataclass(frozen=True)
class DrawBlind(Action):
    """Draw the top card of the face-down deck."""


@dataclass(frozen=True)
class DrawFaceUp(Action):
    """Take the market card at `index` (currently `card`)."""
    index: int
    card: str


@dataclass(frozen=True)
class ClaimRoute(Action):
    """Claim `route_id`, spending `locomotives` L cards plus `color` cards
    for the rest (`color` is "L" when locomotives cover the whole route)."""
    route_id: str
    color: str
    locomotives: int


@dataclass(frozen=True)
class DrawTickets(Action):
    """Take a destination-ticket offer (followed by a keep_tickets decision)."""


@dataclass(frozen=True)
class KeepTickets(Action):
    """Keep the offer tickets at these indices; return the rest."""
    indices: Tuple[int, ...]


def legal_turn_actions(player) -> List[Action]:
    """Everything the player may open their turn with.

    Mirrors the old fault-flag rules: drawing needs 2+ cards in the deck
    (after folding the discard back in), tickets need a 3-card offer.
    """
    game = player.game_context
    actions: List[Action] = []

    deck = game.get_train_deck()
    if len(deck) < 2:
        deck._reshuffle_discard()
    if len(deck) >= 2:
        actions.append(DrawBlind())
        actions.extend(DrawFaceUp(i, card) for i, card in enumerate(deck.get_face_up()))

    actions.extend(legal_claim_actions(player))

    if len(game.get_ticket_deck()) >= 3:
        actions.append(DrawTickets())

    return actions or [Pass()]


def legal_second_draw_actions(player) -> List[Action]:
    """The second card pick: face-up locomotives are off the menu."""
    deck = player.game_context.get_train_deck()
    actions: List[Action] = []
    if len(deck) or deck.get_discard_pile():
        actions.append(DrawBlind())
    actions.extend(
        DrawFaceUp(i, card)
        for i, card in enumerate(deck.get_face_up())
        if card != "L"
    )
    return actions or [Pass()]


def legal_claim_actions(player) -> List[ClaimRoute]:
    """Every (route, color, locomotive-count) combination the hand affords."""
    game = player.game_context
    hand = player.get_hand()
    locomotives = hand.get("L", 0)
    actions: List[ClaimRoute] = []
    for route in game.get_map().get_available_routes(player.player_id):
        if route.length > player.trains_remaining:
            continue
        for spent_locos in range(min(locomotives, route.length) + 1):
            needed = route.length - spent_locos
            if needed == 0:
                actions.append(ClaimRoute(route.route_id, "L", spent_locos))
                continue
            colors = [route.color] if route.color != "X" else [c for c in hand if c != "L"]
            for color in colors:
                if hand.get(color, 0) >= needed:
                    actions.append(ClaimRoute(route.route_id, color, spent_locos))
    return actions


def legal_keep_actions(offer_size: int, min_keep: int) -> List[KeepTickets]:
    """Every allowed subset of an offer (setup uses min_keep=2, later 1)."""
    floor = max(1, min(min_keep, offer_size))
    return [
        KeepTickets(tuple(combo))
        for size in range(floor, offer_size + 1)
        for combo in combinations(range(offer_size), size)
    ]
```

In `map.py` `MapGraph.__init__`, next to the sibling index add `self._routes_by_id: Dict[str, Route] = {route.route_id: route for route in self.routes}`, and add the method:

```python
    def route_by_id(self, route_id: str) -> Route:
        return self._routes_by_id[route_id]
```

- [ ] **Step 4: Run tests** — actions module PASS, full suite `OK`.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/actions.py services/native-runtime/src/ticket_to_ride/engine/state/map.py quality/tests/test_engine_actions.py
git commit -m "feat(engine): action types and legal-move enumeration"
```

### Task 7: ActionBot contract and LegacyBotAdapter

**Files:**
- Modify: `integrations/external/contracts/base_bot.py` (append ActionBot)
- Create: `services/native-runtime/src/ticket_to_ride/engine/legacy_adapter.py`
- Test: `quality/tests/test_legacy_adapter.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_legacy_adapter.py
import unittest
from collections import Counter
from types import SimpleNamespace

from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets,
)
from ticket_to_ride.engine.legacy_adapter import LegacyBotAdapter


def _view(decision, **kwargs):
    defaults = {"decision": decision, "hand": Counter(), "ticket_offer": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _LegacyBot:
    def __init__(self, turn=1, draw=-1, keep=None):
        self._turn, self._draw, self._keep = turn, draw, keep
    def set_player(self, player):
        self.player = player
    def choose_turn_action(self):
        return self._turn
    def choose_draw_train_action(self):
        return self._draw
    def choose_route_to_claim(self, claimable_routes):
        return claimable_routes[0]
    def choose_color_to_spend(self, route, color_options):
        return color_options[0]
    def select_ticket_offer(self, offer):
        return self._keep(offer) if self._keep else offer[:2]


class AdapterTests(unittest.TestCase):
    def test_draw_choice_maps_to_face_up(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=1, draw=2))
        legal = [DrawBlind(), DrawFaceUp(0, "R"), DrawFaceUp(2, "G"), DrawTickets()]
        self.assertEqual(adapter.act(_view("turn"), legal), DrawFaceUp(2, "G"))

    def test_invalid_draw_index_falls_back_to_blind(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=1, draw=4))
        legal = [DrawBlind(), DrawFaceUp(0, "R")]
        self.assertEqual(adapter.act(_view("draw_second"), legal), DrawBlind())

    def test_claim_choice_resolves_color(self):
        route = SimpleNamespace(route_id="A-B-1", color="X", length=2)
        adapter = LegacyBotAdapter(_LegacyBot(turn=2))
        legal = [
            ClaimRoute("A-B-1", "R", 0),
            ClaimRoute("A-B-1", "G", 0),
            DrawBlind(),
        ]
        view = _view("turn", route_by_id=lambda rid: route, hand=Counter({"R": 2, "G": 2}))
        chosen = adapter.act(view, legal)
        self.assertIsInstance(chosen, ClaimRoute)
        self.assertEqual(chosen.color, "R")  # legacy bot picked color_options[0]

    def test_keep_maps_tickets_to_indices(self):
        t = [SimpleNamespace(value=i) for i in range(3)]
        adapter = LegacyBotAdapter(_LegacyBot(keep=lambda offer: [offer[0], offer[2]]))
        legal = [KeepTickets((0, 1)), KeepTickets((0, 2)), KeepTickets((1, 2)), KeepTickets((0, 1, 2))]
        self.assertEqual(adapter.act(_view("keep_tickets", ticket_offer=t), legal), KeepTickets((0, 2)))

    def test_keep_below_minimum_upgrades_to_superset(self):
        t = [SimpleNamespace(value=i) for i in range(3)]
        adapter = LegacyBotAdapter(_LegacyBot(keep=lambda offer: [offer[1]]))
        legal = [KeepTickets((0, 1)), KeepTickets((1, 2)), KeepTickets((0, 1, 2))]
        chosen = adapter.act(_view("keep_tickets", ticket_offer=t), legal)
        self.assertIn(1, chosen.indices)
        self.assertEqual(len(chosen.indices), 2)

    def test_ticket_turn_choice(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=3))
        legal = [DrawBlind(), DrawTickets()]
        self.assertEqual(adapter.act(_view("turn"), legal), DrawTickets())

    def test_claim_wanted_but_unavailable_falls_to_draw(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=2, draw=-1))
        legal = [DrawBlind(), DrawFaceUp(0, "R")]
        self.assertEqual(adapter.act(_view("turn"), legal), DrawBlind())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ticket_to_ride.engine.legacy_adapter`

- [ ] **Step 3: Implement**

Append to `integrations/external/contracts/base_bot.py`:

```python
class ActionBot(BaseBot):
    """New-style bot: implement act(view, legal_actions) -> action.

    view is a ticket_to_ride PlayerView; legal_actions is a non-empty list
    of engine Action dataclasses. Returning anything outside the list makes
    the engine take legal_actions[0] instead. The legacy choose_* contract
    is stubbed out — the engine never calls it on a bot that defines act().
    """

    @abstractmethod
    def act(self, view: Any, legal_actions: List[Any]) -> Any:
        raise NotImplementedError

    def choose_turn_action(self):
        raise RuntimeError("action bots decide via act()")

    def choose_draw_train_action(self) -> int:
        raise RuntimeError("action bots decide via act()")

    def choose_route_to_claim(self, claimable_routes):
        raise RuntimeError("action bots decide via act()")

    def choose_color_to_spend(self, route, color_options):
        raise RuntimeError("action bots decide via act()")

    def select_ticket_offer(self, offer) -> List[Any]:
        raise RuntimeError("action bots decide via act()")
```

Create `engine/legacy_adapter.py`:

```python
"""Adapter that drives a choose_*-style bot through the act() interface.

Player wraps any interface without a callable act() in this adapter, so
every pre-action-model bot (notebook bots, the runtime's bootstrap bot,
sandboxed API clients) keeps working unchanged.
"""
import logging
from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets,
)

logger = logging.getLogger(__name__)


class LegacyBotAdapter:
    def __init__(self, bot):
        self.bot = bot

    def set_player(self, player):
        self.player = player
        self.bot.set_player(player)

    def begin_turn(self):
        hook = getattr(self.bot, "begin_turn", None)
        if callable(hook):
            hook()

    def end_turn(self, completed):
        hook = getattr(self.bot, "end_turn", None)
        if callable(hook):
            hook(completed)

    def act(self, view, legal_actions):
        if view.decision == "keep_tickets":
            return self._keep(view, legal_actions)
        if view.decision == "draw_second":
            return self._draw(self.bot.choose_draw_train_action(), legal_actions)
        return self._turn(view, legal_actions)

    def _turn(self, view, legal_actions):
        claims = [a for a in legal_actions if isinstance(a, ClaimRoute)]
        draws = [a for a in legal_actions if isinstance(a, (DrawBlind, DrawFaceUp))]
        tickets_offered = any(isinstance(a, DrawTickets) for a in legal_actions)
        choice = self.bot.choose_turn_action()
        if choice == 3 and tickets_offered:
            return DrawTickets()
        if choice == 2 and claims:
            return self._claim(view, claims)
        if draws:
            return self._draw(self.bot.choose_draw_train_action(), draws)
        if claims:  # deck dry: forced claim, like the old draw_train fault flag
            return self._claim(view, claims)
        if tickets_offered:
            return DrawTickets()
        return legal_actions[0]

    def _draw(self, pick, legal_actions):
        if pick >= 0:
            for action in legal_actions:
                if isinstance(action, DrawFaceUp) and action.index == pick:
                    return action
        for action in legal_actions:
            if isinstance(action, DrawBlind):
                return action
        return legal_actions[0]

    def _claim(self, view, claims):
        # Rebuild the (route, locomotives) menu the legacy contract expects:
        # one entry per route, at its minimum locomotive spend.
        options = {}
        for action in claims:
            current = options.get(action.route_id)
            if current is None or action.locomotives < current[1]:
                options[action.route_id] = (view.route_by_id(action.route_id), action.locomotives)
        route, locomotives = self.bot.choose_route_to_claim(list(options.values()))
        candidates = [a for a in claims if a.route_id == route.route_id and a.locomotives == locomotives]
        if not candidates:
            candidates = [a for a in claims if a.route_id == route.route_id] or claims
        if len(candidates) > 1:
            colors = [a.color for a in candidates if a.color != "L"]
            chosen_color = self.bot.choose_color_to_spend(route, colors)
            for action in candidates:
                if action.color == chosen_color:
                    return action
            # legacy None/invalid answer: spend the largest stack, mirroring
            # the old engine fallback
            hand = view.hand
            return max(candidates, key=lambda a: hand.get(a.color, 0))
        return candidates[0]

    def _keep(self, view, legal_actions):
        offer = view.ticket_offer
        kept = self.bot.select_ticket_offer(offer)
        indices = tuple(sorted(offer.index(t) for t in kept if t in offer))
        choice = KeepTickets(indices)
        if choice in legal_actions:
            return choice
        supersets = [
            a for a in legal_actions
            if isinstance(a, KeepTickets) and set(indices) <= set(a.indices)
        ]
        if supersets:
            return min(supersets, key=lambda a: len(a.indices))
        logger.warning("Legacy keep %r has no legal mapping; using %r", indices, legal_actions[0])
        return legal_actions[0]
```

- [ ] **Step 4: Run tests** — adapter module PASS, full suite `OK`.

- [ ] **Step 5: Commit**

```bash
git add integrations/external/contracts/base_bot.py services/native-runtime/src/ticket_to_ride/engine/legacy_adapter.py quality/tests/test_legacy_adapter.py
git commit -m "feat(engine): ActionBot contract and LegacyBotAdapter"
```

### Task 8: take_turn drives act(); fault flags deleted

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/player.py`
- Modify: `services/native-runtime/src/ticket_to_ride/engine/game.py` (`next_turn` call)
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/views.py` — nothing to do if Task 3 shipped `decision`/`ticket_offer` (it did)
- Test: `quality/tests/test_engine_actions.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to `test_engine_actions.py`)

```python
from ticket_to_ride.engine.actions import Action
from ticket_to_ride.engine.game import Game


class _FirstLegalBot:
    """Claims when possible, otherwise takes the first legal action."""
    def set_player(self, player):
        self.player = player
    def act(self, view, legal_actions):
        for action in legal_actions:
            if isinstance(action, ClaimRoute):
                return action
        return legal_actions[0]


class _IllegalBot:
    def set_player(self, player):
        self.player = player
    def act(self, view, legal_actions):
        return "nonsense"


class _NullLogger:
    def record_turn(self, *args, **kwargs):
        return None


class ActTurnFlowTests(unittest.TestCase):
    def _run(self, bot_classes, seed=21):
        players = [Player(f"p{i}", cls(), f"p{i}", "red") for i, cls in enumerate(bot_classes)]
        context = GameContext([p.player_id for p in players], seed=seed)
        game = Game(context, players, _NullLogger(), 0)
        game.play()
        return game

    def test_full_game_with_act_bots(self):
        game = self._run([_FirstLegalBot, _FirstLegalBot])
        self.assertTrue(any(p.trains_remaining <= 2 for p in game.players))
        deck = game.context.get_train_deck()
        total = (
            len(deck) + len(deck.get_discard_pile()) + len(deck.get_face_up())
            + sum(p.get_card_count() for p in game.players)
        )
        self.assertEqual(total, 110)

    def test_illegal_action_falls_back_and_completes(self):
        game = self._run([_IllegalBot, _FirstLegalBot])
        self.assertGreater(game.turn_index, 0)

    def test_setup_keeps_at_least_two_tickets(self):
        game = self._run([_FirstLegalBot, _FirstLegalBot])
        for p in game.players:
            self.assertGreaterEqual(len(p.get_tickets()), 2)
```

- [ ] **Step 2: Run to verify failure** — `_FirstLegalBot` has no `choose_turn_action`, so the current take_turn crashes.

- [ ] **Step 3: Rewrite Player's turn machinery**

Imports at the top of `player.py`:

```python
from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, Pass,
    legal_keep_actions, legal_second_draw_actions, legal_turn_actions,
)
from ticket_to_ride.engine.legacy_adapter import LegacyBotAdapter
```

In `Player.__init__`, wrap non-act interfaces (replace the two interface lines):

```python
        if not callable(getattr(interface, "act", None)):
            interface = LegacyBotAdapter(interface)
        self.__interface = interface
        self.__interface.set_player(self)
```

Replace `set_context`'s setup branch (blind draws stay engine-forced; the double ticket draw is replaced by a proper keep-2 menu):

```python
    def set_context(self, context: PlayerView, setup: bool = False):
        """Provide the player with the latest :class:`PlayerView`."""
        self.context = context
        if setup:
            deck = self._game.get_train_deck()
            for _ in range(4):
                self.__add_cards([deck.draw_face_down()], False)
            self.__draw_destination_tickets(min_keep=2)
```

Replace `take_turn` (the whole retry loop) and delete `__draw_train_cards` and `__claim_available_route`:

```python
    def take_turn(self) -> None:
        """Execute one turn: offer the legal menu, apply the chosen action."""
        begin_turn = getattr(self.__interface, "begin_turn", None)
        if callable(begin_turn):
            begin_turn()
        completed = False
        try:
            action = self.__choose(legal_turn_actions(self), "turn")
            if isinstance(action, (DrawBlind, DrawFaceUp)):
                drew_locomotive = self.__apply_draw(action)
                if not drew_locomotive:
                    second = self.__choose(legal_second_draw_actions(self), "draw_second")
                    if not isinstance(second, Pass):
                        self.__apply_draw(second)
            elif isinstance(action, ClaimRoute):
                self.__apply_claim(action)
            elif isinstance(action, DrawTickets):
                self.__draw_destination_tickets()
            # Pass: nothing to do.

            # Re-evaluate tickets every turn, not only after own claims:
            # opponents' claims since last turn may have cut a ticket off, and
            # a shrinking train supply can make one impossible.
            self.check_ticket_completion()
            completed = True
        finally:
            end_turn = getattr(self.__interface, "end_turn", None)
            if callable(end_turn):
                end_turn(completed)

    def __choose(self, legal, decision: str, ticket_offer=None):
        """Build a fresh view, ask the interface, enforce legality."""
        view = PlayerView(
            self.player_id, self._game, self._players,
            decision=decision, ticket_offer=ticket_offer,
        )
        action = self.__interface.act(view, legal)
        if action not in legal:
            logger.warning(
                "Player %s chose illegal action %r for %s; using %r instead.",
                self.player_id, action, decision, legal[0],
            )
            action = legal[0]
        return action

    def __apply_draw(self, action) -> bool:
        """Apply a draw action; True if it was a face-up locomotive (which
        ends the drawing for this turn)."""
        deck = self._game.get_train_deck()
        if isinstance(action, DrawFaceUp):
            card = deck.draw_face_up(action.index)
            self.__add_cards([card], True)
            return card == "L"
        self.__add_cards([deck.draw_face_down()], False)
        return False

    def __apply_claim(self, action: ClaimRoute) -> None:
        route = self._game.get_map().route_by_id(action.route_id)
        needed = route.length - action.locomotives
        cards = ["L"] * action.locomotives
        if action.color != "L":
            cards.extend([action.color] * needed)
        self._spend_cards(cards)
        self.__claim_route(route)
        self.update_longest_path(route)
```

Replace `__draw_destination_tickets` (offer → keep menu → apply):

```python
    def __draw_destination_tickets(self, min_keep: int = 1) -> bool:
        """Offer destination tickets; the interface picks a legal keep-set."""
        try:
            offer = self._game.get_ticket_deck().deal_unique(3)
        except Exception as e:
            logger.warning("Ticket draw failed for player %s: %s", self.player_id, e)
            return False
        if not offer:
            logger.info("No destination tickets available for %s.", self.player_id)
            return False

        legal = legal_keep_actions(len(offer), min_keep)
        choice = self.__choose(legal, "keep_tickets", ticket_offer=offer)
        kept = [offer[i] for i in choice.indices]
        self.__tickets.extend(kept)
        returned = [t for i, t in enumerate(offer) if i not in choice.indices]
        self._game.get_ticket_deck().return_tickets(returned)
        return True
```

In `game.py` `next_turn`, the call becomes:

```python
        player.take_turn()
```

(the fault-flag dict argument is gone).

- [ ] **Step 4: Run everything**

Run: `uv run python -m unittest quality.tests.test_engine_actions -v` — PASS.
Run: `uv run python -m unittest discover -s quality/tests` — **`OK` is the acceptance gate**: every legacy-bot test (example bot game, runtime executor/replay/clock, managed match API) now runs through the adapter. Investigate any failure here before proceeding — this is the riskiest task in the plan.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(engine): take_turn drives act() through legal menus; fault flags removed"
```

### Task 9: RandomBot becomes an ActionBot

**Files:**
- Modify: `integrations/external/bots/random_bot.py`

- [ ] **Step 1: Rewrite the class** (keep `BOT_META`, the marimo cells, and `path_finder`; update the setup-cell import to `from external.contracts.base_bot import ActionBot`):

```python
class RandomBot(ActionBot):
    """Baseline bot: picks a uniformly random legal action.

    ``act`` receives a ``PlayerView`` (data-only snapshot of everything the
    seat may see: ``hand``, ``tickets``, ``face_up_cards``, ``opponents``,
    ``affordable_routes()``, ``culled_map()``) and a non-empty list of legal
    engine actions. Whatever it returns is applied; anything outside the
    list is replaced with the first legal action.
    """

    META = BOT_META

    def act(self, view, legal_actions):
        return random.choice(legal_actions)

    def path_finder(self, city1, city2):
        """Placeholder for path-finding logic."""
        return None
```

Delete the five `choose_*` methods and the old docstring's helper list.

- [ ] **Step 2: Run everything** — `uv run python -m unittest discover -s quality/tests` → `OK` (loader tests re-import the notebook module).

- [ ] **Step 3: Commit**

```bash
git add integrations/external/bots/random_bot.py
git commit -m "refactor(bots): RandomBot picks a random legal action via act()"
```

### Task 10: ExampleBot becomes an ActionBot

**Files:**
- Modify: `integrations/external/bots/example_bot.py`

The planning core (`_steiner_tree`, `_dijkstra`, `_replan`, `_card_needs`, `_claimable_planned`, `_unscored_tickets`, `_pick_initial_tickets`, and the ticket-selection logic) is untouched. Only the engine-facing edge changes.

- [ ] **Step 1: Update the class declaration and imports**

Setup cell: add `ActionBot` to the `base_bot` import, and add
`from ticket_to_ride.engine.actions import ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets`.
Class becomes `class ExampleBot(ActionBot):`.

- [ ] **Step 2: Replace the migration seam**

Delete the `_view` property from Task 5 and delete `self._queued_draw` from `__init__`. `act()` now sets the attribute directly, so every helper that reads `self._view` keeps working:

```python
    def act(self, view, legal_actions):
        self._view = view
        if view.decision == "keep_tickets":
            return self._keep_action(view, legal_actions)
        if view.decision == "draw_second":
            return self._draw_action(view, legal_actions)
        return self._turn_action(view, legal_actions)
```

- [ ] **Step 3: Replace the "Engine-facing decisions" section**

Delete `choose_turn_action`, `choose_draw_train_action`, `_plan_draws`, `choose_color_to_spend`; rename `choose_route_to_claim` → `_choose_route_pick` (body unchanged); rename `select_ticket_offer` → `_select_tickets` (body unchanged). Add:

```python
    def _turn_action(self, view, legal_actions):
        """Tickets all scored -> draw more; else claim if a planned route is
        affordable; else draw train cards."""
        claims = [a for a in legal_actions if isinstance(a, ClaimRoute)]
        draws = [a for a in legal_actions if isinstance(a, (DrawBlind, DrawFaceUp))]
        tickets_offered = any(isinstance(a, DrawTickets) for a in legal_actions)

        if not self._unscored_tickets():
            if tickets_offered:
                return DrawTickets()
            # Deck can't serve an offer: score points instead of stalling.
            if claims:
                return self._claim_action(view, claims)
            if draws:
                return self._draw_action(view, draws)
            return legal_actions[0]

        self._replan()
        if claims and self._claimable_planned(self._picks_from_claims(view, claims)):
            return self._claim_action(view, claims)
        if draws:
            return self._draw_action(view, draws)
        if claims:  # forced: train deck is dry
            return self._claim_action(view, claims)
        if tickets_offered:
            return DrawTickets()
        return legal_actions[0]

    @staticmethod
    def _picks_from_claims(view, claims):
        """Rebuild (route, locomotives) picks — one per route at its minimum
        locomotive spend — so the pre-action planning helpers keep working."""
        best = {}
        for action in claims:
            current = best.get(action.route_id)
            if current is None or action.locomotives < current[1]:
                best[action.route_id] = (view.route_by_id(action.route_id), action.locomotives)
        return list(best.values())

    def _claim_action(self, view, claims):
        picks = self._picks_from_claims(view, claims)
        route, locomotives = self._choose_route_pick(picks)
        candidates = [a for a in claims if a.route_id == route.route_id and a.locomotives == locomotives]
        if not candidates:
            candidates = [a for a in claims if a.route_id == route.route_id] or claims
        if len(candidates) == 1:
            return candidates[0]
        # Gray route: spend the color the plan needs least (largest surplus
        # stack first, so reserved colors stay untouched).
        needs = self._card_needs()
        hand = view.hand
        return min(candidates, key=lambda a: (needs.get(a.color, 0), -hand.get(a.color, 0)))

    def _draw_action(self, view, draw_actions):
        """Best single pick against the market as it is right now: biggest
        deficit color first, never a face-up locomotive, else the deck.

        (The old two-pick planning and its _queued_draw hack are obsolete:
        the engine now shows the refreshed market before the second pick.)
        """
        self._replan()
        needs = self._card_needs()
        useful = [
            a for a in draw_actions
            if isinstance(a, DrawFaceUp) and a.card != "L" and needs.get(a.card, 0) > 0
        ]
        if useful:
            return max(useful, key=lambda a: needs[a.card])
        for action in draw_actions:
            if isinstance(action, DrawBlind):
                return action
        return draw_actions[0]

    def _keep_action(self, view, legal_actions):
        kept = self._select_tickets(view.ticket_offer)
        indices = tuple(sorted(view.ticket_offer.index(t) for t in kept))
        choice = KeepTickets(indices)
        if choice in legal_actions:
            return choice
        supersets = [
            a for a in legal_actions
            if isinstance(a, KeepTickets) and set(indices) <= set(a.indices)
        ]
        if supersets:
            return min(supersets, key=lambda a: len(a.indices))
        return legal_actions[0]
```

Inside `_choose_route_pick` (ex-`choose_route_to_claim`), delete its leading `self._replan()` line's duplicate only if present in both paths — keep one `_replan()` in `_turn_action` and leave the one in `_choose_route_pick` (forced claims arrive without a preceding replan; a second replan is idempotent).

- [ ] **Step 4: Update `test_example_bot.py` if it drives choose_* directly**

`quality/tests/test_example_bot.py:36` wires a player and (line ~28+) may call `choose_*` methods on the bot. Update any direct `bot.choose_turn_action()`-style calls to build a `PlayerView` and call `bot.act(view, legal_turn_actions(player))`. The full-game test (line 15) needs no change.

- [ ] **Step 5: Run everything** — `uv run python -m unittest discover -s quality/tests` → `OK`. Also smoke a real game:

```bash
uv run python - <<'EOF'
import sys
sys.path.insert(0, "applications")
sys.path.insert(0, "integrations")
from notebook_harness.game_runner import available_bots, initialize_game
bots = available_bots()
game = initialize_game([bots["Example Bot"](), bots["Random Bot"]()], seed=7)
game.play()
print("turns:", game.snapshot_count(), "scores:", game.game.context.scores)
EOF
```

Expected: completes, no warnings about illegal actions from ExampleBot.

- [ ] **Step 6: Commit**

```bash
git add integrations/external/bots/example_bot.py quality/tests/test_example_bot.py
git commit -m "refactor(bots): ExampleBot decides via act(); _queued_draw hack deleted"
```

---

## Phase 4 — Action log and replay

### Task 11: Record actions; replay a (seed, actions) record

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/game_context.py` (action_log)
- Modify: `services/native-runtime/src/ticket_to_ride/engine/player.py` (`__choose` records)
- Create: `services/native-runtime/src/ticket_to_ride/engine/replay.py`
- Test: `quality/tests/test_replay.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_replay.py
import json
import random
import unittest

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.replay import GameRecord, record_of, replay_game
from ticket_to_ride.engine.state.game_context import GameContext


class _NullLogger:
    def record_turn(self, *args, **kwargs):
        return None


class _SeededRandomBot:
    def __init__(self, seed):
        self._rng = random.Random(seed)
    def set_player(self, player):
        self.player = player
    def act(self, view, legal_actions):
        return self._rng.choice(legal_actions)


def _play_recorded(seed=31):
    players = [Player(f"p{i}", _SeededRandomBot(seed + i), f"p{i}", "red") for i in range(3)]
    context = GameContext([p.player_id for p in players], seed=seed)
    game = Game(context, players, _NullLogger(), 0)
    game.play()
    return game


class ReplayTests(unittest.TestCase):
    def test_replay_reproduces_the_game(self):
        original = _play_recorded()
        record = record_of(original)
        self.assertTrue(record.actions)

        replayed = replay_game(record)
        self.assertEqual(replayed.context.scores, original.context.scores)
        self.assertEqual(
            {r.route_id: r.claimed_by for r in replayed.context.get_map().routes},
            {r.route_id: r.claimed_by for r in original.context.get_map().routes},
        )
        self.assertEqual(replayed.context.action_log, original.context.action_log)

    def test_record_round_trips_through_json(self):
        original = _play_recorded(seed=77)
        record = record_of(original)
        restored = GameRecord.from_dict(json.loads(json.dumps(record.to_dict())))
        self.assertEqual(restored, record)
        replayed = replay_game(restored)
        self.assertEqual(replayed.context.scores, original.context.scores)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ticket_to_ride.engine.replay`

- [ ] **Step 3: Implement**

`game_context.py` — add to `__init__` (after `self.scores = ...`):

```python
        # Every action a player chose, in play order: (player_id, Action).
        # With self.seed this replays to an identical game (engine/replay.py).
        self.action_log: List[tuple] = []
```

`player.py` `__choose` — after the legality check, before `return action`:

```python
        self._game.action_log.append((self.player_id, action))
```

Create `engine/replay.py`:

```python
"""Deterministic replay: a (seed, action sequence) pair rebuilds a game.

record_of(game) captures the record after (or during) a game whose players
chose through the act() interface; replay_game(record) reconstructs the
identical final state by scripting those actions back through the engine
with the same RNG seed.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import List, Tuple

from ticket_to_ride.engine.actions import (
    Action, ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets, Pass,
)
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext

_ACTION_TYPES = {
    cls.__name__: cls
    for cls in (Pass, DrawBlind, DrawFaceUp, ClaimRoute, DrawTickets, KeepTickets)
}


def action_to_dict(action: Action) -> dict:
    return {"type": type(action).__name__, **asdict(action)}


def action_from_dict(data: dict) -> Action:
    data = dict(data)
    cls = _ACTION_TYPES[data.pop("type")]
    if "indices" in data:
        data["indices"] = tuple(data["indices"])
    return cls(**data)


@dataclass
class GameRecord:
    seed: int
    map_name: str
    player_ids: List[str]
    actions: List[Tuple[str, Action]]

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "mapName": self.map_name,
            "playerIds": list(self.player_ids),
            "actions": [
                {"playerId": player_id, **action_to_dict(action)}
                for player_id, action in self.actions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameRecord":
        actions = []
        for row in data["actions"]:
            row = dict(row)
            player_id = row.pop("playerId")
            actions.append((player_id, action_from_dict(row)))
        return cls(
            seed=data["seed"],
            map_name=data["mapName"],
            player_ids=list(data["playerIds"]),
            actions=actions,
        )


class ScriptedBot:
    """Feeds back a recorded action stream; never consults the view."""

    def __init__(self, script: List[Action]):
        self._script = deque(script)

    def set_player(self, player):
        self.player = player

    def act(self, view, legal_actions):
        return self._script.popleft()


class _SilentLogger:
    def record_turn(self, *args, **kwargs):
        return None


def record_of(game: Game) -> GameRecord:
    context = game.context
    return GameRecord(
        seed=context.seed,
        map_name=context.get_map().map_name,
        player_ids=[p.player_id for p in game.players],
        actions=list(context.action_log),
    )


def replay_game(record: GameRecord) -> Game:
    scripts = {
        player_id: [a for owner, a in record.actions if owner == player_id]
        for player_id in record.player_ids
    }
    players = [
        Player(player_id, ScriptedBot(scripts[player_id]), player_id, "gray")
        for player_id in record.player_ids
    ]
    context = GameContext(record.player_ids, map_name=record.map_name, seed=record.seed)
    game = Game(context, players, _SilentLogger(), 0)
    game.play()
    return game
```

- [ ] **Step 4: Run tests** — replay module PASS, full suite `OK`. If `test_replay_reproduces_the_game` fails on `action_log` equality but scores match, some engine path consumed RNG or made a decision outside `__choose` — find it before proceeding (the assert equality is the whole point of the phase).

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/replay.py services/native-runtime/src/ticket_to_ride/engine/state/game_context.py services/native-runtime/src/ticket_to_ride/engine/player.py quality/tests/test_replay.py
git commit -m "feat(engine): action log + deterministic (seed, actions) replay"
```

### Task 12: Wrap-up — suite, benchmark, doc note

- [ ] **Step 1: Full suite** — `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 2: Benchmark regression check** — the action model must not give back the hot-loop win. Run 5 seeded games with random act-bots and a no-op logger (reuse the pattern from `quality/tests/test_engine_actions.py::ActTurnFlowTests`, timed with `time.perf_counter()`). Expected: same order of magnitude as the pre-migration ~90 ms/game; investigate anything >2x slower (`legal_claim_actions` is the likely culprit — it enumerates color combos per turn).

- [ ] **Step 3: Doc note** — append a short section to `integrations/external/bots/random_bot.py`'s docstring cell (already done in Task 9) and update `docs/` only if a bots-authoring guide exists; otherwise skip (YAGNI).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(engine): action-model migration wrap-up"
```

---

## Self-review notes

- **Spec coverage:** (1) seeded RNG → Tasks 1-2; (2) data-only views → Tasks 3-5; (3) legal_actions + act() + LegacyBotAdapter → Tasks 6-10; (4) action logging with replay → Task 11. Wrap-up → Task 12.
- **Known risk concentrations:** Task 8 (every legacy bot must survive through the adapter — the full suite is the gate) and Task 11's log-equality assert (any RNG use outside the seeded stream breaks replay).
- **Deliberate behavior changes** (already accepted in prior discussion, all rules-conformant): setup keeps ≥2 tickets via one 3-offer instead of the old draw-twice retry; a legacy bot's second draw pick landing on a locomotive becomes a blind draw; forced claims/draws now come from menu absence instead of fault flags; `OpponentInfo.exposed_hand` is a copy.
- **Type consistency check:** `PlayerView(player_id, context, players, decision=..., ticket_offer=...)` (Tasks 3, 8); `attach(game_context, players)` + `game_context` property (Tasks 4, 6); `ClaimRoute(route_id, color, locomotives)` with `color="L"` for all-loco claims (Tasks 6, 7, 8, 10); `view.decision` strings `"turn" | "draw_second" | "keep_tickets"` (Tasks 3, 7, 8, 10).
