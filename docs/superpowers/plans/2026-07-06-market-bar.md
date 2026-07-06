# Market Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the InfoBarWidget placeholder with a live market bar — five face-up card rectangles, a draw-pile counter card, a discard counter card with a bin icon, and an SVG pie of draw odds — backed by rules-as-written deck reshuffling, public draw-odds on PlayerView, and replay-based turn-slider playback.

**Architecture:** The engine reshuffles the discard into the draw pile only when the draw pile is empty (official rules), and `legal_*` menus gate drawing on actual card availability. `PlayerView` gains the public discard composition and `draw_odds()` (unknown pool = 110-card composition minus face-up, discard, opponents' exposed cards, and own hand); `GlobalPrivateView` gains the true deck composition. Playback reconstructs the market at any slider step by replaying the recorded action log to that turn (no snapshot schema change). The widget is dumb: Python computes one `market` dict per (step, selected player) and the JS renders it; all colors come from `board_view.py`'s single color map, so changing a color there updates routes and market together.

**Tech Stack:** Python 3.14 + unittest (`uv run python -m unittest …`), anywidget/traitlets, hand-rolled SVG (no new JS deps), esbuild bundle via `npm run build`.

---

## Context for the executor

- Repo root: `/Users/lucasstarkey/Documents/GitHub/ticket_to_ride`. Run all commands from there.
- Run one test module: `uv run python -m unittest quality.tests.<module> -v`
- Run everything: `uv run python -m unittest discover -s quality/tests` → must end `OK` before every commit. The suite currently has 155 tests, all passing.
- Rebuild the widget JS bundle after editing anything under `applications/notebook_harness/widget-src/`:
  `cd applications/notebook_harness/widget-src && npm run build && cd ../../..`
  (esbuild writes to `applications/notebook_harness/static/`; the generated `static/*.js` files are committed.)
- The engine uses an action model: bots implement `act(view, legal_actions)`; menus come from `services/native-runtime/src/ticket_to_ride/engine/actions.py`. `PlayerView` (in `engine/state/views.py`) is data-only. Games are deterministic given `GameContext.seed`, and every chosen action is recorded in `context.action_log`; `engine/replay.py` can rebuild a game from `(seed, actions)`.
- Commit after each task with the message given in the task. End every commit message with:

```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

## File map

| File | Change |
|---|---|
| `services/native-runtime/src/ticket_to_ride/engine/actions.py` | Task 1: rules-as-written draw availability |
| `quality/tests/test_engine_actions.py` | Task 1: update empty-menu test, add availability tests |
| `services/native-runtime/src/ticket_to_ride/engine/state/decks.py` | Task 2: `deck_composition()` |
| `services/native-runtime/src/ticket_to_ride/engine/state/views.py` | Task 2: `discard_pile`, `unknown_pool()`, `draw_odds()`, `GlobalPrivateView.deck_composition()` |
| `quality/tests/test_player_view.py` | Task 2: odds tests |
| `services/native-runtime/src/ticket_to_ride/engine/game.py` | Task 3: extract `setup()` |
| `services/native-runtime/src/ticket_to_ride/engine/replay.py` | Task 3: `replay_to_turn()` |
| `quality/tests/test_replay.py` | Task 3: partial-replay tests |
| `services/native-runtime/src/ticket_to_ride/board_view.py` | Task 4: `card_color_hex()` |
| `applications/notebook_harness/game_runner.py` | Task 4: `HarnessGame.market_at()` + replay cache |
| `quality/tests/test_notebook_harness_game_runner.py` | Task 4: market_at tests |
| `applications/notebook_harness/info_bar_widget.py` | Task 5: `market` trait |
| `applications/notebook_harness/widget-src/src/info_bar_widget.js` | Task 5: market renderer |
| `applications/notebook_harness/static/info_bar_widget.css` | Task 5: market styles |
| `integrations/external/bots/example_bot.py`, `integrations/external/bots/random_bot.py` | Task 6: wire market into the display cells |

---

## Task 1: Rules-as-written draw availability

Today `legal_turn_actions` folds the discard into the draw pile whenever the pile is below 2 at a turn start, and blocks *all* drawing (even face-up) unless the pile has 2+ cards. Official rules: the discard reshuffles only when the draw pile is exhausted (`draw_face_down` and `_refill_face_up_slot` already do this); a blind draw needs at least one card across the two piles; face-up cards may be taken whenever the market has any.

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/actions.py:55-77` (legal_turn_actions)
- Test: `quality/tests/test_engine_actions.py`

- [ ] **Step 1: Update/add tests**

In `quality/tests/test_engine_actions.py`, replace the existing `test_empty_menu_is_pass` with:

```python
    def test_empty_menu_is_pass(self):
        context, player = _game_and_player()
        deck = context.get_train_deck()
        while len(deck):
            deck.draw_face_down()
        while deck.get_face_up():
            deck.draw_face_up(0)
        ticket_deck = context.get_ticket_deck()
        while len(ticket_deck) >= 3:
            ticket_deck.deal_unique(3)
        legal = legal_turn_actions(player)
        self.assertEqual(legal, [Pass()])
```

and add these two tests to `LegalMenuTests`:

```python
    def test_single_card_still_allows_drawing(self):
        context, player = _game_and_player()
        deck = context.get_train_deck()
        while len(deck) > 1:
            deck.draw_face_down()
        legal = legal_turn_actions(player)
        self.assertIn(DrawBlind(), legal)
        self.assertTrue(any(isinstance(a, DrawFaceUp) for a in legal))

    def test_face_up_takeable_when_piles_are_empty(self):
        context, player = _game_and_player()
        deck = context.get_train_deck()
        while len(deck):
            deck.draw_face_down()
        legal = legal_turn_actions(player)
        self.assertNotIn(DrawBlind(), legal)          # nothing to draw blind
        self.assertTrue(any(isinstance(a, DrawFaceUp) for a in legal))
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run python -m unittest quality.tests.test_engine_actions -v`
Expected: `test_single_card_still_allows_drawing` and `test_face_up_takeable_when_piles_are_empty` FAIL (the old `len(deck) >= 2` gate blocks them); the updated empty-menu test may pass already.

- [ ] **Step 3: Implement**

In `actions.py`, replace the deck block inside `legal_turn_actions`:

```python
    deck = game.get_train_deck()
    if len(deck) < 2:
        deck._reshuffle_discard()
    if len(deck) >= 2:
        actions.append(DrawBlind())
        actions.extend(DrawFaceUp(i, card) for i, card in enumerate(deck.get_face_up()))
```

with:

```python
    deck = game.get_train_deck()
    if len(deck) or deck.get_discard_pile():
        actions.append(DrawBlind())
    actions.extend(DrawFaceUp(i, card) for i, card in enumerate(deck.get_face_up()))
```

and update `legal_turn_actions`'s docstring second line from "Mirrors the old fault-flag rules: drawing needs 2+ cards in the deck (after folding the discard back in), tickets need a 3-card offer." to:

```python
    Rules as written: a blind draw needs at least one card across the draw
    and discard piles (the deck reshuffles the moment it empties), face-up
    cards are takeable whenever the market has any, tickets need a 3-card
    offer.
```

`legal_second_draw_actions` already follows these rules — do not change it.

- [ ] **Step 4: Run tests**

Run: `uv run python -m unittest quality.tests.test_engine_actions -v` → all pass.
Run: `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/actions.py quality/tests/test_engine_actions.py
git commit -m "fix(engine): draw availability follows the rulebook, not the old fault-flag gate"
```

## Task 2: Public draw odds on PlayerView; true deck composition on GlobalPrivateView

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/decks.py` (TrainCardDeck)
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/views.py` (PlayerView + GlobalPrivateView)
- Test: `quality/tests/test_player_view.py`

- [ ] **Step 1: Write the failing tests** (append to `quality/tests/test_player_view.py`)

```python
class DrawOddsTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=9)
        self.players = _make_players(self.context)

    def test_unknown_pool_accounts_for_all_public_information(self):
        deck = self.context.get_train_deck()
        # give p0 a known hand, p1 exposed + hidden cards, and a discard
        self.players[0].get_hand().update(["R", "R", "U"])
        self.players[1].get_hand().update(["G", "G", "Y"])
        self.players[1].exposed.update(["G", "G"])          # Y stays hidden
        deck.discard(["B", "B", "W"])

        view = PlayerView("p0", self.context, self.players)
        pool = view.unknown_pool()

        # pool = full composition - face-up - discard - own hand - exposed.
        # (The deck's locomotive mulligan may have discarded cards during
        # __init__, so compute the discard size instead of hardcoding 3.)
        discard_size = len(deck.get_discard_pile())
        self.assertEqual(pool.total(), 110 - 5 - discard_size - 3 - 2)
        # equivalently: draw pile + p1's hidden card
        self.assertEqual(pool.total(), len(deck) + 1)
        self.assertGreaterEqual(view.discard_pile["B"], 2)

    def test_draw_odds_sum_to_one(self):
        view = PlayerView("p0", self.context, self.players)
        odds = view.draw_odds()
        self.assertAlmostEqual(sum(odds.values()), 1.0)
        self.assertTrue(all(0 <= p <= 1 for p in odds.values()))

    def test_private_view_sees_true_deck_composition(self):
        from ticket_to_ride.engine.state.views import GlobalPrivateView

        deck = self.context.get_train_deck()
        composition = GlobalPrivateView(self.context, self.players).deck_composition()
        self.assertEqual(composition.total(), len(deck))
        drawn = deck.draw_face_down()
        after = GlobalPrivateView(self.context, self.players).deck_composition()
        self.assertEqual(after[drawn], composition[drawn] - 1)
```

Note: `test_unknown_pool_accounts_for_all_public_information` relies on fresh `Player`s having empty hands (the `_make_players` helper does not run setup), so the only cards outside the deck are the ones the test places.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m unittest quality.tests.test_player_view -v`
Expected: FAIL/ERROR — `PlayerView` has no `unknown_pool`.

- [ ] **Step 3: Implement**

In `decks.py`, add to `TrainCardDeck` (after `get_discard_pile`):

```python
    def deck_composition(self) -> 'Counter[str]':
        """Color counts of the face-down draw pile (contents, not order).

        This is hidden information: expose it only through GlobalPrivateView,
        never to bots.
        """
        return Counter(self._deck)
```

and add `from collections import Counter` to the imports at the top of `decks.py`.

In `views.py`:

1. Add `TrainCardDeck` to the decks import:
   `from ticket_to_ride.engine.state.decks import DestinationTicket, TrainCardDeck`
2. In `PlayerView.__init__`, right after `self.face_up_cards = ...`, add:

```python
        self.discard_pile: 'Counter[str]' = Counter(train_deck.get_discard_pile())
```

3. Add two methods to `PlayerView` (after `connection_cost`):

```python
    def unknown_pool(self) -> 'Counter[str]':
        """Color counts of every card this player cannot see: the draw pile
        plus opponents' hidden (face-down-drawn) cards. Computed purely from
        public information: the full 110-card composition minus the face-up
        market, the discard pile, opponents' exposed cards, and this
        player's own hand."""
        pool = Counter(TrainCardDeck.COLOR_COUNTS)
        pool.subtract(self.face_up_cards)
        pool.subtract(self.discard_pile)
        pool.subtract(self.hand)
        for opponent in self.opponents:
            pool.subtract(opponent.exposed_hand)
        return +pool  # drop zero/negative entries

    def draw_odds(self) -> Dict[str, float]:
        """Probability the next blind draw is each color, from this player's
        public information (the unknown pool). Empty dict if nothing is
        drawable."""
        pool = self.unknown_pool()
        total = pool.total()
        if not total:
            return {}
        return {color: count / total for color, count in sorted(pool.items())}
```

4. Add to `GlobalPrivateView`:

```python
    def deck_composition(self) -> 'Counter[str]':
        """True color counts of the face-down draw pile (spectator only)."""
        return self._context.get_train_deck().deck_composition()
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m unittest quality.tests.test_player_view -v` → all pass.
Run: `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/state/decks.py services/native-runtime/src/ticket_to_ride/engine/state/views.py quality/tests/test_player_view.py
git commit -m "feat(engine): public draw odds on PlayerView, true deck composition on GlobalPrivateView"
```

## Task 3: Partial replay — Game.setup() and replay_to_turn()

Slider step N shows the state recorded at the start of turn N, i.e. after setup plus turns 0..N-1. `replay_to_turn(record, N)` rebuilds exactly that.

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/game.py:41-53` (play)
- Modify: `services/native-runtime/src/ticket_to_ride/engine/replay.py`
- Test: `quality/tests/test_replay.py`

- [ ] **Step 1: Write the failing tests** (append to `quality/tests/test_replay.py`)

```python
class PartialReplayTests(unittest.TestCase):
    def test_replay_to_turn_is_deterministic_and_conserves_cards(self):
        from ticket_to_ride.engine.replay import replay_to_turn

        original = _play_recorded(seed=13)
        record = record_of(original)
        step = original.turn_index // 2

        a = replay_to_turn(record, step)
        b = replay_to_turn(record, step)
        self.assertEqual(a.turn_index, step)
        deck_a = a.context.get_train_deck()
        deck_b = b.context.get_train_deck()
        self.assertEqual(deck_a.get_face_up(), deck_b.get_face_up())
        self.assertEqual(len(deck_a), len(deck_b))
        self.assertEqual(len(deck_a.get_discard_pile()), len(deck_b.get_discard_pile()))
        total = (
            len(deck_a) + len(deck_a.get_discard_pile()) + len(deck_a.get_face_up())
            + sum(p.get_card_count() for p in a.players)
        )
        self.assertEqual(total, 110)

    def test_replay_to_turn_zero_is_post_setup(self):
        from ticket_to_ride.engine.replay import replay_to_turn

        original = _play_recorded(seed=13)
        game = replay_to_turn(record_of(original), 0)
        self.assertEqual(game.turn_index, 0)
        for player in game.players:
            self.assertEqual(player.get_card_count(), 4)   # setup deals 4 blind cards
            self.assertGreaterEqual(len(player.get_tickets()), 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m unittest quality.tests.test_replay -v`
Expected: FAIL/ERROR — no `replay_to_turn` in `ticket_to_ride.engine.replay`.

- [ ] **Step 3: Implement**

In `game.py`, split `play`:

```python
    def setup(self) -> None:
        """Deal starting hands and initial ticket offers to every seat."""
        for p in self.players:
            p.set_context(PlayerView(p.player_id, self.context, self.players), True)

    def play(self) -> None:
        """Run the core gameplay loop until an end condition is reached."""
        self.setup()
        while not self._is_game_over():
            self.next_turn()
            self._score_game(False)
        # Final round: once a player ends a turn with two trains or fewer,
        # every player (including them) gets one last turn.
        for _ in range(len(self.players)):
            self.next_turn()
            self._score_game(False)
        self._score_game(True)
```

(the `for p in self.players: p.set_context(...)` loop moves out of `play` unchanged.)

In `replay.py`, add after `replay_game`:

```python
def replay_to_turn(record: GameRecord, turn_count: int) -> Game:
    """Rebuild the game state as of the start of turn `turn_count`.

    That is: setup plus the first `turn_count` full turns — the state the
    logger snapshotted at slider step `turn_count`. Deterministic given the
    record (same seed, same scripted actions).
    """
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
    game.setup()
    for _ in range(turn_count):
        game.next_turn()
        game._score_game(False)
    return game
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m unittest quality.tests.test_replay -v` → all pass.
Run: `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/game.py services/native-runtime/src/ticket_to_ride/engine/replay.py quality/tests/test_replay.py
git commit -m "feat(engine): Game.setup() extraction and replay_to_turn partial replay"
```

## Task 4: Shared card colors and HarnessGame.market_at()

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/board_view.py:22-33`
- Modify: `applications/notebook_harness/game_runner.py` (HarnessGame)
- Test: `quality/tests/test_notebook_harness_game_runner.py`

- [ ] **Step 1: Write the failing tests** (append to `quality/tests/test_notebook_harness_game_runner.py`)

```python
class MarketAtTests(unittest.TestCase):
    def _played_game(self):
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()], seed=41)
        harness_game.play()
        return harness_game

    def test_market_at_step_zero_shows_the_post_setup_market(self):
        harness_game = self._played_game()
        market = harness_game.market_at(0)
        self.assertEqual(len(market["face_up"]), 5)
        # 110 cards - 5 face-up - 4 dealt to each of 2 seats, split between
        # the draw pile and any cards the locomotive mulligan discarded
        # during deck construction.
        self.assertEqual(market["deck_count"] + market["discard_count"], 110 - 5 - 8)
        # spectator pie = true draw pile
        self.assertEqual(sum(seg["count"] for seg in market["pie"]), market["deck_count"])
        self.assertIn("L", market["colors"])
        self.assertIn("R", market["colors"])

    def test_market_at_with_viewpoint_uses_the_public_pool(self):
        harness_game = self._played_game()
        step = harness_game.snapshot_count() - 1
        spectator = harness_game.market_at(step)
        viewer = harness_game.market_at(step, "bot_0")
        pie_total = sum(seg["count"] for seg in viewer["pie"])
        # public pool = draw pile + opponents' hidden cards >= true draw pile
        self.assertGreaterEqual(pie_total, spectator["deck_count"])
        self.assertEqual(viewer["deck_count"], spectator["deck_count"])

    def test_market_at_is_cached_and_consistent(self):
        harness_game = self._played_game()
        first = harness_game.market_at(3)
        second = harness_game.market_at(3)
        self.assertEqual(first["face_up"], second["face_up"])
        self.assertEqual(first["deck_count"], second["deck_count"])

    def test_card_color_hex_covers_all_card_colors(self):
        from ticket_to_ride.board_view import card_color_hex

        colors = card_color_hex()
        for letter in ["R", "B", "U", "G", "O", "P", "W", "Y", "L"]:
            self.assertRegex(colors[letter], r"^#[0-9a-fA-F]{6}$")
        self.assertNotIn("X", colors)   # gray is a route color, not a card
