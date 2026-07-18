"""Composite spectate dashboard: the viewer replay dashboard's grid layout
rebuilt as one anywidget, embedding the route-graph and info-bar JS renderers.

Trait flow: Python pushes per-step payloads (board/market/leaderboard/stats/
tickets); JS owns playback interaction and writes `playback` and
`selected_player` back, which the spectate view cell reads reactively.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import anywidget
import traitlets

from notebook_harness.route_graph_widget import build_graph_data


class SpectateShellWidget(anywidget.AnyWidget):
    _esm = files("notebook_harness").joinpath("static/spectate_shell_widget.js")
    # Embedded render modules do not bring their standalone AnyWidget CSS
    # with them. Materialize one composite stylesheet so graph interactions,
    # market cards, and the shell grid render identically inside this widget.
    _css = "\n".join(
        files("notebook_harness").joinpath("static", name).read_text()
        for name in (
            "route_graph_widget.css",
            "info_bar_widget.css",
            "spectate_shell_widget.css",
        )
    )

    # Python -> JS payloads
    board = traitlets.Dict().tag(sync=True)
    market = traitlets.Dict().tag(sync=True)
    players = traitlets.List([]).tag(sync=True)
    leaderboard = traitlets.List([]).tag(sync=True)
    stats = traitlets.Dict().tag(sync=True)
    tickets = traitlets.List([]).tag(sync=True)
    # One atomic playback payload. The individual traits remain for the
    # standalone renderers and backwards compatibility, while the composite
    # shell reads this frame so it never combines two different turns.
    frame = traitlets.Dict().tag(sync=True)
    aggregates = traitlets.List([]).tag(sync=True)
    route_usage = traitlets.Dict().tag(sync=True)
    rounds_meta = traitlets.List([]).tag(sync=True)
    current_player = traitlets.Unicode("").tag(sync=True)

    # JS -> Python interaction
    playback = traitlets.Dict({"round": 0, "turn": 0}).tag(sync=True)
    selected_player = traitlets.Unicode("").tag(sync=True)
    route_usage_wins_only = traitlets.Bool(False).tag(sync=True)

    # playback tuning
    interval_ms = traitlets.Int(300).tag(sync=True)

    # route-graph passthroughs (same names RouteGraphWidget uses; the JS
    # facade maps the graph's `data` trait onto `board`)
    repulsion = traitlets.Int(80).tag(sync=True)
    link_distance_base = traitlets.Float(30).tag(sync=True)
    link_distance_scale = traitlets.Float(15).tag(sync=True)
    unclaimed_route_opacity = traitlets.Float(0.5, min=0.0, max=1.0).tag(sync=True)
    node_scale = traitlets.Float(3).tag(sync=True)
    node_size_feature = traitlets.Unicode("").tag(sync=True)
    colour_feature = traitlets.Unicode("").tag(sync=True)
    colour_scale_type = traitlets.Unicode("").tag(sync=True)
    selected_ids = traitlets.List([]).tag(sync=True)
    route_usage_selected_ids = traitlets.List([]).tag(sync=True)
    select_feature = traitlets.Unicode("").tag(sync=True)
    select_feature_value = traitlets.Unicode("").tag(sync=True)
    width = traitlets.Int(800).tag(sync=True)
    height = traitlets.Int(500).tag(sync=True)
    route_usage_height = traitlets.Int(420).tag(sync=True)


def _trait(shell: Any, name: str, default: Any) -> Any:
    """Read a trait off a raw widget or a mo.ui.anywidget wrapper."""
    value = getattr(shell, "value", None)
    if isinstance(value, dict) and name in value:
        return value[name]
    return getattr(shell, name, default)


def build_shell(series: Any) -> SpectateShellWidget:
    """Create the shell once per series, seeding static and step-0 traits."""
    shell = SpectateShellWidget(
        players=series.roster(),
        rounds_meta=series.rounds_meta(),
        aggregates=series.aggregates(),
    )
    update_shell(shell, series)
    return shell


def update_shell(shell: Any, series: Any) -> None:
    """Push the payloads for the shell's current playback step and selection."""
    playback = _trait(shell, "playback", {}) or {}
    round_index = min(max(int(playback.get("round", 0)), 0), series.round_count() - 1)
    turn_index = min(max(int(playback.get("turn", 0)), 0), series.turn_count(round_index) - 1)
    viewpoint = _trait(shell, "selected_player", "") or None

    nodes, edges = series.board_at(round_index, turn_index, viewpoint)
    active = series.active_player_at(round_index, turn_index)

    board = build_graph_data(nodes, edges, layout_key=viewpoint or "__full__")
    market = series.market_at(round_index, turn_index, viewpoint)
    leaderboard = series.leaderboard_at(round_index, turn_index)
    stats = series.stats_at(round_index, turn_index)
    tickets = series.tickets_at(round_index, turn_index, viewpoint or active)

    # This second graph is series-wide rather than tied to replay. With no
    # explicit player-card selection, keep it on the first seat so playback
    # does not make the aggregate heatmap jump from bot to bot each turn.
    usage_player = viewpoint or series.roster()[0]["id"]
    wins_only = bool(_trait(shell, "route_usage_wins_only", False))
    usage_nodes, usage_edges, usage_summary = series.route_usage(
        usage_player, wins_only=wins_only
    )
    route_usage = build_graph_data(
        usage_nodes,
        usage_edges,
        layout_key=f"__usage__:{usage_player}:{int(wins_only)}",
    )
    route_usage.update(usage_summary)

    # Publish the coherent frame first. JS redraws from this single trait;
    # the legacy trait assignments that follow cannot expose partial state.
    shell.frame = {
        "round": round_index,
        "turn": turn_index,
        "board": board,
        "market": market,
        "leaderboard": leaderboard,
        "stats": stats,
        "tickets": tickets,
        "ticket_player": viewpoint or active,
        "current_player": active,
    }
    shell.board = board
    shell.market = market
    shell.leaderboard = leaderboard
    shell.stats = stats
    shell.tickets = tickets
    shell.current_player = active
    if _trait(shell, "route_usage", {}) != route_usage:
        shell.route_usage = route_usage
