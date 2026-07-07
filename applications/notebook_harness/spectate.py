"""The shared spectate/debug UI every bot notebook renders.

Each bot notebook calls these four functions from four consecutive cells
(see integrations/external/bots/random_bot.py). All layout, widgets, and
update logic live here so a UI change lands in every notebook at once.

Marimo wiring notes, load-bearing:
- Marimo never re-runs a UI element's defining cell on interaction, so a
  widget's value can only be read reactively from a *different* cell than
  the one that bound it to a global. That forces the four-cell pipeline:
  controls -> game -> widgets -> view.
- ``spectate_widgets`` creates the widgets once per game (its cell only
  re-runs when ``harness_game`` changes); ``spectate_view`` mutates those
  same instances on every slider/selection change, so graph node positions
  persist across steps and only diffs animate.
- ``mo`` is passed in explicitly (each cell does ``import marimo as mo``):
  the file-header ``import marimo`` is not visible inside the kernel's cell
  namespace, and the explicit parameter lets the headless tests drive the
  wiring with a fake marimo object.
"""

from __future__ import annotations

from typing import Any


def spectate_controls(mo: Any, *, bot_name: str, bot_class: type, title: str | None = None):
    """Create and display the map and seat picker controls for a bot notebook.

    ``bot_class`` is the notebook's live class, injected over the on-disk
    version the loader discovered so edits take effect without reloading.
    Returns (map_picker, seat_pickers) for the cell to bind as globals.
    """

    from notebook_harness.game_runner import available_bots, list_maps

    maps = list_maps()
    bot_options = {"(empty)": None, **available_bots()}
    bot_options[bot_name] = bot_class

    if title:
        mo.output.append(mo.md(f"# {title} - spectate & debug").left())

    map_picker = mo.ui.dropdown(options=maps, value=maps[0], label="Map")
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
    mo.output.append(mo.hstack([map_picker, seat_pickers], align="start", justify="start"))
    return map_picker, seat_pickers


def play_match(mo: Any, map_picker: Any, seat_pickers: Any):
    """Run the selected bot seats on the selected map."""

    from notebook_harness.game_runner import initialize_game

    seated_bot_classes = [bot_class for bot_class in seat_pickers.value if bot_class is not None]
    mo.stop(len(seated_bot_classes) < 2, mo.md("Pick bots for at least two seats to run a game."))

    harness_game = initialize_game(
        [bot_class() for bot_class in seated_bot_classes],
        map_name=map_picker.value,
    )
    harness_game.play()
    return harness_game


def spectate_widgets(mo: Any, harness_game: Any):
    """Create the board, roster, market, and playback widgets for one game.

    Created once per game — not per slider step — so the force simulation
    keeps running instead of restarting from scratch on every step. This
    cell renders nothing; ``spectate_view`` displays the widgets from the
    next cell, where their values can be read reactively.
    Returns (graph, player_list, info_bar, step_slider).
    """

    RouteGraphWidget, PlayerListWidget, InfoBarWidget, build_graph_data, PlaySlider = _load_widget_classes()
    initial_nodes, initial_edges = harness_game.board_at(0)
    graph = mo.ui.anywidget(RouteGraphWidget(data=build_graph_data(initial_nodes, initial_edges)))
    player_list = mo.ui.anywidget(PlayerListWidget(players=harness_game.roster()))
    info_bar = mo.ui.anywidget(InfoBarWidget(market=harness_game.market_at(0)))
    step_slider = mo.ui.anywidget(
        PlaySlider(
            min_value=0,
            max_value=harness_game.snapshot_count() - 1,
            step=1,
            interval_ms=300,
        )
    )
    return graph, player_list, info_bar, step_slider


def spectate_view(
    mo: Any,
    harness_game: Any,
    graph: Any,
    player_list: Any,
    info_bar: Any,
    step_slider: Any,
) -> None:
    """Push the current step/selection into the widgets and display the layout.

    Selecting a player switches to their culled view (their network merged
    into single nodes, only routes they could still claim); the market
    follows the same step + selection — a spectator sees the true draw
    pile, a selected player sees their public-information odds pool.
    """

    _, _, _, build_graph_data, _ = _load_widget_classes()
    viewpoint = _selected_player(player_list)
    step = _slider_step(step_slider)

    nodes, edges = harness_game.board_at(step, viewpoint)
    graph.data = build_graph_data(nodes, edges)
    info_bar.market = harness_game.market_at(step, viewpoint)
    mo.output.append(
        mo.vstack(
            [
                step_slider,
                mo.hstack([graph, player_list], align="start", justify="start"),
                info_bar,
            ]
        )
    )


def _selected_player(player_list: Any) -> str | None:
    value = getattr(player_list, "value", {})
    if isinstance(value, dict):
        selected = value.get("selected_player")
    else:
        selected = getattr(player_list, "selected_player", None)
    return selected or None


def _slider_step(step_slider: Any) -> int:
    value = getattr(step_slider, "value", 0)
    if isinstance(value, dict):
        value = value.get("value", 0)
    return int(value)


def _load_widget_classes():
    from wigglystuff import PlaySlider

    from notebook_harness.info_bar_widget import InfoBarWidget
    from notebook_harness.player_list_widget import PlayerListWidget
    from notebook_harness.route_graph_widget import RouteGraphWidget, build_graph_data

    return RouteGraphWidget, PlayerListWidget, InfoBarWidget, build_graph_data, PlaySlider
