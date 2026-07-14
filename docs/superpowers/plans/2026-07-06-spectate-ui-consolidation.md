# Spectate UI Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the five duplicated marimo spectate/debug UI cells out of every bot notebook into `applications/notebook_harness/spectate.py`, so each notebook (and the copyable bot template) carries only three one-call cells.

**Deliberate deviation from the spec:** The implementation skips the composite panel element and uses the spec's named fallback: each widget is returned and bound as its own notebook cell global. Marimo containers clone their children, and that reactivity cannot be proven headless; the separate-globals wiring is what the existing notebooks already proved in production. The helper API also passes `mo` explicitly so the six headless tests can exercise the UI wiring with a fake marimo object.

**Architecture:** Three functions — `spectate_controls` (pickers), `play_match` (game + widgets), `spectate_view` (slider-driven render) — each called from its own notebook cell. Interactive `mo.ui` elements are returned to the notebook and bound as cell globals, which is the reactive wiring the current notebooks already prove in production. The spec's composite-`panel` variant is intentionally NOT used: marimo containers clone their children and their reactivity can't be verified headless, so we implement the spec's named fallback (separate element globals) directly.

**Tech Stack:** Python 3.12, marimo 0.23.x (`uv sync --extra notebooks`), anywidget widgets in `applications/notebook_harness/`, unittest under `quality/tests/` (`uv run test`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-06-spectate-ui-consolidation-design.md`.
- Run tests with `uv run test` from the repo root (runs `unittest discover -s quality/tests`). Requires `uv sync --extra notebooks` to have been run once.
- Bot notebooks must remain valid marimo files: keep the `import marimo` / `app = marimo.App(...)` header, `@app.cell` function structure (params = consumed globals, `return` = exported globals), and the `if __name__ == "__main__": app.run()` footer.
- Bot notebooks must keep exposing `BOT_META` and their single `BaseBot` subclass at module scope (the backend `BotLoader` contract).
- The native runtime (`services/native-runtime/`) must not import from `integrations/external/`; `applications/notebook_harness/` MAY (it already does, via `game_runner.available_bots`).
- Marimo constraint honored throughout: a UI element's `.value` is only read in cells *other* than the one that created/bound it.
- Template placeholders must be exactly `your_bot_id`, `Your Bot Name`, `YourBotName` (the future New-Bot button string-replaces them).

---

### Task 1: `spectate.py` module with headless tests

**Files:**
- Create: `applications/notebook_harness/spectate.py`
- Test: `quality/tests/test_notebook_harness_spectate.py`

**Interfaces:**
- Consumes (existing): `notebook_harness.game_runner.initialize_game(bots, map_name=..., seed=...) -> HarnessGame`, `available_bots() -> dict[str, type]`, `list_maps() -> list[str]`; `HarnessGame.play() / roster() / board_at(step, viewpoint=None) -> (nodes, edges) / market_at(step, viewpoint=None) / snapshot_count()`; `route_graph_widget.RouteGraphWidget(data=...)` + `build_graph_data(nodes, edges)`; `player_list_widget.PlayerListWidget(players=...)` (traits: `players`, `selected_player`); `info_bar_widget.InfoBarWidget(market=...)`; `wigglystuff.PlaySlider(min_value, max_value, step, interval_ms)` (trait: `value`).
- Produces (used by Tasks 2–4):
  - `spectate_controls(local_bot_class: type) -> tuple[map_picker, seat_pickers, controls_view]` — `map_picker: mo.ui.dropdown` (value: map name str), `seat_pickers: mo.ui.array` of 5 dropdowns (value: `list[type | None]`), `controls_view`: displayable layout.
  - `play_match(map_picker, seat_pickers) -> tuple[SpectateSession, step_slider, player_list]` — `step_slider`/`player_list`: `mo.ui.anywidget` elements; raises marimo's stop for <2 seats.
  - `SpectateSession` dataclass: fields `harness_game: HarnessGame`, `graph`, `info_bar` (both `mo.ui.anywidget`).
  - `resolve_view(step_slider_value: dict, player_list_value: dict) -> tuple[int, str | None]`.
  - `spectate_view(session, step_slider, player_list) -> displayable layout`.

- [ ] **Step 1: Write the failing tests**

Create `quality/tests/test_notebook_harness_spectate.py`:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import list_maps
from notebook_harness.route_graph_widget import build_graph_data
from notebook_harness.spectate import (
    SpectateSession,
    play_match,
    resolve_view,
    spectate_controls,
    spectate_view,
)


class SpectateControlsTests(unittest.TestCase):
    def test_defaults_seat_the_local_bot_twice_on_the_first_map(self) -> None:
        map_picker, seat_pickers, controls_view = spectate_controls(RandomBot)

        self.assertEqual(map_picker.value, list_maps()[0])
        self.assertEqual(seat_pickers.value[:2], [RandomBot, RandomBot])
        self.assertEqual(seat_pickers.value[2:], [None, None, None])
        self.assertIsNotNone(controls_view)

    def test_injects_the_live_local_class_over_the_discovered_one(self) -> None:
        class EditedRandomBot(RandomBot):
            pass

        _, seat_pickers, _ = spectate_controls(EditedRandomBot)

        # The live (possibly just-edited) class wins the seat defaults, not
        # the on-disk class the loader discovered under the same META name.
        self.assertIs(seat_pickers.value[0], EditedRandomBot)
        self.assertIs(seat_pickers.value[1], EditedRandomBot)


class PlayMatchTests(unittest.TestCase):
    def test_plays_a_full_game_and_builds_widgets(self) -> None:
        map_picker, seat_pickers, _ = spectate_controls(RandomBot)

        session, step_slider, player_list = play_match(map_picker, seat_pickers)

        self.assertIsInstance(session, SpectateSession)
        self.assertGreater(session.harness_game.snapshot_count(), 0)
        self.assertIn("value", step_slider.value)
        self.assertIn("selected_player", player_list.value)
        self.assertEqual(
            player_list.value["players"], session.harness_game.roster()
        )

    def test_stops_when_fewer_than_two_seats_are_filled(self) -> None:
        fake_map = SimpleNamespace(value=list_maps()[0])
        fake_seats = SimpleNamespace(value=[RandomBot, None, None, None, None])

        with self.assertRaises(BaseException) as caught:
            play_match(fake_map, fake_seats)

        self.assertEqual(type(caught.exception).__name__, "MarimoStopError")


class ResolveViewTests(unittest.TestCase):
    def test_reads_step_and_viewpoint(self) -> None:
        step, viewpoint = resolve_view({"value": 7}, {"selected_player": "bot_1"})
        self.assertEqual((step, viewpoint), (7, "bot_1"))

    def test_empty_selection_means_spectator(self) -> None:
        step, viewpoint = resolve_view({"value": 0}, {"selected_player": ""})
        self.assertEqual((step, viewpoint), (0, None))


class SpectateViewTests(unittest.TestCase):
    def test_pushes_board_and_market_for_the_current_values_and_returns_layout(self) -> None:
        map_picker, seat_pickers, _ = spectate_controls(RandomBot)
        session, step_slider, player_list = play_match(map_picker, seat_pickers)

        layout = spectate_view(session, step_slider, player_list)

        # Widget defaults are step 0, no selection — the view must match them.
        expected_nodes, expected_edges = session.harness_game.board_at(0, None)
        self.assertEqual(session.graph.data, build_graph_data(expected_nodes, expected_edges))
        self.assertEqual(session.info_bar.market, session.harness_game.market_at(0, None))
        self.assertIsNotNone(layout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_spectate -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebook_harness.spectate'`

- [ ] **Step 3: Write the implementation**

Create `applications/notebook_harness/spectate.py`:

```python
"""The shared spectate/debug UI every bot notebook renders.

Each bot notebook calls these three functions from three consecutive cells
(see integrations/external/bots/random_bot.py). All layout, widgets, and
update logic live here so a UI change lands in every notebook at once.

Marimo wiring notes, load-bearing:
- A UI element's value can only be read reactively from a cell OTHER than
  the one that bound it to a global, so the pipeline needs three cells:
  controls -> game/widgets -> view.
- Elements are returned to the notebook and bound as cell globals (not
  wrapped in mo.ui containers): containers clone their children, and the
  separate-globals wiring is the pattern the notebooks already prove.
- spectate_view mutates the widgets play_match created instead of building
  new ones, so graph node positions persist across steps and only diffs
  animate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import marimo as mo
from wigglystuff import PlaySlider

from notebook_harness.game_runner import available_bots, initialize_game, list_maps
from notebook_harness.info_bar_widget import InfoBarWidget
from notebook_harness.player_list_widget import PlayerListWidget
from notebook_harness.route_graph_widget import RouteGraphWidget, build_graph_data

EMPTY_SEAT_LABEL = "(empty)"
SEAT_COUNT = 5


@dataclass
class SpectateSession:
    """One played game plus the write-only widgets the view pushes into."""

    harness_game: Any
    graph: Any
    info_bar: Any


def spectate_controls(local_bot_class: type) -> tuple[Any, Any, Any]:
    """Build the title + map/seat pickers for one bot notebook.

    Returns (map_picker, seat_pickers, controls_view). The notebook binds
    the two elements as globals and displays controls_view.
    """
    meta = dict(getattr(local_bot_class, "META", {}) or {})
    display_name = str(meta.get("name") or local_bot_class.__name__)

    # Every bot notebook on disk, plus this notebook's live class so edits
    # made there take effect without reloading.
    bot_options: dict[str, type | None] = {EMPTY_SEAT_LABEL: None, **available_bots()}
    bot_options[display_name] = local_bot_class

    map_names = list_maps()
    map_picker = mo.ui.dropdown(options=map_names, value=map_names[0], label="Map")
    seat_pickers = mo.ui.array(
        [
            mo.ui.dropdown(
                options=bot_options,
                value=display_name if index < 2 else EMPTY_SEAT_LABEL,
                label=f"Seat {index + 1}",
            )
            for index in range(SEAT_COUNT)
        ]
    )
    controls_view = mo.vstack(
        [
            mo.md(f"# {display_name} — spectate & debug").left(),
            mo.hstack([map_picker, seat_pickers], align="start", justify="start"),
        ]
    )
    return map_picker, seat_pickers, controls_view


def play_match(map_picker: Any, seat_pickers: Any) -> tuple[SpectateSession, Any, Any]:
    """Seat the picked bots, play a full game, and build the view widgets.

    Returns (session, step_slider, player_list). Widgets are created once
    per game — not per slider step — so the force simulation keeps running
    instead of restarting from scratch on every step.
    """
    seated_bot_classes = [bot_class for bot_class in seat_pickers.value if bot_class is not None]
    mo.stop(
        len(seated_bot_classes) < 2,
        mo.md("Pick bots for at least two seats to run a game."),
    )
    harness_game = initialize_game(
        [bot_class() for bot_class in seated_bot_classes], map_name=map_picker.value
    )
    harness_game.play()

    initial_nodes, initial_edges = harness_game.board_at(0)
    graph = mo.ui.anywidget(RouteGraphWidget(data=build_graph_data(initial_nodes, initial_edges)))
    player_list = mo.ui.anywidget(PlayerListWidget(players=harness_game.roster()))
    info_bar = mo.ui.anywidget(InfoBarWidget(market=harness_game.market_at(0)))
    step_slider = mo.ui.anywidget(
        PlaySlider(min_value=0, max_value=harness_game.snapshot_count() - 1, step=1, interval_ms=300)
    )
    return SpectateSession(harness_game, graph, info_bar), step_slider, player_list


def resolve_view(step_slider_value: dict, player_list_value: dict) -> tuple[int, str | None]:
    """Map raw widget values to (step, viewpoint); '' selection = spectator."""
    viewpoint = player_list_value.get("selected_player") or None
    step = int(step_slider_value.get("value", 0))
    return step, viewpoint


def spectate_view(session: SpectateSession, step_slider: Any, player_list: Any) -> Any:
    """Push the current step/selection into the widgets and return the layout.

    Selecting a player switches to their culled view (their network merged
    into single nodes, only routes they could still claim); the market
    follows the same step + selection — spectator sees the true draw pile,
    a selected player sees their public-information odds pool.
    """
    step, viewpoint = resolve_view(step_slider.value, player_list.value)
    nodes, edges = session.harness_game.board_at(step, viewpoint)
    session.graph.data = build_graph_data(nodes, edges)
    session.info_bar.market = session.harness_game.market_at(step, viewpoint)
    return mo.vstack(
        [
            step_slider,
            mo.hstack([session.graph, player_list], align="start", justify="start"),
            session.info_bar,
        ]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m unittest quality.tests.test_notebook_harness_spectate -v`
Expected: PASS (6 tests). Note: `test_injects_the_live_local_class_over_the_discovered_one` passes because `bot_options[display_name] = local_bot_class` overwrites the loader's entry for the same name — if it fails with `RandomBot` instead of `EditedRandomBot`, the override line is missing or ordered before the `available_bots()` spread.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run test`
Expected: `OK` (existing count + 6 new tests)

- [ ] **Step 6: Commit**

```bash
git add applications/notebook_harness/spectate.py quality/tests/test_notebook_harness_spectate.py
git commit -m "feat(harness): centralized spectate UI module for bot notebooks"
```

---

### Task 2: `random_bot.py` uses the consolidated cells

**Files:**
- Modify: `integrations/external/bots/random_bot.py` (setup block + all five `@app.cell` blocks)

**Interfaces:**
- Consumes: `notebook_harness.spectate.spectate_controls / play_match / spectate_view` exactly as defined in Task 1.
- Produces: `random_bot.py` still exposes `BOT_META` and `RandomBot` at module scope (loader contract) — unchanged.

- [ ] **Step 1: Trim the setup block**

In `integrations/external/bots/random_bot.py`, the setup block currently is:

```python
with app.setup(hide_code=True):
    import random

    from external.contracts.base_bot import ActionBot

    from wigglystuff import PlaySlider

    BOT_META = {
```

Remove the `from wigglystuff import PlaySlider` import (and its surrounding blank line) — it moved into spectate.py. Result:

```python
with app.setup(hide_code=True):
    import random

    from external.contracts.base_bot import ActionBot

    BOT_META = {
```

Leave `import random`, the `ActionBot` import, `BOT_META`, and the `RandomBot` class definition untouched.

- [ ] **Step 2: Replace the five UI cells with three**

Delete all five existing `@app.cell(hide_code=True)` blocks (everything between the end of the `RandomBot` class definition and the `if __name__ == "__main__":` footer) and insert:

```python
@app.cell(hide_code=True)
def _():
    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers, controls_view = spectate_controls(RandomBot)
    controls_view
    return map_picker, seat_pickers


@app.cell(hide_code=True)
def _(map_picker, seat_pickers):
    from notebook_harness.spectate import play_match

    session, step_slider, player_list = play_match(map_picker, seat_pickers)
    return player_list, session, step_slider


@app.cell(hide_code=True)
def _(player_list, session, step_slider):
    from notebook_harness.spectate import spectate_view

    spectate_view(session, step_slider, player_list)
    return
```

Keep the `if __name__ == "__main__": app.run()` footer.

- [ ] **Step 3: Verify the notebook still imports and the suite passes**

Run: `uv run python -c "from external.bots.random_bot import RandomBot, BOT_META; print(BOT_META['id'])"`
Expected: `random_bot`

Run: `uv run test`
Expected: `OK` (the loader-contract and harness tests all still pass)

- [ ] **Step 4: Commit**

```bash
git add integrations/external/bots/random_bot.py
git commit -m "refactor(bots): random_bot notebook uses the centralized spectate UI"
```

---

### Task 3: `example_bot.py` uses the consolidated cells

**Files:**
- Modify: `integrations/external/bots/example_bot.py` (the five `@app.cell` blocks at the end of the file, after the `ExampleBot` class definition)

**Interfaces:**
- Consumes: `notebook_harness.spectate.spectate_controls / play_match / spectate_view` exactly as defined in Task 1.
- Produces: `example_bot.py` still exposes `BOT_META` and `ExampleBot` at module scope — unchanged.

- [ ] **Step 1: Replace the five UI cells with three**

`example_bot.py`'s setup block has no widget imports to trim (its widget imports live inside the cells being deleted). Delete the five `@app.cell(hide_code=True)` blocks between the end of the `ExampleBot` class definition and the `if __name__ == "__main__":` footer, and insert:

```python
@app.cell(hide_code=True)
def _():
    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers, controls_view = spectate_controls(ExampleBot)
    controls_view
    return map_picker, seat_pickers


@app.cell(hide_code=True)
def _(map_picker, seat_pickers):
    from notebook_harness.spectate import play_match

    session, step_slider, player_list = play_match(map_picker, seat_pickers)
    return player_list, session, step_slider


@app.cell(hide_code=True)
def _(player_list, session, step_slider):
    from notebook_harness.spectate import spectate_view

    spectate_view(session, step_slider, player_list)
    return
```

Keep the `if __name__ == "__main__": app.run()` footer.

- [ ] **Step 2: Verify import and suite**

Run: `uv run python -c "from external.bots.example_bot import ExampleBot, BOT_META; print(BOT_META['id'])"`
Expected: `example_bot`

Run: `uv run test`
Expected: `OK` (including `test_example_bot.py`, which plays ExampleBot vs RandomBot)

- [ ] **Step 3: Commit**

```bash
git add integrations/external/bots/example_bot.py
git commit -m "refactor(bots): example_bot notebook uses the centralized spectate UI"
```

---

### Task 4: Template becomes a marimo notebook (the New-Bot copy source)

**Files:**
- Rewrite: `integrations/external/templates/bots/build_your_bot_here.py`
- Test: `quality/tests/test_bot_template.py` (create)
- Modify: `integrations/external/README.md` (one line about the template)

**Interfaces:**
- Consumes: `external.contracts.base_bot.ActionBot`; `notebook_harness.spectate` functions as defined in Task 1.
- Produces: the canonical scaffold a future New-Bot button copies into `integrations/external/bots/` and string-replaces. Placeholders (exact): `your_bot_id`, `Your Bot Name`, `YourBotName`.

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_bot_template.py`:

```python
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from external.contracts.base_bot import ActionBot

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "integrations" / "external" / "templates" / "bots" / "build_your_bot_here.py"
)


