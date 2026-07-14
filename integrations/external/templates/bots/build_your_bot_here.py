import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup(hide_code=True):
    from typing import Any

    from external.contracts.base_bot import ActionBot

    BOT_META = {
        "schema_version": 1,
        "id": "your_bot_id",
        "name": "Your Bot Name",
        "version": "1.0.0",
        "description": "Describe the strategy or purpose of this bot.",
        "author": "",
        "tags": [],
    }


@app.class_definition
class YourBotName(ActionBot):
    META = BOT_META

    def act(self, view: Any, legal_actions: list[Any]) -> Any:
        """Choose and return one action from legal_actions."""
        return legal_actions[0]


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers = spectate_controls(
        mo,
        bot_name=BOT_META["name"],
        bot_class=YourBotName,
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