```

(`initialize_game` and `BootstrapRandomBot` are already imported at the top of this test file.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_game_runner -v`
Expected: FAIL/ERROR — `HarnessGame` has no `market_at`; no `card_color_hex` in board_view.

- [ ] **Step 3: Implement the color accessor**

In `board_view.py`, directly below the `_ROUTE_COLOR_HEX` dict, add:

```python
# Locomotive card color for market/odds displays. Routes never use this
# letter; teal is distinct from all eight route colors above.
_LOCOMOTIVE_HEX = "#17becf"


def card_color_hex() -> Dict[str, str]:
    """Card-color letter -> hex for market/odds displays.

    Derived from the same _ROUTE_COLOR_HEX map the route graph renders from
    (minus gray "X", which is a route color, not a card), plus the
    locomotive. Change a color in _ROUTE_COLOR_HEX and every widget updates.
    """
    colors = {letter: hex_ for letter, hex_ in _ROUTE_COLOR_HEX.items() if letter != "X"}
    colors["L"] = _LOCOMOTIVE_HEX
    return colors
```

- [ ] **Step 4: Implement market_at**

In `applications/notebook_harness/game_runner.py`:

1. Extend the imports:

```python
from dataclasses import dataclass, field

from ticket_to_ride.board_view import card_color_hex
from ticket_to_ride.engine.replay import record_of, replay_to_turn
from ticket_to_ride.engine.state.views import PlayerView
```

