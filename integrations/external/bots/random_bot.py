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

    from notebook_harness.game_runner import initialize_game, list_maps

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
def _(harness_game, mo):
    # Created once per game (not per slider step) so the force simulation
    # keeps running instead of restarting from scratch on every step.
    from notebook_harness.route_graph_widget import RouteGraphWidget, build_graph_data

    initial_nodes, initial_edges = harness_game.board_at(0)
    graph = mo.ui.anywidget(RouteGraphWidget(data=build_graph_data(initial_nodes, initial_edges)))
    return build_graph_data, graph


@app.cell
def _(build_graph_data, graph, harness_game, step_slider):
    # Pushes each step's board state into the existing widget instance
    # instead of constructing a new one, so node positions persist across
    # steps and only the diff (newly claimed routes) animates.
    nodes, edges = harness_game.board_at(int(step_slider.value["value"]))
    graph.data = build_graph_data(nodes, edges)
    graph
    return


if __name__ == "__main__":
    app.run()
