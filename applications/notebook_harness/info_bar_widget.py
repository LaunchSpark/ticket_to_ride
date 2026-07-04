from __future__ import annotations

from importlib.resources import files

import anywidget
import traitlets


class InfoBarWidget(anywidget.AnyWidget):
    """Placeholder bar shown below the map and player list.

    Will eventually display the train-card market and the odds of drawing
    each card color, computed from public information only. For now it just
    reserves the space so the notebook layout is already in its final shape.
    See ``applications/notebook_harness/widget-src/`` for the JS source this
    is bundled from.
    """

    _esm = files("notebook_harness").joinpath("static/info_bar_widget.js")
    _css = files("notebook_harness").joinpath("static/info_bar_widget.css")

    placeholder_text = traitlets.Unicode("Market & draw odds — coming soon").tag(sync=True)