(the module currently imports `dataclass` only — add `field`; keep every existing import.)

2. In the `HarnessGame` dataclass, add a cache field after `logger: InMemoryGameLogger`:

```python
    _market_games: Dict[int, Game] = field(default_factory=dict, repr=False)
```

3. Add two methods to `HarnessGame` (after `board_at`):

```python
    def _replayed_game(self, step_index: int) -> Game:
        """Game state as of recorded step `step_index`, rebuilt by replaying
        the action log with the game's seed (and cached per step)."""
        game = self._market_games.get(step_index)
        if game is None:
            game = replay_to_turn(record_of(self.game), step_index)
            self._market_games[step_index] = game
        return game

    def market_at(self, step_index: int, viewpoint: 'str | None' = None) -> Dict[str, Any]:
        """Market payload for the InfoBarWidget as of the given recorded turn.

        Without a viewpoint the pie is the true draw-pile composition
        (spectator view). With a viewpoint player id it is that player's
        public-information unknown pool (draw pile + opponents' hidden
        cards) — the exact distribution PlayerView.draw_odds() gives bots.
        """
        replayed = self._replayed_game(step_index)
        deck = replayed.context.get_train_deck()

        if viewpoint is None:
            pie_counts = deck.deck_composition()
            pie_label = "Draw pile"
        else:
            view = PlayerView(viewpoint, replayed.context, replayed.players)
            pie_counts = view.unknown_pool()
            names = {p["id"]: p["name"] for p in self.roster()}
            pie_label = f"Unknown to {names.get(viewpoint, viewpoint)} (deck + hidden hands)"

        return {
            "face_up": deck.get_face_up(),
            "deck_count": len(deck),
            "discard_count": len(deck.get_discard_pile()),
            "pie": [
                {"color": color, "count": count}
                for color, count in sorted(pie_counts.items())
                if count > 0
            ],
            "pie_label": pie_label,
            "colors": card_color_hex(),
        }
```

