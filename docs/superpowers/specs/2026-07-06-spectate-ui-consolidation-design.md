# Spectate UI Consolidation — Design

**Date:** 2026-07-06
**Status:** Approved

## Problem

Every bot notebook carries ~90 lines of identical marimo UI cells: title, map/seat
pickers, game construction, widget creation, and the slider-driven render loop.
`integrations/external/bots/random_bot.py` and `integrations/external/bots/example_bot.py`
duplicate these five cells almost byte-for-byte; the only real differences are the title
string and which local bot class is injected into the seat options. Any UI change (new
widget, layout tweak, stats panel) must be hand-copied into every bot notebook, and every
future bot multiplies the problem.

This matters more because notebooks are the long-term manager UI for the project: the
website becomes a navigation plane between notebooks, and the notebook harness grows into
the main display for competitive matches. The spectate UI will change often; it must live
in one place.

A future "New Bot" button in the main UI will copy the bot template into
`integrations/external/bots/` and register it. The template must therefore be a complete,
minimal notebook whose UI comes entirely from centralized calls — nothing to regenerate,
nothing to drift.

## Constraint that shapes the design

Marimo never re-runs a UI element's defining cell on interaction. A value can only be
read reactively from a *different* cell than the one that created the element (this is
already documented inline in the current notebooks). A literal single-cell/single-call
design would freeze the step slider at 0. The minimum is three cells:

1. create pickers (read downstream)
2. read pickers → build game + create widgets (read downstream)
3. read slider/selection → push updates, render layout

Each cell contains exactly one harness function call, so the "change it in one place"
goal fully holds.

## Design

### New module: `applications/notebook_harness/spectate.py` (~120 lines)

Absorbs the five duplicated cells. Three public functions plus a small session dataclass.

**`spectate_controls(local_bot_class) -> composite mo.ui element`**

- Reads `META` off `local_bot_class` (all bots carry `META = BOT_META`).
- Renders: `# {name} — spectate & debug` title, map dropdown from `list_maps()`
  (first map default), and 5 seat dropdowns via `mo.ui.array`.
- Seat options: `{"(empty)": None, **available_bots(), META["name"]: local_bot_class}`.
  Injecting the live class keeps the edit-and-rerun loop working without reloading.
  Seats 1–2 default to the local bot, the rest to `(empty)`.
- Returns one composite `mo.ui` element (`mo.md(...).batch(...)` preferred for layout;
  `mo.ui.dictionary` as fallback) with
  `.value == {"map": <map name>, "seats": [<class | None>] * 5}`.
- The notebook cell's last expression displays it; being a single element bound to a
  notebook global is what makes picker changes re-run downstream cells.

**`play_match(controls) -> (SpectateSession, panel)`**

- Reads `controls.value`. `mo.stop` (works from library code — it raises
  `MarimoStopError`) with the existing "Pick bots for at least two seats" message when
  fewer than 2 seats are filled.
- `initialize_game([cls() for cls in seated], map_name=...)` then `play()`.
- Creates the widgets once per game, preserving force-simulation continuity:
  `RouteGraphWidget` (seeded with `board_at(0)`), `PlayerListWidget` (roster),
  `InfoBarWidget` (`market_at(0)`), and the `PlaySlider`
  (`max = snapshot_count() - 1`, `interval_ms=300`).
- Returns two values so each stays a one-liner cell assignment:
  - `session`: plain dataclass — `harness_game`, `graph`, `info_bar` (the write-only
    widgets), and the `build_graph_data` reference.
  - `panel`: composite `mo.ui` element holding the two *read* widgets (`step` slider,
    `players` list). Interacting with either re-runs any cell referencing `panel`.

**`spectate_view(session, panel) -> layout`**

- Reads `panel.value`: `step` and `selected_player` (viewpoint; `None` = spectator).
- Pushes `session.graph.data = build_graph_data(*board_at(step, viewpoint))` and
  `session.info_bar.market = market_at(step, viewpoint)` — mutating existing widget
  instances so node positions persist and only diffs animate, exactly as today.
- Returns the same layout as today: `vstack([slider, hstack([graph, players]), info_bar])`,
  pulling the slider/player-list child elements out of `panel` for placement.

### Bot notebooks

`random_bot.py` and `example_bot.py` each replace their five UI cells with three:

```python
@app.cell(hide_code=True)
def _():
    from notebook_harness.spectate import spectate_controls
    controls = spectate_controls(RandomBot)
    controls
    return (controls,)


@app.cell(hide_code=True)
def _(controls):
    from notebook_harness.spectate import play_match
    session, panel = play_match(controls)
    return panel, session


@app.cell(hide_code=True)
def _(panel, session):
    from notebook_harness.spectate import spectate_view
    spectate_view(session, panel)
    return
```

Setup blocks shrink accordingly (`PlaySlider` and widget imports move into spectate.py).

### Template: `integrations/external/templates/bots/build_your_bot_here.py`

Converted to a marimo notebook — the canonical scaffold the future New-Bot button copies
into `integrations/external/bots/` (the button/endpoint itself is out of scope):

- setup block: `BOT_META` with placeholder id `your_bot_id` / name `Your Bot Name`,
  `ActionBot` import.
- `@app.class_definition`: `YourBotName(ActionBot)` with `META = BOT_META` and an `act`
  returning `legal_actions[0]`, docstring explaining view/legal_actions.
- The same three spectate cells as the bots.
- Placeholders (`your_bot_id`, `YourBotName`, `Your Bot Name`) are chosen to be trivially
  string-replaceable by the future copy-and-register flow.
- Stays outside runtime discovery (templates/ is not scanned by the loader), unchanged.

### Testing

Headless, mirroring the existing `test_notebook_harness_*` style:

- `spectate_controls`: value shape is `{"map", "seats"}`; options include `(empty)`,
  discovered bots, and the injected local class; defaults seat the local bot twice.
- `play_match`: with a stubbed controls object (`SimpleNamespace(value=...)`), plays a
  full game; session exposes a completed `harness_game` and widgets; raises the stop for
  <2 seats.
- `spectate_view`: with faked panel values, asserts `graph.data` and `info_bar.market`
  update for a given step/viewpoint and the layout is returned.
- Both bot notebooks and the template still import cleanly with their class + `BOT_META`
  intact (loader contract).

### Error handling

- <2 seats: `mo.stop` with guidance message (existing behavior, now centralized).
- Malformed `controls` argument (not the composite element): clear `TypeError`/`ValueError`
  naming `spectate.py` so a notebook author knows where to look.
- Invalid map names surface `initialize_game`'s existing error.

## Known risk — validate first

Load-bearing marimo assumption: a composite UI element **created inside an imported
function** still triggers re-runs of cells referencing it, and its child widgets can be
placed individually into another cell's layout. This is documented marimo behavior for
composite elements bound to globals, but implementation step one is a scratch-notebook
proof (create controls + panel via imported functions, drag slider, confirm the view cell
re-runs). Fallback if child-placement or propagation fails: `play_match` returns the
slider and player list as separate globals — cells remain one-liners, API otherwise
unchanged.

## Out of scope

- The "New Bot" button/endpoint (future work; this design only makes the template ready
  to be its copy source).
- Any change to the bot-api HTTP protocol, engine, or viewer website.
- New widgets or layout changes (this is a pure consolidation; the win is that such
  changes become one-file edits afterward).
