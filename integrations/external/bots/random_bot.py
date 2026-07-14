import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup(hide_code=True):
    import random

    from external.contracts.base_bot import ActionBot

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

    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers = spectate_controls(
        mo,
        bot_name=BOT_META["name"],
        bot_class=RandomBot,
        title=BOT_META["name"],
    )
    return map_picker, mo, seat_pickers


@app.cell(hide_code=True)
def _(map_picker, mo, seat_pickers):
    from notebook_harness.spectate import play_match

    harness_game = play_match(mo, map_picker, seat_pickers)
    return (harness_game,)


@app.cell(hide_code=True)
def _(harness_game, mo):
    from notebook_harness.spectate import spectate_widgets

    graph, player_list, info_bar, step_slider = spectate_widgets(mo, harness_game)
    return graph, info_bar, player_list, step_slider


@app.cell(hide_code=True)
def _(graph, harness_game, info_bar, mo, player_list, step_slider):
    from notebook_harness.spectate import spectate_view

    spectate_view(mo, harness_game, graph, player_list, info_bar, step_slider)
    return


if __name__ == "__main__":
    app.run()