- [ ] **Step 5: Run tests**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_game_runner -v` → all pass.
Run: `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 6: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/board_view.py applications/notebook_harness/game_runner.py quality/tests/test_notebook_harness_game_runner.py
git commit -m "feat(harness): market_at replay-backed market payload with shared card colors"
```

## Task 5: The market widget (Python trait + JS renderer + CSS + bundle)

**Files:**
- Modify: `applications/notebook_harness/info_bar_widget.py`
- Modify: `applications/notebook_harness/widget-src/src/info_bar_widget.js` (full replacement)
- Modify: `applications/notebook_harness/static/info_bar_widget.css` (full replacement)
- Rebuild: `applications/notebook_harness/static/info_bar_widget.js` (generated by esbuild)

There is no JS test harness; verification is the bundle building cleanly plus Task 6's smoke test.

- [ ] **Step 1: Replace `info_bar_widget.py`'s class body**

```python
class InfoBarWidget(anywidget.AnyWidget):
    """Market bar shown below the map: the five face-up cards, draw and
    discard pile counters, and a pie of draw odds.

    The notebook pushes one `market` dict per (turn-slider step, selected
    player) — see HarnessGame.market_at() for the payload shape. Card and
    pie colors arrive inside the payload (from board_view.card_color_hex),
    so recoloring routes recolors the market automatically.
    See ``applications/notebook_harness/widget-src/`` for the JS source this
    is bundled from.
    """

    _esm = files("notebook_harness").joinpath("static/info_bar_widget.js")
    _css = files("notebook_harness").joinpath("static/info_bar_widget.css")

    market = traitlets.Dict({}).tag(sync=True)
