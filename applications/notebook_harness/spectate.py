from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class SpectateWidgets:
    graph: Any
    player_list: Any
    info_bar: Any
    step_slider: Any
    build_graph_data: Callable[[list[dict], list[dict]], dict]


def spectate_controls(mo: Any, *, bot_name: str, bot_class: type, title: str | None = None):
    """Create the map and seat picker controls for a bot notebook."""

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


def spectate_view(mo: Any, harness_game: Any):
    """Create or update the board, roster, market, and playback controls."""

    widgets = _spectate_widgets(mo, harness_game)
    viewpoint = _selected_player(widgets.player_list)
    step = _slider_step(widgets.step_slider)

    nodes, edges = harness_game.board_at(step, viewpoint)
    widgets.graph.data = widgets.build_graph_data(nodes, edges)
    widgets.info_bar.market = harness_game.market_at(step, viewpoint)
    mo.output.append(
        mo.vstack(
            [
                widgets.step_slider,
                mo.hstack([widgets.graph, widgets.player_list], align="start", justify="start"),
                widgets.info_bar,
            ]
        )
    )
    return widgets.graph, widgets.player_list, widgets.info_bar, widgets.step_slider


def _spectate_widgets(mo: Any, harness_game: Any) -> SpectateWidgets:
    widgets = getattr(harness_game, "_spectate_widgets", None)
    if widgets is not None:
        return widgets

    RouteGraphWidget, PlayerListWidget, InfoBarWidget, build_graph_data, PlaySlider = _load_widget_classes()
    initial_nodes, initial_edges = harness_game.board_at(0)
    widgets = SpectateWidgets(
        graph=mo.ui.anywidget(RouteGraphWidget(data=build_graph_data(initial_nodes, initial_edges))),
        player_list=mo.ui.anywidget(PlayerListWidget(players=harness_game.roster())),
        info_bar=mo.ui.anywidget(InfoBarWidget(market=harness_game.market_at(0))),
        step_slider=mo.ui.anywidget(
            PlaySlider(
                min_value=0,
                max_value=harness_game.snapshot_count() - 1,
                step=1,
                interval_ms=300,
            )
        ),
        build_graph_data=build_graph_data,
    )
    harness_game._spectate_widgets = widgets
    return widgets


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
