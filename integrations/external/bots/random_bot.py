import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup(hide_code=True):
    import random
    from typing import List

    from external.contracts.base_bot import BaseBot
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