```

(the `placeholder_text` trait is deleted.)

- [ ] **Step 2: Replace `widget-src/src/info_bar_widget.js` entirely**

```javascript
// Market bar: five face-up cards, draw/discard pile counters, and an SVG
// pie of draw odds. Pure renderer — the notebook computes the `market`
// payload (HarnessGame.market_at) including the shared color map, so this
// file contains no card-color constants of its own.

const BIN_ICON = `
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M3 6h18"/>
  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
  <line x1="10" y1="11" x2="10" y2="17"/>
  <line x1="14" y1="11" x2="14" y2="17"/>
</svg>`;

function pie_slice_path(cx, cy, r, start_angle, end_angle) {
    const large_arc = end_angle - start_angle > Math.PI ? 1 : 0;
    const x0 = cx + r * Math.cos(start_angle);
    const y0 = cy + r * Math.sin(start_angle);
    const x1 = cx + r * Math.cos(end_angle);
    const y1 = cy + r * Math.sin(end_angle);
    return `M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 ${large_arc} 1 ${x1} ${y1} Z`;
}

function build_pie(segments, colors, label) {
    const size = 96;
    const c = size / 2;
    const r = c - 2;
    const total = segments.reduce((sum, seg) => sum + seg.count, 0);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.classList.add("market-pie");

    if (!total) {
        return svg;
    }
    if (segments.length === 1) {
        // a single full-circle slice has degenerate arc endpoints; use a circle
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", c);
        circle.setAttribute("cy", c);
        circle.setAttribute("r", r);
        circle.setAttribute("fill", colors[segments[0].color] || "#999");
        svg.appendChild(circle);
        return svg;
    }

    let angle = -Math.PI / 2; // start at 12 o'clock
    for (const seg of segments) {
        const sweep = (seg.count / total) * 2 * Math.PI;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", pie_slice_path(c, c, r, angle, angle + sweep));
        path.setAttribute("fill", colors[seg.color] || "#999");
        const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
        const pct = ((100 * seg.count) / total).toFixed(1);
        title.textContent = `${seg.color}: ${seg.count} (${pct}%) — ${label}`;
        path.appendChild(title);
        svg.appendChild(path);
        angle += sweep;
    }
    return svg;
}