def load_template_module():
    spec = importlib.util.spec_from_file_location("bot_template", TEMPLATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BotTemplateTests(unittest.TestCase):
    def test_template_keeps_the_replaceable_placeholders(self) -> None:
        module = load_template_module()

        self.assertEqual(module.BOT_META["id"], "your_bot_id")
        self.assertEqual(module.BOT_META["name"], "Your Bot Name")
        self.assertTrue(hasattr(module, "YourBotName"))

    def test_template_bot_is_an_action_bot_that_picks_the_first_legal_action(self) -> None:
        module = load_template_module()

        self.assertTrue(issubclass(module.YourBotName, ActionBot))
        bot = module.YourBotName()
        sentinel = object()
        self.assertIs(bot.act(view=None, legal_actions=[sentinel, object()]), sentinel)

    def test_template_meta_matches_the_class_meta(self) -> None:
        module = load_template_module()

        self.assertIs(module.YourBotName.META, module.BOT_META)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest quality.tests.test_bot_template -v`
Expected: FAIL — the current template's `BOT_META["id"]` is not `your_bot_id` and it has no marimo structure yet (first assertion errors).

- [ ] **Step 3: Rewrite the template**

Replace the full contents of `integrations/external/templates/bots/build_your_bot_here.py` with:

```python
import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup(hide_code=True):
    from external.contracts.base_bot import ActionBot

    BOT_META = {
        "schema_version": 1,
        "id": "your_bot_id",
        "name": "Your Bot Name",
        "version": "0.1.0",
        "description": "Describe your strategy here.",
        "author": "Your Name",
        "tags": [],
    }


@app.class_definition
class YourBotName(ActionBot):
    """Your bot: implement act(view, legal_actions) -> one legal action.

    ``view`` is a PlayerView — a data-only view of everything your seat may
    see: ``hand``, ``tickets``, ``face_up_cards``, ``opponents``,
    ``affordable_routes()``, ``culled_map()``. ``legal_actions`` is a
    non-empty list of engine actions; return one of them. Returning anything
    outside the list makes the engine take ``legal_actions[0]`` instead.
    """

    META = BOT_META

    def act(self, view, legal_actions):
        return legal_actions[0]


@app.cell(hide_code=True)
def _():
    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers, controls_view = spectate_controls(YourBotName)
    controls_view
    return map_picker, seat_pickers


@app.cell(hide_code=True)
def _(map_picker, seat_pickers):
    from notebook_harness.spectate import play_match

    session, step_slider, player_list = play_match(map_picker, seat_pickers)
    return player_list, session, step_slider


@app.cell(hide_code=True)
def _(player_list, session, step_slider):
    from notebook_harness.spectate import spectate_view

    spectate_view(session, step_slider, player_list)
    return


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m unittest quality.tests.test_bot_template -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Update the external README's template line**

In `integrations/external/README.md`, change:

```markdown
- `templates/bots/` holds starter bot templates that are not discovered at runtime.
```

to:

```markdown
- `templates/bots/` holds the starter bot notebook (spectate UI included via `notebook_harness.spectate`); it is not discovered at runtime and is the copy source for creating new bots.
```

- [ ] **Step 6: Run the full suite**

Run: `uv run test`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add integrations/external/templates/bots/build_your_bot_here.py quality/tests/test_bot_template.py integrations/external/README.md
git commit -m "feat(templates): bot template is a marimo notebook with the shared spectate UI"
```

---

### Task 5: Manual marimo verification (interactive — needs a human)

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything above.
- Produces: confirmation that reactive wiring survives the move into library functions.

- [ ] **Step 1: Launch the random bot notebook**

Run: `uv run marimo edit integrations/external/bots/random_bot.py`
(Requires `uv sync --extra notebooks`. This opens a browser tab.)

- [ ] **Step 2: Verify the interactive behaviors**

1. The title, map picker, and 5 seat dropdowns render; seats 1–2 default to Random Bot.
2. Changing a seat to `(empty)` so fewer than 2 are filled shows "Pick bots for at least two seats to run a game." instead of a board.
3. With 2+ seats, the board, roster, market bar, and play slider render.
4. Dragging (or playing) the step slider advances the board and market — the view cell re-runs (this is the wiring the whole design leans on).
5. Clicking a player in the roster switches to their culled view; clicking them again returns to spectator view.
6. Node positions persist across slider steps (force simulation does not restart on every step).

- [ ] **Step 3: Spot-check the other notebooks**

Repeat step 2's checks 3–5 briefly for:
- `uv run marimo edit integrations/external/bots/example_bot.py`
- `uv run marimo edit integrations/external/templates/bots/build_your_bot_here.py`

- [ ] **Step 4: If anything fails**

The known failure mode is a widget interaction not re-running the view cell. If that happens, the wiring rule was broken somewhere: confirm each element is bound to a cell global (`map_picker`, `seat_pickers`, `step_slider`, `player_list`) and that no cell reads `.value` of an element it created. Fix in `spectate.py` or the notebook cells, re-run `uv run test`, and repeat this task.

## Browser Verification Checklist

Run these checks in a real browser after `uv sync --extra notebooks`:

- [ ] Launch `uv run marimo edit integrations/external/bots/random_bot.py`.
- [ ] Confirm the title, map picker, and five seat dropdowns render.
- [ ] Confirm seats 1 and 2 default to `Random Bot`; seats 3 through 5 default to `(empty)`.
- [ ] Change enough seats to `(empty)` that fewer than two seats are filled, and confirm the notebook stops with `Pick bots for at least two seats to run a game.` instead of rendering a board.
- [ ] Restore two or more filled seats and confirm the board, roster, market bar, and play slider render.
- [ ] Drag or play the slider and confirm the board and market update as the step changes.
- [ ] Click a player in the roster and confirm the board switches to that player's culled view.
- [ ] Click the selected player again and confirm the board returns to spectator view.
- [ ] Drag the slider across multiple steps and confirm node positions persist instead of restarting the graph simulation every step.
- [ ] Repeat the board/slider/player-selection checks for `uv run marimo edit integrations/external/bots/example_bot.py`.
- [ ] Repeat the board/slider/player-selection checks for `uv run marimo edit integrations/external/templates/bots/build_your_bot_here.py`.
