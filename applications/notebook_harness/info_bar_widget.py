from __future__ import annotations

from importlib.resources import files

import anywidget
import traitlets


class InfoBarWidget(anywidget.AnyWidget):
    """Market bar shown below the map: the five face-up cards, draw and
    discard pile counters, and a pie of draw odds.

    The notebook pushes one `market` dict per (turn-slider step, selected
    player) — see HarnessGame.market_at() for the payload shape. Card and
    pie colors arrive inside the payload (from board_view.card_color_hex),
    so recoloring routes recolors the market automatically.
    See ``applications/notebook_harness/widget-src/`` for the JS source this
    is bundled from.
    """

    _esm = files("notebook_harness").joinpath("static/info_bar_widget.js")
    _css = files("notebook_harness").joinpath("static/info_bar_widget.css")

    market = traitlets.Dict({}).tag(sync=True)