function build_counted_card(count, className, inner) {
    const wrap = document.createElement("div");
    wrap.className = "market-slot";
    const number = document.createElement("div");
    number.className = "market-count";
    number.textContent = String(count);
    const card = document.createElement("div");
    card.className = `market-card ${className}`;
    if (inner) {
        card.innerHTML = inner;
    }
    wrap.appendChild(number);
    wrap.appendChild(card);
    return wrap;
}

function render({ model, el }) {
    el.classList.add("info-bar-widget");

    const draw = () => {
        el.replaceChildren();
        const market = model.get("market") || {};
        const colors = market.colors || {};

        const row = document.createElement("div");
        row.className = "market-row";

        // 1-5: the face-up market cards
        for (const letter of market.face_up || []) {
            const wrap = document.createElement("div");
            wrap.className = "market-slot";
            const spacer = document.createElement("div");
            spacer.className = "market-count market-count-empty";
            const card = document.createElement("div");
            card.className = "market-card";
            card.style.background = colors[letter] || "#999";
            if (letter === "L") {
                card.classList.add("market-card-locomotive");
            }
            card.title = letter;
            wrap.appendChild(spacer);
            wrap.appendChild(card);
            row.appendChild(wrap);
        }

        // 6: draw pile (grey, count above)
        row.appendChild(
            build_counted_card(market.deck_count ?? 0, "market-card-deck", "")
        );
        // 7: discard pile (bin icon, count above)
        row.appendChild(
            build_counted_card(market.discard_count ?? 0, "market-card-discard", BIN_ICON)
        );

        el.appendChild(row);

        // pie of draw odds, to the right
        const pie_wrap = document.createElement("div");
        pie_wrap.className = "market-pie-wrap";
        pie_wrap.appendChild(build_pie(market.pie || [], colors, market.pie_label || ""));
        const pie_label = document.createElement("div");
        pie_label.className = "market-pie-label";
        pie_label.textContent = market.pie_label || "";
        pie_wrap.appendChild(pie_label);
        el.appendChild(pie_wrap);
    };

    draw();
    model.on("change:market", draw);
}

