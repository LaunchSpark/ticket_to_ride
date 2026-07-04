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
        "id": "example_bot",
        "name": "Example Bot",
        "version": "1.0.0",
        "description": "Reference implementation for custom Ticket to Ride bots.",
        "author": "Lucas Starkey",
        "tags": ["example"],
    }


@app.class_definition
class ExampleBot(BaseBot):  # TODO: actually build the thing
    META = BOT_META

    # used to determine weather to
    # 1 = Draw
    # 2 = Claim
    # 3 = draw a destination ticket
    def choose_turn_action(self):
        """Select which action to take on a turn."""
        return random.randrange(1, 3)

    # choose what cards to draw
    def choose_draw_train_action(self) -> int:
        """Pick which train card position to draw from."""
        return random.randrange(-1, 5)

    # choose what routes to claim
    def choose_route_to_claim(self, claimable_routes: List[Route]) -> Route:
        """Select a route to claim from the provided options."""
        return claimable_routes[random.randrange(0, len(claimable_routes))]

    # choose what color to spend on a gray route
    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        """Decide which color cards to spend on a gray route."""
        return None

    # choose which destination tickets to keep
    def select_ticket_offer(self, offer: List[DestinationTicket]) -> List[DestinationTicket]:
        """Choose which destination tickets to keep from an offer."""
        return [offer[0], offer[1]]

    def path_finder(self, city1, city2):
        """Placeholder helper for possible path calculations."""
        return None


@app.cell
def _():
    import marimo as mo

    from notebook_harness.game_runner import initialize_game, list_maps

    mo.md("# Example Bot — spectate & debug").left()
    return initialize_game, list_maps, mo


@app.cell
def _(list_maps, mo):
    map_picker = mo.ui.dropdown(options=list_maps(), value=list_maps()[0], label="Map")
    map_picker
    return (map_picker,)


@app.cell
def _(initialize_game, map_picker):
    # Runs the freshly-edited ExampleBot against a second copy of itself.
    harness_game = initialize_game([ExampleBot(), ExampleBot()], map_name=map_picker.value)
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
    return build_graph_data, graph, info_bar, player_list


@app.cell
def _(build_graph_data, graph, harness_game, info_bar, mo, player_list, step_slider):
    # Pushes each step's board state into the existing widget instance
    # instead of constructing a new one, so node positions persist across
    # steps and only the diff (newly claimed routes) animates.
    nodes, edges = harness_game.board_at(int(step_slider.value["value"]))
    graph.data = build_graph_data(nodes, edges)
    mo.vstack([mo.hstack([graph, player_list], align="start", justify="start"), info_bar])
    return


if __name__ == "__main__":
    app.run()
