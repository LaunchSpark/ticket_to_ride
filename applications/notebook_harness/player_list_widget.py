from __future__ import annotations

from importlib.resources import files

import anywidget
import traitlets


class PlayerListWidget(anywidget.AnyWidget):
    """Roster panel shown beside the board: one row per seat with the seat's
    color swatch (matching that player's claim markers on the map) and name.

    ``players`` takes the list of ``{id, name, color}`` dicts produced by
    ``HarnessGame.roster()``.

    Rows behave like a self-clearing radio group: clicking a player selects
    them (``selected_player`` = their id), clicking a different player moves
    the selection, and clicking the selected player again clears it back to
    ``""`` (the default: nobody selected).

    See ``applications/notebook_harness/widget-src/`` for the JS source this
    is bundled from.
    """

    _esm = files("notebook_harness").joinpath("static/player_list_widget.js")
    _css = files("notebook_harness").joinpath("static/player_list_widget.css")

    players = traitlets.List([]).tag(sync=True)
    selected_player = traitlets.Unicode("").tag(sync=True)