export default { render };
```

- [ ] **Step 3: Replace `static/info_bar_widget.css` entirely**

```css
/* Colors for chrome come from marimo's theme variables (light-dark() aware),
   with light fallbacks for non-marimo hosts. Card colors arrive in the
   `market` payload from board_view.card_color_hex — never hardcode them
   here, or the "change colors once" guarantee breaks. */

.info-bar-widget {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 24px;
    min-height: 96px;
    padding: 8px 12px;
    border: 1px solid var(--border, #ccc);
    border-radius: 6px;
    background: var(--card, #fafafa);
    font-family: system-ui, sans-serif;
}

.market-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
}

.market-slot {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
}

.market-count {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    color: var(--foreground, #333);
    min-height: 15px;
}

.market-count-empty {
    visibility: hidden;
}

.market-card {
    width: 34px;
    height: 48px;
    border-radius: 4px;
    border: 1px solid var(--border, rgba(0, 0, 0, 0.25));
    box-sizing: border-box;
}

.market-card-locomotive {
    /* locomotives read as "wild": sheen over the payload-supplied color */
    background-image: linear-gradient(
        135deg,
        rgba(255, 255, 255, 0.55) 0%,
        rgba(255, 255, 255, 0) 45%,
        rgba(0, 0, 0, 0.18) 100%
    );
}

.market-card-deck {
    background: var(--muted-foreground, #9a9a9a);
}

.market-card-discard {
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border-style: dashed;
    color: var(--muted-foreground, #777);
}

.market-card-discard svg {
    width: 20px;
    height: 20px;
}

.market-pie-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
}

.market-pie {
    width: 96px;
    height: 96px;
}

.market-pie-label {
    font-size: 11px;
    color: var(--muted-foreground, #999);
    max-width: 200px;
    text-align: center;
}
```

- [ ] **Step 4: Rebuild the bundle and check it in**

```bash
cd applications/notebook_harness/widget-src && npm run build && cd ../../..
git status --short   # static/info_bar_widget.js (and build-stamped siblings) should show as modified
```

Expected: esbuild exits 0. (It rebuilds all three widgets; the route-graph/player-list bundles change only in their build stamp — commit them too.)

- [ ] **Step 5: Run the full suite** — `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 6: Commit**

```bash
git add applications/notebook_harness/info_bar_widget.py applications/notebook_harness/widget-src/src/info_bar_widget.js applications/notebook_harness/static/
git commit -m "feat(widgets): market bar UI — face-up cards, pile counters, draw-odds pie"
```

## Task 6: Wire the market into both bot notebooks

**Files:**
- Modify: `integrations/external/bots/example_bot.py` (two display cells near the bottom)
- Modify: `integrations/external/bots/random_bot.py` (same two cells — the notebooks share this structure verbatim)

- [ ] **Step 1: Update the widget-creation cell in BOTH notebook files**

Find (in each file):

```python
    # Placeholder: will show the market & per-color draw odds (public info only).
    info_bar = mo.ui.anywidget(InfoBarWidget())
```

Replace with:

```python
    info_bar = mo.ui.anywidget(InfoBarWidget(market=harness_game.market_at(0)))
```

- [ ] **Step 2: Update the display cell in BOTH notebook files**

Find:

```python
    viewpoint = player_list.value["selected_player"] or None
    nodes, edges = harness_game.board_at(int(step_slider.value["value"]), viewpoint)
    graph.data = build_graph_data(nodes, edges)
    mo.vstack([step_slider, mo.hstack([graph, player_list], align="start", justify="start"), info_bar])
```

Replace with:

```python
    viewpoint = player_list.value["selected_player"] or None
    step = int(step_slider.value["value"])
    nodes, edges = harness_game.board_at(step, viewpoint)
    graph.data = build_graph_data(nodes, edges)
    # Market follows the same step + selection: spectator sees the true draw
    # pile; a selected player sees their public-information odds pool.
    info_bar.market = harness_game.market_at(step, viewpoint)
    mo.vstack([step_slider, mo.hstack([graph, player_list], align="start", justify="start"), info_bar])
```

- [ ] **Step 3: Smoke-test the whole stack headlessly**

```bash
uv run python - <<'EOF'
import sys
sys.path.insert(0, "applications")
sys.path.insert(0, "integrations")
from notebook_harness.game_runner import available_bots, initialize_game
bots = available_bots()
game = initialize_game([bots["Example Bot"](), bots["Random Bot"]()], seed=3)
game.play()
last = game.snapshot_count() - 1
for step in (0, last // 2, last):
    spectator = game.market_at(step)
    viewer = game.market_at(step, "bot_0")
    assert len(spectator["face_up"]) <= 5
    assert sum(s["count"] for s in spectator["pie"]) == spectator["deck_count"]
    assert sum(s["count"] for s in viewer["pie"]) >= spectator["deck_count"]
    total = (
        spectator["deck_count"] + spectator["discard_count"]
        + len(spectator["face_up"])
    )
    assert total <= 110
print("market smoke ok:", game.market_at(last)["deck_count"], "cards in deck at final step")
EOF
```

Expected: prints `market smoke ok: ...` with no assertion errors.

- [ ] **Step 4: Full suite** — `uv run python -m unittest discover -s quality/tests` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add integrations/external/bots/example_bot.py integrations/external/bots/random_bot.py
git commit -m "feat(notebooks): market bar follows the turn slider and player selection"
```

## Task 7: Wrap-up

- [ ] **Step 1: Full suite one more time** — `uv run python -m unittest discover -s quality/tests` → `OK`.
- [ ] **Step 2: Confirm the working tree is clean** — `git status --short` shows nothing (everything committed in Tasks 1-6). If anything is left over, figure out which task missed it and amend that concern before finishing.

---

## Self-review notes

- **Spec coverage:** rules-as-written reshuffle → Task 1 (the empty-pile fold already lives in `draw_face_down`/`_refill_face_up_slot`; Task 1 removes the last non-rulebook gate). Draw odds for bots (own hand + discard + exposed hands) → Task 2. True composition for spectators → Task 2. Replay playback → Tasks 3-4. 5 cards + grey deck counter + bin discard counter + right-side pie → Task 5. Selection-dependent pie + slider coupling → Tasks 4 and 6. Automatic colors → Task 4's `card_color_hex` derived from `_ROUTE_COLOR_HEX` + Task 5's payload-driven renderer.
- **Type consistency:** payload keys `face_up` / `deck_count` / `discard_count` / `pie` (list of `{color, count}`) / `pie_label` / `colors` are identical in Task 4 (producer), Task 5 (renderer), and Task 6 (smoke test). `replay_to_turn(record, turn_count)` matches its Task 3 definition at the Task 4 call site.
- **Known risk:** Task 5 has no JS unit test — the checks are esbuild exiting 0 and Task 6's payload smoke test; visual confirmation happens when the user next opens the notebook.
