import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup(hide_code=True):
    import random
    from typing import List

    from external.contracts.base_bot import ActionBot, BaseBot
    from ticket_to_ride.engine.state.map import Route
    from ticket_to_ride.engine.state.decks import DestinationTicket
    from wigglystuff import PlaySlider

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
class RandomBot(ActionBot):
    """Baseline bot: picks a uniformly random legal action.

    ``act`` receives a ``PlayerView`` (data-only view of everything the
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


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from notebook_harness.game_runner import initialize_game, list_maps

    mo.md("# Random Bot — spectate & debug").left()
    return initialize_game, list_maps, mo


@app.cell(hide_code=True)
def _(list_maps, mo):
    from notebook_harness.game_runner import available_bots

    # Every bot notebook on disk, plus this notebook's live class so edits
    # made here take effect without reloading.
    bot_options = {"(empty)": None, **available_bots()}
    bot_options[BOT_META["name"]] = RandomBot

    map_picker = mo.ui.dropdown(options=list_maps(), value=list_maps()[0], label="Map")
    seat_pickers = mo.ui.array(
        [
            mo.ui.dropdown(
                options=bot_options,
                value=BOT_META["name"] if index < 2 else "(empty)",
                label=f"Seat {index + 1}",
            )
            for index in range(5)
        ]
    )
    mo.hstack([map_picker, seat_pickers], align="start", justify="start")
    return map_picker, seat_pickers


@app.cell(hide_code=True)
def _(initialize_game, map_picker, mo, seat_pickers):
    seated_bot_classes = [bot_class for bot_class in seat_pickers.value if bot_class is not None]
    mo.stop(len(seated_bot_classes) < 2, mo.md("Pick bots for at least two seats to run a game."))
    harness_game = initialize_game(
        [bot_class() for bot_class in seated_bot_classes], map_name=map_picker.value
    )
    harness_game.play()
    return (harness_game,)


@app.cell(hide_code=True)
def _(harness_game, mo):
    # Created once per game (not per slider step) so the force simulation
    # keeps running instead of restarting from scratch on every step.
    from notebook_harness.info_bar_widget import InfoBarWidget
    from notebook_harness.player_list_widget import PlayerListWidget
    from notebook_harness.route_graph_widget import RouteGraphWidget, build_graph_data

    initial_nodes, initial_edges = harness_game.board_at(0)
    graph = mo.ui.anywidget(RouteGraphWidget(data=build_graph_data(initial_nodes, initial_edges)))
    player_list = mo.ui.anywidget(PlayerListWidget(players=harness_game.roster()))
    # Placeholder: will show the market & per-color draw odds (public info only).
    info_bar = mo.ui.anywidget(InfoBarWidget())
    # Must be created in a different cell than the one reading its value:
    # marimo never re-runs a UI element's defining cell on interaction, so a
    # same-cell read would freeze the map at step 0. It still *displays* in
    # the layout cell below.
    step_slider = mo.ui.anywidget(
        PlaySlider(min_value=0, max_value=harness_game.snapshot_count() - 1, step=1, interval_ms=300)
    )
    return build_graph_data, graph, info_bar, player_list, step_slider


@app.cell(hide_code=True)
def _(
    build_graph_data,
    graph,
    harness_game,
    info_bar,
    mo,
    player_list,
    step_slider,
):
    # Pushes each step's board state into the existing widget instance
    # instead of constructing a new one, so node positions persist across
    # steps and only the diff (newly claimed routes) animates.
    # Selecting a player in the list switches to their culled view: their
    # network merged into single nodes, showing only routes they could still
    # claim (that topology change intentionally restarts the simulation).
    viewpoint = player_list.value["selected_player"] or None
    nodes, edges = harness_game.board_at(int(step_slider.value["value"]), viewpoint)
    graph.data = build_graph_data(nodes, edges)
    mo.vstack([step_slider, mo.hstack([graph, player_list], align="start", justify="start"), info_bar])
    return


if __name__ == "__main__":
    app.run()
