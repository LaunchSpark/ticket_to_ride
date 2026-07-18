from __future__ import annotations

from importlib.resources import files

import anywidget
import traitlets


class RouteGraphWidget(anywidget.AnyWidget):
    """Force-directed board renderer forked from `graph_widget` (vasturiano/force-graph).

    Unlike wigglystuff's GraphWidget, link distance is a spring proportional to
    each edge's route length (``link_distance_base + link_distance_scale *
    edge["data"]["length"]``) rather than a fixed constant, and ``repulsion``
    is Python-tunable. See ``applications/notebook_harness/widget-src/`` for
    the JS source this is bundled from.
    """

    _esm = files("notebook_harness").joinpath("static/route_graph_widget.js")
    _css = files("notebook_harness").joinpath("static/route_graph_widget.css")

    data = traitlets.Dict().tag(sync=True)
    repulsion = traitlets.Int(80).tag(sync=True)
    link_distance_base = traitlets.Float(30).tag(sync=True)
    link_distance_scale = traitlets.Float(15).tag(sync=True)
    unclaimed_route_opacity = traitlets.Float(0.5, min=0.0, max=1.0).tag(sync=True)
    node_scale = traitlets.Float(3).tag(sync=True)
    node_size_feature = traitlets.Unicode("").tag(sync=True)
    colour_feature = traitlets.Unicode("").tag(sync=True)
    colour_scale_type = traitlets.Unicode("").tag(sync=True)
    selected_ids = traitlets.List([]).tag(sync=True)
    select_feature = traitlets.Unicode("").tag(sync=True)
    select_feature_value = traitlets.Unicode("").tag(sync=True)
    width = traitlets.Int(800).tag(sync=True)
    height = traitlets.Int(500).tag(sync=True)


def build_graph_data(
    nodes: list[dict], edges: list[dict], *, layout_key: str | None = None
) -> dict:
    """Wrap nodes/edges in the shape RouteGraphWidget expects.

    ``layout_key`` identifies a full or player-culled view. The renderer uses
    a key change to distinguish a view switch (seed positions, then settle)
    from an ordinary playback update (seed positions and remain frozen).
    """
    data = {"nodes": nodes, "links": edges}
    if layout_key is not None:
        data["layoutKey"] = layout_key
    return data
